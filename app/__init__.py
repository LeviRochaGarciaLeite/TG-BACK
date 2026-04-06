"""
Factory principal da aplicação Flask — Nexus API.
"""

import os
import logging
from flask import Flask, jsonify
from flask_jwt_extended import JWTManager
from flask_cors import CORS

from .models import db
from .config import config_map


def create_app(config_name: str | None = None) -> Flask:
    """
    Cria e configura a instância da aplicação Flask.
    Parâmetro config_name: 'development' | 'production' (padrão: variável ENV ou development).
    """
    app = Flask(__name__)

    # ── Configuração ───────────────────────────────────────────────────────
    env = config_name or os.environ.get("FLASK_ENV", "development")
    app.config.from_object(config_map.get(env, config_map["default"]))

    # ── Logging básico ─────────────────────────────────────────────────────
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    app.logger.setLevel(logging.INFO)

    # ── Extensões ──────────────────────────────────────────────────────────
    CORS(app, origins=app.config.get("CORS_ORIGINS", "*"))
    db.init_app(app)
    jwt = JWTManager(app)

    # ── Handlers de erro JWT ──────────────────────────────────────────────
    # Substitui as respostas padrão do flask-jwt-extended por JSON consistente

    @jwt.unauthorized_loader
    def missing_token_callback(reason):
        return jsonify({"erro": "Token de acesso ausente.", "detalhe": reason}), 401

    @jwt.invalid_token_loader
    def invalid_token_callback(reason):
        return jsonify({"erro": "Token inválido.", "detalhe": reason}), 401

    @jwt.expired_token_loader
    def expired_token_callback(jwt_header, jwt_payload):
        return jsonify({"erro": "Token expirado. Faça login novamente."}), 401

    @jwt.revoked_token_loader
    def revoked_token_callback(jwt_header, jwt_payload):
        return jsonify({"erro": "Token revogado."}), 401

    # ── Handler de erro genérico ───────────────────────────────────────────
    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"erro": "Rota não encontrada."}), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return jsonify({"erro": "Método não permitido."}), 405

    @app.errorhandler(500)
    def internal_error(e):
        app.logger.error(f"Erro interno: {e}", exc_info=True)
        return jsonify({"erro": "Erro interno do servidor."}), 500

    # ── Blueprints ─────────────────────────────────────────────────────────
    from .routes.auth import auth_bp
    from .routes.ponto import ponto_bp
    from .routes.gestor import gestor_bp

    app.register_blueprint(auth_bp,   url_prefix="/api/auth")
    app.register_blueprint(ponto_bp,  url_prefix="/api/ponto")
    app.register_blueprint(gestor_bp, url_prefix="/api/gestor")

    # ── Rota de health-check ───────────────────────────────────────────────
    @app.route("/api/health")
    def health_check():
        return jsonify({"status": "ok", "versao": "1.0.0"}), 200

    # ── Criação das tabelas ────────────────────────────────────────────────
    with app.app_context():
        db.create_all()
        app.logger.info("Banco de dados inicializado.")

    return app
