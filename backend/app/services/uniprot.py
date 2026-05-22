"""
uniprot.py — Fetches protein data from UniProt REST API on demand.

How it works:
  1. Frontend searches for "Streptococcus"
  2. Backend checks uniprot_cache — if found, return it
  3. If not cached, fetch https://rest.uniprot.org/uniprotkb/{id}.txt
  4. Parse organism, protein name, domains, function from the flat file
  5. Store in uniprot_cache so next search is instant
"""

import re
import urllib.request
import urllib.error
from app.core.config import UNIPROT_TEXT_URL
from app.core.database import get_connection


# ── UniProt flat file field parsers ──────────────────────────────────────────

def _parse_uniprot_text(text: str) -> dict:
    """
    Parse a UniProt flat file (.txt format).
    Extracts: organism, taxon, protein name, gene name, function, domains.
    """
    data = {
        "organism":        None,
        "organism_taxon":  None,
        "protein_name":    None,
        "gene_name":       None,
        "function_text":   None,
        "domains":         None,
        "sequence":        None,
        "sequence_length": None,
    }

    lines      = text.splitlines()
    in_seq     = False
    seq_lines  = []
    cc_block   = []
    ft_domains = []
    in_cc      = False

    for line in lines:
        tag = line[:2]
        val = line[5:].strip() if len(line) > 5 else ""

        # Organism
        if tag == "OS" and data["organism"] is None:
            data["organism"] = val.rstrip(".")

        # Taxonomy
        if tag == "OC" and data["organism_taxon"] is None:
            data["organism_taxon"] = val.rstrip(";.")

        # Protein name — RecName or SubName
        if tag == "DE":
            if "RecName: Full=" in val and data["protein_name"] is None:
                data["protein_name"] = val.split("Full=")[-1].rstrip(";")
            elif "SubName: Full=" in val and data["protein_name"] is None:
                data["protein_name"] = val.split("Full=")[-1].rstrip(";")

        # Gene name
        if tag == "GN" and data["gene_name"] is None:
            m = re.search(r"Name=([^;{]+)", val)
            if m:
                data["gene_name"] = m.group(1).strip()

        # Sequence length from SQ line
        if tag == "SQ":
            m = re.search(r"(\d+) AA", val)
            if m:
                data["sequence_length"] = int(m.group(1))
            in_seq = True
            continue

        # Sequence lines (indented with spaces, only letters)
        if in_seq:
            if tag == "//":
                in_seq = False
                data["sequence"] = "".join(seq_lines)
            else:
                seq_lines.append(re.sub(r"[^A-Z]", "", line.upper()))
            continue

        # Function from CC (comment) block
        if tag == "CC":
            if "-!- FUNCTION:" in val:
                in_cc = True
                cc_block.append(val.replace("-!- FUNCTION:", "").strip())
            elif in_cc:
                if val.startswith("-!-") or val.startswith("---"):
                    in_cc = False
                else:
                    cc_block.append(val)

        # Domain annotations from FT (feature table)
        if tag == "FT" and "DOMAIN" in val:
            ft_domains.append(
                re.sub(r"DOMAIN\s+\d+\.\.\d+", "", val)
                  .replace("/note=", "")
                  .replace('"', "")
                  .strip()
            )

    if cc_block:
        data["function_text"] = " ".join(cc_block)[:1000]

    if ft_domains:
        cleaned = [d for d in ft_domains if d and len(d) > 1]
        data["domains"] = ", ".join(cleaned[:10]) if cleaned else None

    return data


# ── Public fetch function ─────────────────────────────────────────────────────

def fetch_and_cache(uniprot_id: str) -> dict | None:
    """
    Fetch a protein from UniProt and cache it.
    Returns the cached row dict, or None on failure.
    """
    conn = get_connection()
    try:
        # Check cache first
        existing = conn.execute(
            "SELECT * FROM uniprot_cache WHERE uniprot_id = ? AND fetch_error IS NULL",
            (uniprot_id,)
        ).fetchone()
        if existing:
            return dict(existing)

        # Fetch from UniProt
        url = UNIPROT_TEXT_URL.format(uid=uniprot_id)
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "HypoBac/1.0 (bioclues.org; research)"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                text = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            _store_error(conn, uniprot_id, f"HTTP {e.code}")
            conn.commit()
            return None
        except Exception as e:
            _store_error(conn, uniprot_id, str(e))
            conn.commit()
            return None

        # Parse
        parsed = _parse_uniprot_text(text)

        # Store in cache
        conn.execute("""
            INSERT INTO uniprot_cache
                (uniprot_id, organism, organism_taxon, protein_name,
                 gene_name, function_text, domains, sequence, sequence_length)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(uniprot_id) DO UPDATE SET
                organism        = excluded.organism,
                organism_taxon  = excluded.organism_taxon,
                protein_name    = excluded.protein_name,
                gene_name       = excluded.gene_name,
                function_text   = excluded.function_text,
                domains         = excluded.domains,
                sequence        = excluded.sequence,
                sequence_length = excluded.sequence_length,
                fetched_at      = datetime('now'),
                fetch_error     = NULL
        """, (
            uniprot_id,
            parsed["organism"],
            parsed["organism_taxon"],
            parsed["protein_name"],
            parsed["gene_name"],
            parsed["function_text"],
            parsed["domains"],
            parsed["sequence"],
            parsed["sequence_length"],
        ))

        # Rebuild FTS
        try:
            conn.execute("INSERT INTO cache_fts(cache_fts) VALUES('rebuild')")
        except Exception:
            pass

        conn.commit()

        row = conn.execute(
            "SELECT * FROM uniprot_cache WHERE uniprot_id = ?", (uniprot_id,)
        ).fetchone()
        return dict(row) if row else None

    finally:
        conn.close()


def _store_error(conn, uniprot_id: str, error_msg: str):
    conn.execute("""
        INSERT INTO uniprot_cache (uniprot_id, fetch_error)
        VALUES (?, ?)
        ON CONFLICT(uniprot_id) DO UPDATE SET fetch_error = excluded.fetch_error,
                                              fetched_at  = datetime('now')
    """, (uniprot_id, error_msg))
