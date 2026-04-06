"""
Configurações da aplicação Nexus.
Leia variáveis de ambiente com fallback seguro para desenvolvimento local.
Em produção, NUNCA use os valores padrão — defina as variáveis no ambiente.
"""

import os
from datetime import timedelta


class Config:
    # ── Segurança ──────────────────────────────────────────────────────────
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-prod")
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "dev-jwt-key-change-in-prod")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=8)   # Jornada máxima de trabalho
    JWT_ALGORITHM = "HS256"

    # ── Banco de dados ─────────────────────────────────────────────────────
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///nexus.db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,   # Detecta conexões mortas antes de usar
    }

    # ── CORS ───────────────────────────────────────────────────────────────
    # Em produção, restrinja para o domínio real do front-end
    CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*")


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


# Mapeamento para uso em create_app
config_map = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


# Mapeamento para uso em create_app
config_map = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}
