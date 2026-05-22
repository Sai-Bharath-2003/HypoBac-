from flask import Flask
from flask_cors import CORS

from app.core.database import init_db
from app.api.search  import search_bp
from app.api.protein import protein_bp
from app.api.data    import data_bp


def create_app():
    app = Flask(__name__)
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    init_db()

    app.register_blueprint(search_bp)
    app.register_blueprint(protein_bp)
    app.register_blueprint(data_bp)

    @app.route("/api/health", methods=["GET"])
    def health():
        return {"status": "ok", "service": "HypoBac Backend", "version": "1.0"}

    return app
