"""
api/search.py — Fixed version.
Fixes: exact HP match, null uniprot_id guard, proper joins.
"""

from flask import Blueprint, request, jsonify
from app.core.database import get_connection

search_bp = Blueprint("search", __name__)


@search_bp.route("/api/search", methods=["GET"])
def search():
    q      = request.args.get("q", "").strip()
    stype  = request.args.get("type", "keyword").lower()
    limit  = min(int(request.args.get("limit", 20)), 100)
    offset = max(int(request.args.get("offset", 0)), 0)

    if not q:
        return jsonify({"results": [], "total": 0, "query": q, "type": stype})

    conn = get_connection()
    try:
        if stype == "hp":
            rows, total = _search_hp_exact(conn, q, limit, offset)
        elif stype == "uniprot":
            rows, total = _search_uniprot(conn, q, limit, offset)
        elif stype == "organism":
            rows, total = _search_organism(conn, q, limit, offset)
        elif stype == "domain":
            rows, total = _search_domain(conn, q, limit, offset)
        else:
            rows, total = _search_keyword(conn, q, limit, offset)

        return jsonify({
            "results": [_fmt(r) for r in rows if r["uniprot_id"]],
            "total":   total,
            "query":   q,
            "type":    stype,
        })
    finally:
        conn.close()


# ── Core query — always joins proteins + weka + cache ─────────────────────
BASE = """
    SELECT
        hp.uniprot_id,
        hp.hp_label,
        hp.is_repeat,
        hp.related_ids,
        hp.uniprot_url,
        hp.fasta_url,
        w.class_label,
        w.c1_protein_family, w.c2_orthology,   w.c3_interaction,
        w.c4_bbh,            w.c5_sorting_signal, w.c6_pseudogene,
        w.c7_homology,
        uc.organism,
        uc.protein_name,
        uc.domains,
        uc.sequence_length
    FROM hypo_proteins hp
    LEFT JOIN weka_scores   w  ON w.hp_label   = hp.hp_label
    LEFT JOIN uniprot_cache uc ON uc.uniprot_id = hp.uniprot_id
    WHERE hp.uniprot_id IS NOT NULL
"""


def _search_hp_exact(conn, q, limit, offset):
    """Exact HP label match — HP1 must not return HP10, HP100 etc."""
    q_upper = q.upper().strip()
    # Add HP prefix if user typed just a number
    if q_upper.isdigit():
        q_upper = "HP" + q_upper

    sql = BASE + " AND hp.hp_label = ? ORDER BY CAST(SUBSTR(hp.hp_label,3) AS INTEGER) LIMIT ? OFFSET ?"
    rows = conn.execute(sql, (q_upper, limit, offset)).fetchall()
    total = conn.execute(
        "SELECT COUNT(*) FROM hypo_proteins WHERE hp_label=? AND uniprot_id IS NOT NULL",
        (q_upper,)
    ).fetchone()[0]
    return rows, total


def _search_uniprot(conn, q, limit, offset):
    sql = BASE + " AND hp.uniprot_id LIKE ? ORDER BY hp.uniprot_id LIMIT ? OFFSET ?"
    pattern = f"%{q}%"
    rows = conn.execute(sql, (pattern, limit, offset)).fetchall()
    total = conn.execute(
        "SELECT COUNT(*) FROM hypo_proteins WHERE uniprot_id LIKE ? AND uniprot_id IS NOT NULL",
        (pattern,)
    ).fetchone()[0]
    return rows, total


def _search_organism(conn, q, limit, offset):
    """Search by organism name — only works for cached proteins."""
    pattern = f"%{q}%"
    sql = BASE + " AND uc.organism LIKE ? ORDER BY uc.organism, hp.uniprot_id LIMIT ? OFFSET ?"
    rows = conn.execute(sql, (pattern, limit, offset)).fetchall()
    total = conn.execute(
        """SELECT COUNT(*) FROM hypo_proteins hp
           JOIN uniprot_cache uc ON uc.uniprot_id=hp.uniprot_id
           WHERE uc.organism LIKE ? AND hp.uniprot_id IS NOT NULL""",
        (pattern,)
    ).fetchone()[0]
    return rows, total


def _search_domain(conn, q, limit, offset):
    """Search by domain keyword — only works for cached proteins."""
    pattern = f"%{q}%"
    sql = BASE + " AND (uc.domains LIKE ? OR uc.protein_name LIKE ? OR uc.function_text LIKE ?) ORDER BY hp.uniprot_id LIMIT ? OFFSET ?"
    rows = conn.execute(sql, (pattern, pattern, pattern, limit, offset)).fetchall()
    total = conn.execute(
        """SELECT COUNT(*) FROM hypo_proteins hp
           JOIN uniprot_cache uc ON uc.uniprot_id=hp.uniprot_id
           WHERE (uc.domains LIKE ? OR uc.protein_name LIKE ? OR uc.function_text LIKE ?)
             AND hp.uniprot_id IS NOT NULL""",
        (pattern, pattern, pattern)
    ).fetchone()[0]
    return rows, total


def _search_keyword(conn, q, limit, offset):
    """Keyword: searches UniProt ID, HP label, organism, protein name, domains."""
    pattern = f"%{q}%"
    sql = BASE + """ AND (
        hp.uniprot_id    LIKE ? OR
        hp.hp_label      LIKE ? OR
        uc.organism      LIKE ? OR
        uc.protein_name  LIKE ? OR
        uc.domains       LIKE ?
    ) ORDER BY hp.hp_label LIMIT ? OFFSET ?"""
    rows = conn.execute(sql, (pattern,)*5 + (limit, offset)).fetchall()
    total = conn.execute(
        """SELECT COUNT(*) FROM hypo_proteins hp
           LEFT JOIN uniprot_cache uc ON uc.uniprot_id=hp.uniprot_id
           WHERE (hp.uniprot_id LIKE ? OR hp.hp_label LIKE ?
              OR uc.organism LIKE ? OR uc.protein_name LIKE ?)
             AND hp.uniprot_id IS NOT NULL""",
        (pattern,)*4
    ).fetchone()[0]
    return rows, total


def _fmt(row) -> dict:
    return {
        "uniprot_id":    row["uniprot_id"],
        "hp_label":      row["hp_label"],
        "class_label":   row["class_label"],
        "class_text":    ("Pathogenic" if row["class_label"] == 1
                          else "Non-pathogenic" if row["class_label"] == 0
                          else "Unknown"),
        "organism":      row["organism"],
        "protein_name":  row["protein_name"],
        "domains":       row["domains"],
        "sequence_length": row["sequence_length"],
        "is_repeat":     bool(row["is_repeat"]),
        "uniprot_url":   row["uniprot_url"],
        "fasta_url":     row["fasta_url"],
        "scores": {
            "c1_protein_family": row["c1_protein_family"],
            "c2_orthology":      row["c2_orthology"],
            "c3_interaction":    row["c3_interaction"],
            "c4_bbh":            row["c4_bbh"],
            "c5_sorting_signal": row["c5_sorting_signal"],
            "c6_pseudogene":     row["c6_pseudogene"],
            "c7_homology":       row["c7_homology"],
        } if row["class_label"] is not None else None,
    }
