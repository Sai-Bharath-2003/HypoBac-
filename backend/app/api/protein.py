"""
api/protein.py

GET /api/protein/<uniprot_id>   — full detail, triggers UniProt fetch if not cached
GET /api/weka                   — all 314 HP records with scores
GET /api/weka/<hp_label>        — single HP detail
GET /api/stats                  — summary counts
"""

from flask import Blueprint, jsonify, request
from app.core.database import get_connection
from app.services.uniprot import fetch_and_cache

protein_bp = Blueprint("protein", __name__)

SCORE_META = [
    ("c1_protein_family", "Protein Family Match",   "Does this HP match a known protein family?"),
    ("c2_orthology",      "Orthology",              "Does it have orthologs in other organisms?"),
    ("c3_interaction",    "Protein Interaction",    "Is it involved in known protein interactions?"),
    ("c4_bbh",            "BBH Score",              "Best Bidirectional BLAST Hit — confirms homology"),
    ("c5_sorting_signal", "Sorting Signal",         "Does it have a signal peptide or sorting motif?"),
    ("c6_pseudogene",     "Linked to Pseudogenes",  "Is it linked to pseudogenes in the genome?"),
    ("c7_homology",       "Homology Modelling",     "Can its 3D structure be modelled by homology?"),
]


@protein_bp.route("/api/protein/<path:uniprot_id>", methods=["GET"])
def protein_detail(uniprot_id):
    conn = get_connection()
    try:
        # Get hypo_proteins record
        hp_row = conn.execute(
            "SELECT * FROM hypo_proteins WHERE uniprot_id = ?", (uniprot_id,)
        ).fetchone()

        if not hp_row:
            return jsonify({"error": f"Protein '{uniprot_id}' not found in HypoBac"}), 404

        # Get or fetch UniProt data
        cached = conn.execute(
            "SELECT * FROM uniprot_cache WHERE uniprot_id = ? AND fetch_error IS NULL",
            (uniprot_id,)
        ).fetchone()

        if not cached:
            fetch_and_cache(uniprot_id)
            cached = conn.execute(
                "SELECT * FROM uniprot_cache WHERE uniprot_id = ?", (uniprot_id,)
            ).fetchone()

        # Get WEKA scores
        weka = None
        if hp_row["hp_label"]:
            w = conn.execute(
                "SELECT * FROM weka_scores WHERE hp_label = ?", (hp_row["hp_label"],)
            ).fetchone()
            if w:
                weka = _format_weka(w)

        # Related proteins
        related = []
        if hp_row["related_ids"]:
            for rid in hp_row["related_ids"].split():
                rid = rid.strip()
                if rid:
                    r_row = conn.execute(
                        "SELECT uniprot_id, hp_label FROM hypo_proteins WHERE uniprot_id = ?",
                        (rid,)
                    ).fetchone()
                    related.append({
                        "uniprot_id": rid,
                        "in_db": bool(r_row),
                        "hp_label": r_row["hp_label"] if r_row else None,
                    })

        return jsonify({
            "protein": {
                "uniprot_id":  uniprot_id,
                "hp_label":    hp_row["hp_label"],
                "is_repeat":   bool(hp_row["is_repeat"]),
                "uniprot_url": hp_row["uniprot_url"],
                "fasta_url":   hp_row["fasta_url"],
            },
            "annotation": {
                "organism":        cached["organism"]       if cached else None,
                "organism_taxon":  cached["organism_taxon"] if cached else None,
                "protein_name":    cached["protein_name"]   if cached else None,
                "gene_name":       cached["gene_name"]      if cached else None,
                "function":        cached["function_text"]  if cached else None,
                "domains":         cached["domains"]        if cached else None,
                "sequence_length": cached["sequence_length"] if cached else None,
                "sequence":        cached["sequence"]        if cached else None,
                "fetched_at":      cached["fetched_at"]      if cached else None,
            },
            "weka":    weka,
            "related": related,
        })
    finally:
        conn.close()


@protein_bp.route("/api/weka", methods=["GET"])
def list_weka():
    """All 314 HP records — supports ?class=0|1 filter."""
    class_filter = request.args.get("class")
    limit  = min(int(request.args.get("limit",  314)), 314)
    offset = max(int(request.args.get("offset",   0)),   0)

    conn = get_connection()
    try:
        if class_filter is not None:
            rows = conn.execute("""
                SELECT w.*, hp.uniprot_id, uc.organism, uc.protein_name
                FROM weka_scores w
                LEFT JOIN hypo_proteins hp ON hp.hp_label = w.hp_label
                LEFT JOIN uniprot_cache uc ON uc.uniprot_id = hp.uniprot_id
                WHERE w.class_label = ?
                ORDER BY w.hp_label
                LIMIT ? OFFSET ?
            """, (int(class_filter), limit, offset)).fetchall()
        else:
            rows = conn.execute("""
                SELECT w.*, hp.uniprot_id, uc.organism, uc.protein_name
                FROM weka_scores w
                LEFT JOIN hypo_proteins hp ON hp.hp_label = w.hp_label
                LEFT JOIN uniprot_cache uc ON uc.uniprot_id = hp.uniprot_id
                ORDER BY w.hp_label
                LIMIT ? OFFSET ?
            """, (limit, offset)).fetchall()

        return jsonify([_format_weka_row(r) for r in rows])
    finally:
        conn.close()


@protein_bp.route("/api/weka/<hp_label>", methods=["GET"])
def weka_detail(hp_label):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM weka_scores WHERE hp_label = ?", (hp_label.upper(),)
        ).fetchone()
        if not row:
            return jsonify({"error": f"HP label '{hp_label}' not found"}), 404
        return jsonify(_format_weka(row))
    finally:
        conn.close()


@protein_bp.route("/api/stats", methods=["GET"])
def stats():
    conn = get_connection()
    try:
        total_proteins = conn.execute("SELECT COUNT(*) FROM hypo_proteins").fetchone()[0]
        total_weka     = conn.execute("SELECT COUNT(*) FROM weka_scores").fetchone()[0]
        pathogenic     = conn.execute("SELECT COUNT(*) FROM weka_scores WHERE class_label=1").fetchone()[0]
        non_pathogenic = conn.execute("SELECT COUNT(*) FROM weka_scores WHERE class_label=0").fetchone()[0]
        cached         = conn.execute("SELECT COUNT(*) FROM uniprot_cache WHERE fetch_error IS NULL").fetchone()[0]
        repeats        = conn.execute("SELECT COUNT(*) FROM hypo_proteins WHERE is_repeat=1").fetchone()[0]

        return jsonify({
            "total_proteins": total_proteins,
            "total_weka":     total_weka,
            "pathogenic":     pathogenic,
            "non_pathogenic": non_pathogenic,
            "cached":         cached,
            "repeats":        repeats,
        })
    finally:
        conn.close()


# ── Formatters ────────────────────────────────────────────────────────────────

def _format_weka(row) -> dict:
    scores = []
    for field, label, description in SCORE_META:
        val = row[field]
        scores.append({
            "field":       field,
            "label":       label,
            "description": description,
            "value":       val,
            "hit":         bool(val) if val is not None else None,
        })
    total_hits = sum(1 for s in scores if s["hit"])
    return {
        "hp_label":    row["hp_label"],
        "class_label": row["class_label"],
        "class_text":  "Pathogenic" if row["class_label"] == 1 else "Non-pathogenic",
        "total_hits":  total_hits,
        "max_hits":    7,
        "scores":      scores,
    }


def _format_weka_row(row) -> dict:
    return {
        "hp_label":    row["hp_label"],
        "class_label": row["class_label"],
        "class_text":  "Pathogenic" if row["class_label"] == 1 else "Non-pathogenic",
        "uniprot_id":  row["uniprot_id"] if "uniprot_id" in row.keys() else None,
        "organism":    row["organism"]    if "organism"   in row.keys() else None,
        "protein_name":row["protein_name"] if "protein_name" in row.keys() else None,
        "c1": row["c1_protein_family"],
        "c2": row["c2_orthology"],
        "c3": row["c3_interaction"],
        "c4": row["c4_bbh"],
        "c5": row["c5_sorting_signal"],
        "c6": row["c6_pseudogene"],
        "c7": row["c7_homology"],
    }
