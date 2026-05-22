"""
parsers.py — reads every HypoBac data file and returns clean Python dicts.
Never touches the database — just reads files and returns data.
"""

import os
import re
import hashlib


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────

def file_hash(filepath: str) -> str:
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_int(val, default=None):
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _safe_float(val, default=None):
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


# ─────────────────────────────────────────────────────────────────────────────
# 1. WEKA CSV — 314 hypothetical proteins with 7 scores + CLASS
# ─────────────────────────────────────────────────────────────────────────────

def parse_weka_csv(filepath: str) -> list[dict]:
    """
    Reads WEKA_MERGING_SHEET.csv.
    Returns list of dicts — one per HP label.

    Columns used:
      HP | C1 Protein family | C2 Orthology | C3 Interaction | C4 BBH |
      C5 Sorting Signal | C6 Pseudogene | C7 Homology | CLASS
    """
    results = []
    try:
        import csv
        with open(filepath, newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                hp = str(row.get('HP', '')).strip()
                if not hp or not hp.startswith('HP'):
                    continue
                results.append({
                    'hp_label':          hp,
                    'c1_protein_family': _safe_int(row.get('Protein family Score (C1)')),
                    'c2_orthology':      _safe_float(row.get('Orthology Score (C2)')),
                    'c3_interaction':    _safe_int(row.get('Protein interaction Score (C3)')),
                    'c4_bbh':            _safe_int(row.get('BBH Score (C4)')),
                    'c5_sorting_signal': _safe_int(row.get('Sorting Signal Score (C5)')),
                    'c6_pseudogene':     _safe_int(row.get('HPs linked to Pseudogenes (C6)')),
                    'c7_homology':       _safe_int(row.get('Homology Modelling Score (C7)')),
                    'class_label':       _safe_int(row.get('CLASS')),
                    'source_file':       os.path.basename(filepath),
                })
    except Exception as e:
        print(f"[PARSER] Error reading WEKA CSV {filepath}: {e}")

    print(f"[PARSER] WEKA: {len(results)} HP records from {os.path.basename(filepath)}")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# 2. Hypo3 XLSX — 3 sheets
# ─────────────────────────────────────────────────────────────────────────────

def parse_hypo3_xlsx(filepath: str) -> dict:
    """
    Reads all 3 sheets from Hypo3_Protein_Ids__NEW_CHANGES_.xlsx.

    Returns:
    {
        "proteins":  [{uniprot_id, is_repeat, related_ids}],   ← Sheet 1 swiss_prot
        "links":     [{uniprot_id, uniprot_url, fasta_url}],   ← Sheet 2 992 unique IDs
        "ncbi":      [{ncbi_id, uniprot_id, uniprot_url, fasta_url}]  ← Sheet 3 (empty now)
    }
    """
    result = {"proteins": [], "links": [], "ncbi": []}

    try:
        import openpyxl
        wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)

        # ── Sheet 1: swiss_prot ───────────────────────────────────────────────
        # Columns: primary_id | is_repeat | related_ids (space-separated)
        if 'swiss_prot' in wb.sheetnames:
            ws = wb['swiss_prot']
            rows = list(ws.iter_rows(values_only=True))
            # Row 0 is the header row (first actual ID is in row 0 col 0)
            # The XLSX has no proper header — row 0 IS data (A0AUZ9 is a real ID)
            for row in rows:
                uid = str(row[0]).strip() if row[0] else ''
                if not uid or uid == 'None' or len(uid) < 4:
                    continue
                is_repeat_raw = str(row[1]).strip().lower() if row[1] else ''
                is_repeat = 1 if is_repeat_raw == 'repeat' else 0
                related_raw = str(row[2]).strip() if row[2] else ''
                related = related_raw if related_raw != 'None' else ''
                result["proteins"].append({
                    "uniprot_id":  uid,
                    "is_repeat":   is_repeat,
                    "related_ids": related,
                    "source_file": os.path.basename(filepath),
                })

        # ── Sheet 2: 992 unique Hypo2 IDs ────────────────────────────────────
        # Columns: Protein IDs | (blank) | UniProt URL | FASTA URL
        sheet2_name = '992 uniqe Hypo2 IDs'
        if sheet2_name in wb.sheetnames:
            ws2 = wb[sheet2_name]
            rows2 = list(ws2.iter_rows(values_only=True))
            for row in rows2:
                uid = str(row[0]).strip() if row[0] else ''
                if not uid or uid == 'None' or uid == 'Protein IDs':
                    continue
                uniprot_url = str(row[2]).strip() if len(row) > 2 and row[2] else \
                    f"https://rest.uniprot.org/uniprotkb/{uid}.txt"
                fasta_url   = str(row[3]).strip() if len(row) > 3 and row[3] else \
                    f"https://rest.uniprot.org/uniprotkb/{uid}.fasta"
                result["links"].append({
                    "uniprot_id":   uid,
                    "uniprot_url":  uniprot_url,
                    "fasta_url":    fasta_url,
                    "source_file":  os.path.basename(filepath),
                })

        # ── Sheet 3: 604 new unique Hypo2 IDs (empty now) ────────────────────
        sheet3_name = '604 new uniqe Hypo2 IDs'
        if sheet3_name in wb.sheetnames:
            ws3 = wb[sheet3_name]
            rows3 = list(ws3.iter_rows(values_only=True))
            for row in rows3:
                if not any(row):
                    continue
                ncbi_id     = str(row[0]).strip() if row[0] else ''
                uid         = str(row[1]).strip() if len(row) > 1 and row[1] else ''
                uniprot_url = str(row[2]).strip() if len(row) > 2 and row[2] else ''
                fasta_url   = str(row[3]).strip() if len(row) > 3 and row[3] else ''
                if ncbi_id or uid:
                    result["ncbi"].append({
                        "ncbi_id":     ncbi_id,
                        "uniprot_id":  uid,
                        "uniprot_url": uniprot_url,
                        "fasta_url":   fasta_url,
                        "source_file": os.path.basename(filepath),
                    })

        wb.close()

    except Exception as e:
        print(f"[PARSER] Error reading Hypo3 XLSX {filepath}: {e}")

    print(f"[PARSER] Hypo3: {len(result['proteins'])} proteins (Sheet1), "
          f"{len(result['links'])} links (Sheet2), "
          f"{len(result['ncbi'])} NCBI entries (Sheet3)")
    return result
