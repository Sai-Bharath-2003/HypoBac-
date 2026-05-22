from flask import Blueprint, jsonify
from app.services.loader import load_all, check_for_new_files
from app.core.database import get_connection

data_bp = Blueprint("data", __name__)


@data_bp.route("/api/data/check", methods=["GET"])
def check_data():
    result = check_for_new_files()
    return jsonify(result)


@data_bp.route("/api/data/refresh", methods=["POST"])
def refresh_data():
    summary = load_all()
    return jsonify({
        "success":          not bool(summary["errors"]),
        "files_processed":  summary["files_processed"],
        "files_skipped":    summary["files_skipped"],
        "weka_rows":        summary["weka_rows"],
        "proteins_added":   summary["proteins_added"],
        "links_added":      summary["links_added"],
        "errors":           summary["errors"],
    })


@data_bp.route("/api/data/status", methods=["GET"])
def data_status():
    conn = get_connection()
    try:
        ingested = conn.execute(
            "SELECT filepath, file_hash, ingested_at FROM ingested_files ORDER BY ingested_at DESC"
        ).fetchall()
        last = ingested[0] if ingested else None
        return jsonify({
            "ingested_files": [
                {"file": r["filepath"], "at": r["ingested_at"]} for r in ingested
            ],
            "last_ingested": {
                "file": last["filepath"] if last else None,
                "at":   last["ingested_at"] if last else None,
            }
        })
    finally:
        conn.close()
