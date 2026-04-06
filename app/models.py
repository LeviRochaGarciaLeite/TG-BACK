"""
Modelos de banco de dados do Nexus.
Utiliza SQLAlchemy com boas práticas: timestamps explícitos, índices e
métodos de serialização para não vazar dados sensíveis nas respostas.
"""

from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone

db = SQLAlchemy()

# ── Utilitário de tempo ────────────────────────────────────────────────────

def now_utc() -> datetime:
    """Retorna o instante atual em UTC de forma explícita (sem deprecation)."""
    return datetime.now(timezone.utc)


# ── Modelos ────────────────────────────────────────────────────────────────

class Empresa(db.Model):
    __tablename__ = "empresas"

    id            = db.Column(db.Integer, primary_key=True)
    nome_fantasia = db.Column(db.String(100), nullable=False)
    cnpj          = db.Column(db.String(14), unique=True, nullable=False, index=True)
    criado_em     = db.Column(db.DateTime(timezone=True), default=now_utc, nullable=False)

    usuarios = db.relationship("Usuario", back_populates="empresa", lazy="select")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "nome_fantasia": self.nome_fantasia,
            "cnpj": self.cnpj,
        }

    def __repr__(self) -> str:
        return f"<Empresa {self.nome_fantasia}>"


class Usuario(db.Model):
    __tablename__ = "usuarios"

    id          = db.Column(db.Integer, primary_key=True)
    empresa_id  = db.Column(db.Integer, db.ForeignKey("empresas.id"), nullable=False, index=True)
    nome        = db.Column(db.String(100), nullable=False)
    cpf         = db.Column(db.String(11), unique=True, nullable=False, index=True)
    senha_hash  = db.Column(db.String(255), nullable=False)
    perfil      = db.Column(db.String(20), nullable=False, default="colaborador")
    ativo       = db.Column(db.Boolean, nullable=False, default=True)
    criado_em   = db.Column(db.DateTime(timezone=True), default=now_utc, nullable=False)
    foto_perfil = db.Column(db.Text, nullable=True)

    empresa   = db.relationship("Empresa", back_populates="usuarios")
    registros = db.relationship("RegistroPonto", back_populates="usuario", lazy="select")

    # Perfis válidos — usados como referência nas rotas
    PERFIS_VALIDOS   = ("colaborador", "gestor", "admin")
    PERFIS_GESTORES  = ("gestor", "admin")

    def to_dict(self) -> dict:
        """Serialização segura — nunca inclui senha_hash."""
        return {
            "id":          self.id,
            "nome":        self.nome,
            "cpf":         self.cpf,
            "perfil":      self.perfil,
            "ativo":       self.ativo,
            "empresa_id":  self.empresa_id,
            "foto_perfil": self.foto_perfil,
        }

    def __repr__(self) -> str:
        return f"<Usuario {self.cpf} | {self.perfil}>"


class RegistroPonto(db.Model):
    __tablename__ = "registros_ponto"

    id             = db.Column(db.Integer, primary_key=True)
    usuario_id     = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False, index=True)
    tipo_registro  = db.Column(db.String(20), nullable=False)
    timestamp      = db.Column(db.DateTime(timezone=True), default=now_utc, nullable=False, index=True)
    ip_origem      = db.Column(db.String(45))
    dispositivo    = db.Column(db.String(255))
    status         = db.Column(db.String(20), nullable=False, default="valido")
    observacao     = db.Column(db.String(500))  # Campo livre para motivos de ajuste

    usuario = db.relationship("Usuario", back_populates="registros")

    # Tipos válidos de registro
    TIPOS_VALIDOS   = ("entrada", "pausa_inicio", "pausa_fim", "saida")
    # Status possíveis
    STATUS_VALIDOS  = ("valido", "pendente_ajuste", "ajustado", "recusado")

    def to_dict(self) -> dict:
        return {
            "id":         self.id,
            "tipo":       self.tipo_registro,
            "horario":    self.timestamp.isoformat(),
            "status":     self.status,
            "ip_origem":  self.ip_origem,
            "observacao": self.observacao,
        }

    def __repr__(self) -> str:
        return f"<RegistroPonto {self.tipo_registro} @ {self.timestamp}>"