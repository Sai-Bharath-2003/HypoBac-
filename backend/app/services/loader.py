"""
loader.py — Fixed version.
Key fix: builds HP→UniProt mapping by row position during ingest.
"""

import os
from app.core.config import WEKA_DIR, HYPO_DIR
from app.core.database import get_connection
from app.utils.parsers import parse_weka_csv, parse_hypo3_xlsx, file_hash


def _is_new_or_changed(conn, filepath):
    h = file_hash(filepath)
    row = conn.execute(
        "SELECT file_hash FROM ingested_files WHERE filepath=?", (filepath,)
    ).fetchone()
    if row is None:
        return True, h
    return row["file_hash"] != h, h


def _mark_ingested(conn, filepath, h):
    conn.execute("""
        INSERT INTO ingested_files (filepath, file_hash)
        VALUES (?,?)
        ON CONFLICT(filepath) DO UPDATE
            SET file_hash=excluded.file_hash, ingested_at=datetime('now')
    """, (filepath, h))


def load_all():
    summary = {
        "weka_rows": 0, "proteins_added": 0, "links_added": 0,
        "files_processed": [], "files_skipped": [], "errors": []
    }
    conn = get_connection()
    try:
        # Collect all files first so we can do the mapping
        weka_path = None
        hypo_path = None

        for folder, exts, key in [(WEKA_DIR, [".csv"], "weka"), (HYPO_DIR, [".xlsx",".xls"], "hypo")]:
            if not os.path.isdir(folder):
                continue
            for fname in sorted(os.listdir(folder)):
                fpath = os.path.join(folder, fname)
                if not os.path.isfile(fpath):
                    continue
                ext = os.path.splitext(fname)[1].lower()
                if ext not in exts:
                    continue
                needs, h = _is_new_or_changed(conn, fpath)
                if not needs:
                    summary["files_skipped"].append(fname)
                    continue
                if key == "weka":
                    weka_path = (fpath, h)
                else:
                    hypo_path = (fpath, h)

        # Parse both
        weka_rows = []
        hypo_data = {"proteins": [], "links": [], "ncbi": []}

        if weka_path:
            weka_rows = parse_weka_csv(weka_path[0])
        if hypo_path:
            hypo_data = parse_hypo3_xlsx(hypo_path[0])

        # ── Build URL lookup from Sheet 2 ────────────────────────────────────
        url_map = {}
        for lnk in hypo_data.get("links", []):
            url_map[lnk["uniprot_id"]] = lnk

        # ── Insert all proteins from Sheet 1 ─────────────────────────────────
        proteins = hypo_data.get("proteins", [])
        for i, p in enumerate(proteins):
            uid = p["uniprot_id"]
            # Row-position mapping: first 314 proteins map to HP1-HP314
            hp_label = f"HP{i+1}" if i < 314 else None
            urls = url_map.get(uid, {})
            conn.execute("""
                INSERT INTO hypo_proteins
                    (uniprot_id, is_repeat, related_ids, uniprot_url, fasta_url, hp_label, source_file)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(uniprot_id) DO UPDATE SET
                    is_repeat   = excluded.is_repeat,
                    related_ids = excluded.related_ids,
                    uniprot_url = COALESCE(excluded.uniprot_url, hypo_proteins.uniprot_url),
                    fasta_url   = COALESCE(excluded.fasta_url,   hypo_proteins.fasta_url),
                    hp_label    = COALESCE(excluded.hp_label,    hypo_proteins.hp_label),
                    source_file = excluded.source_file
            """, (
                uid, p["is_repeat"], p["related_ids"],
                urls.get("uniprot_url", f"https://rest.uniprot.org/uniprotkb/{uid}.txt"),
                urls.get("fasta_url",   f"https://rest.uniprot.org/uniprotkb/{uid}.fasta"),
                hp_label,
                p["source_file"]
            ))
            summary["proteins_added"] += 1

        # ── Insert WEKA scores and also set hp_label on proteins ─────────────
        for r in weka_rows:
            conn.execute("""
                INSERT INTO weka_scores
                    (hp_label, c1_protein_family, c2_orthology, c3_interaction,
                     c4_bbh, c5_sorting_signal, c6_pseudogene, c7_homology,
                     class_label, source_file)
                VALUES (:hp_label,:c1_protein_family,:c2_orthology,:c3_interaction,
                        :c4_bbh,:c5_sorting_signal,:c6_pseudogene,:c7_homology,
                        :class_label,:source_file)
                ON CONFLICT(hp_label) DO UPDATE SET
                    c1_protein_family=excluded.c1_protein_family,
                    c2_orthology=excluded.c2_orthology,
                    c3_interaction=excluded.c3_interaction,
                    c4_bbh=excluded.c4_bbh,
                    c5_sorting_signal=excluded.c5_sorting_signal,
                    c6_pseudogene=excluded.c6_pseudogene,
                    c7_homology=excluded.c7_homology,
                    class_label=excluded.class_label,
                    source_file=excluded.source_file
            """, r)
            summary["weka_rows"] += 1

        # ── Insert extra Sheet2 IDs not in Sheet1 ────────────────────────────
        for lnk in hypo_data.get("links", []):
            existing = conn.execute(
                "SELECT id FROM hypo_proteins WHERE uniprot_id=?", (lnk["uniprot_id"],)
            ).fetchone()
            if not existing:
                conn.execute("""
                    INSERT INTO hypo_proteins (uniprot_id, uniprot_url, fasta_url, source_file)
                    VALUES (?,?,?,?)
                    ON CONFLICT(uniprot_id) DO NOTHING
                """, (lnk["uniprot_id"], lnk["uniprot_url"], lnk["fasta_url"], lnk["source_file"]))
                summary["links_added"] += 1

        # Mark files ingested
        if weka_path:
            _mark_ingested(conn, weka_path[0], weka_path[1])
            summary["files_processed"].append(os.path.basename(weka_path[0]))
        if hypo_path:
            _mark_ingested(conn, hypo_path[0], hypo_path[1])
            summary["files_processed"].append(os.path.basename(hypo_path[0]))

        conn.commit()

        # Print the mapping for verification
        sample = conn.execute("""
            SELECT hp.uniprot_id, hp.hp_label, w.class_label
            FROM hypo_proteins hp
            LEFT JOIN weka_scores w ON w.hp_label = hp.hp_label
            WHERE hp.hp_label IS NOT NULL
            ORDER BY CAST(SUBSTR(hp.hp_label,3) AS INTEGER)
            LIMIT 5
        """).fetchall()
        print("[LOADER] Sample mapping:")
        for row in sample:
            print(f"  {row['hp_label']} → {row['uniprot_id']} (CLASS={row['class_label']})")

    except Exception as e:
        conn.rollback()
        summary["errors"].append(str(e))
        print(f"[LOADER] Error: {e}")
        import traceback; traceback.print_exc()
    finally:
        conn.close()

    print(f"[LOADER] Done. {summary}")
    return summary


def check_for_new_files():
    new_files, changed_files = [], []
    conn = get_connection()
    for folder in [WEKA_DIR, HYPO_DIR]:
        if not os.path.isdir(folder):
            continue
        for fname in os.listdir(folder):
            fpath = os.path.join(folder, fname)
            if not os.path.isfile(fpath):
                continue
            needs, _ = _is_new_or_changed(conn, fpath)
            if needs:
                existing = conn.execute(
                    "SELECT filepath FROM ingested_files WHERE filepath=?", (fpath,)
                ).fetchone()
                (changed_files if existing else new_files).append(fpath)
    conn.close()
    return {
        "new_files": new_files, "changed_files": changed_files,
        "has_updates": bool(new_files or changed_files)
    }
