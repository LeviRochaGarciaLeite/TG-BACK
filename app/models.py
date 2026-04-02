from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Empresa(db.Model):
    __tablename__ = 'empresas'
    id = db.Column(db.Integer, primary_key=True)
    nome_fantasia = db.Column(db.String(100), nullable=False)
    cnpj = db.Column(db.String(14), unique=True, nullable=False)
    usuarios = db.relationship('Usuario', backref='empresa', lazy=True)

class Usuario(db.Model):
    __tablename__ = 'usuarios'
    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey('empresas.id'), nullable=False)
    nome = db.Column(db.String(100), nullable=False)
    cpf = db.Column(db.String(11), unique=True, nullable=False)
    senha_hash = db.Column(db.String(255), nullable=False)
    perfil = db.Column(db.String(20), default='colaborador') # colaborador, gestor, admin
    registros = db.relationship('RegistroPonto', backref='usuario', lazy=True)

class RegistroPonto(db.Model):
    __tablename__ = 'registros_ponto'
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    tipo_registro = db.Column(db.String(20), nullable=False) # entrada, pausa_inicio, pausa_fim, saida
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    ip_origem = db.Column(db.String(45))
    dispositivo = db.Column(db.String(255))
    status = db.Column(db.String(20), default='valido') # valido, pendente_ajuste, ajustado