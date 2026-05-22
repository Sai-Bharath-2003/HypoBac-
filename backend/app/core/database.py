import sqlite3
from app.core.config import DB_PATH


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_connection()
    cur  = conn.cursor()

    # ── hypo_proteins ─────────────────────────────────────────────────────────
    # One row per UniProt protein ID from the Hypo3 XLSX
    cur.execute("""
        CREATE TABLE IF NOT EXISTS hypo_proteins (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            uniprot_id  TEXT    NOT NULL UNIQUE,   -- e.g. A0AVK6
            is_repeat   INTEGER NOT NULL DEFAULT 0, -- 1 if marked 'repeat'
            related_ids TEXT,                       -- space-separated related IDs
            uniprot_url TEXT,                       -- live .txt link from sheet 2
            fasta_url   TEXT,                       -- live .fasta link from sheet 2
            hp_label    TEXT,                       -- e.g. HP47 (set if mapped to WEKA)
            source_file TEXT
        )
    """)

    # ── weka_scores ───────────────────────────────────────────────────────────
    # One row per HP label (HP1–HP314) from the WEKA CSV
    cur.execute("""
        CREATE TABLE IF NOT EXISTS weka_scores (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            hp_label    TEXT    NOT NULL UNIQUE,   -- HP1, HP2 … HP314
            c1_protein_family   INTEGER,
            c2_orthology        REAL,
            c3_interaction      INTEGER,
            c4_bbh              INTEGER,
            c5_sorting_signal   INTEGER,
            c6_pseudogene       INTEGER,
            c7_homology         INTEGER,
            class_label         INTEGER,           -- 0 or 1
            source_file         TEXT
        )
    """)

    # ── uniprot_cache ─────────────────────────────────────────────────────────
    # Fetched-on-demand from UniProt REST API, cached here so we don't
    # re-fetch on every search
    cur.execute("""
        CREATE TABLE IF NOT EXISTS uniprot_cache (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            uniprot_id      TEXT    NOT NULL UNIQUE,
            organism        TEXT,
            organism_taxon  TEXT,
            protein_name    TEXT,
            gene_name       TEXT,
            function_text   TEXT,
            domains         TEXT,   -- comma-separated domain names
            sequence        TEXT,   -- full amino-acid sequence
            sequence_length INTEGER,
            fetched_at      TEXT    NOT NULL DEFAULT (datetime('now')),
            fetch_error     TEXT    -- stores error message if fetch failed
        )
    """)

    # ── ingested_files ────────────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ingested_files (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            filepath    TEXT    NOT NULL UNIQUE,
            file_hash   TEXT    NOT NULL,
            ingested_at TEXT    NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # ── FTS on uniprot_cache ──────────────────────────────────────────────────
    cur.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS cache_fts
        USING fts5(
            uniprot_id, organism, protein_name, gene_name,
            function_text, domains,
            content='uniprot_cache', content_rowid='id'
        )
    """)

    conn.commit()
    conn.close()
    print(f"[DB] HypoBac database ready at {DB_PATH}")
