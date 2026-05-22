import os

_BACKEND_DIR  = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)

DATA_DIR          = os.environ.get("HYPOBAC_DATA_DIR", os.path.join(_PROJECT_ROOT, "data"))
WEKA_DIR          = os.path.join(DATA_DIR, "weka_scores")
HYPO_DIR          = os.path.join(DATA_DIR, "hypo_proteins")
DB_PATH           = os.environ.get("HYPOBAC_DB_PATH", os.path.join(_BACKEND_DIR, "hypobac.db"))

# UniProt REST base
UNIPROT_TEXT_URL  = "https://rest.uniprot.org/uniprotkb/{uid}.txt"
UNIPROT_FASTA_URL = "https://rest.uniprot.org/uniprotkb/{uid}.fasta"

# How many seconds to wait before re-fetching a cached UniProt entry
CACHE_TTL_DAYS = 30
