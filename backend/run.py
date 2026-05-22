"""
run.py — Start the HypoBac Flask backend.

Usage:
    cd backend
    python run.py

Starts on http://localhost:5001  (5001 so it doesn't clash with HoriGene on 5000)
"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.services.loader import load_all

app = create_app()

if __name__ == "__main__":
    print("=" * 60)
    print("  HypoBac Backend — Hypothetical Bacterial Protein Database")
    print("=" * 60)
    print("[STARTUP] Running initial data load...")
    summary = load_all()
    print(f"[STARTUP] Loaded {summary['weka_rows']} WEKA records, "
          f"{summary['proteins_added']} proteins, "
          f"{summary['links_added']} additional links.")
    if summary["errors"]:
        print(f"[STARTUP] Warnings: {summary['errors']}")
    print("[STARTUP] Starting Flask on http://localhost:5001")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5001, debug=True)
