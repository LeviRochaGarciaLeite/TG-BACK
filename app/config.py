import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'mudar-para-uma-chave-segura-em-producao'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///nexus.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY') or 'super-secret-key-mudar-em-prod'
