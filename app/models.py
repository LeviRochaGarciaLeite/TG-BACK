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


# ── Tabela associativa: membros de equipe ─────────────────────────────────
equipe_membros = db.Table(
    "equipe_membros",
    db.Column("equipe_id",   db.Integer, db.ForeignKey("equipes.id"),   primary_key=True),
    db.Column("usuario_id",  db.Integer, db.ForeignKey("usuarios.id"),  primary_key=True),
)


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
    pontos_positivos = db.Column(db.Integer, nullable=False, default=0)
    pontos_negativos = db.Column(db.Integer, nullable=False, default=0)

    data_nascimento = db.Column(db.Date, nullable=True)
    cidade          = db.Column(db.String(100), nullable=True)
    celular         = db.Column(db.String(20), nullable=True)
    email           = db.Column(db.String(150), unique=True, nullable=False)

    empresa        = db.relationship("Empresa", back_populates="usuarios")
    registros      = db.relationship("RegistroPonto", back_populates="usuario", lazy="select")
    notificacoes   = db.relationship("Notificacao", back_populates="usuario", lazy="select")

    PERFIS_VALIDOS    = ("colaborador", "gestor", "supervisor", "admin")
    PERFIS_GESTORES   = ("gestor", "admin")
    PERFIL_SUPERVISOR = "supervisor"

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "nome":        self.nome,
            "cpf":         self.cpf,
            "perfil":      self.perfil,
            "ativo":       self.ativo,
            "empresa_id":  self.empresa_id,
            "foto_perfil": self.foto_perfil,
            "pontos_positivos": self.pontos_positivos,
            "pontos_negativos": self.pontos_negativos,
            "data_nascimento": self.data_nascimento.isoformat() if self.data_nascimento else None,
            "cidade":      self.cidade,
            "celular":     self.celular,
            "email":       self.email,
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
    observacao     = db.Column(db.String(500))

    usuario = db.relationship("Usuario", back_populates="registros")

    TIPOS_VALIDOS  = ("entrada", "pausa_inicio", "pausa_fim", "saida")
    STATUS_VALIDOS = ("valido", "pendente_ajuste", "ajustado", "recusado")

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


class Equipe(db.Model):
    __tablename__ = "equipes"

    id            = db.Column(db.Integer, primary_key=True)
    empresa_id    = db.Column(db.Integer, db.ForeignKey("empresas.id"), nullable=False, index=True)
    supervisor_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False, unique=True)
    nome          = db.Column(db.String(100), nullable=True)
    criado_em     = db.Column(db.DateTime(timezone=True), default=now_utc, nullable=False)
    atualizado_em = db.Column(db.DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)

    empresa    = db.relationship("Empresa", foreign_keys=[empresa_id])
    supervisor = db.relationship("Usuario", foreign_keys=[supervisor_id])
    membros    = db.relationship(
        "Usuario",
        secondary=equipe_membros,
        lazy="select",
    )

    def to_dict(self) -> dict:
        return {
            "id":            self.id,
            "empresa_id":    self.empresa_id,
            "supervisor_id": self.supervisor_id,
            "nome":          self.nome,
            "supervisor":    self.supervisor.to_dict() if self.supervisor else None,
            "membros":       [m.to_dict() for m in self.membros],
        }

    def __repr__(self) -> str:
        return f"<Equipe supervisor={self.supervisor_id}>"


# ── Notificações ───────────────────────────────────────────────────────────

class Notificacao(db.Model):
    __tablename__ = "notificacoes"

    id         = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False, index=True)
    mensagem   = db.Column(db.String(300), nullable=False)
    tipo       = db.Column(db.String(50), nullable=False)   # ex: "ponto", "equipe", "senha", "holerite"
    tela       = db.Column(db.String(50), nullable=True)    # ex: "ponto", "equipe", "holerite", "gestao"
    lida       = db.Column(db.Boolean, nullable=False, default=False)
    criada_em  = db.Column(db.DateTime(timezone=True), default=now_utc, nullable=False, index=True)

    usuario = db.relationship("Usuario", back_populates="notificacoes")

    def to_dict(self) -> dict:
        return {
            "id":        self.id,
            "mensagem":  self.mensagem,
            "tipo":      self.tipo,
            "tela":      self.tela,
            "lida":      self.lida,
            "criada_em": self.criada_em.isoformat(),
        }

    def __repr__(self) -> str:
        return f"<Notificacao usuario={self.usuario_id} tipo={self.tipo}>"


# ── Mensagens de Chat ──────────────────────────────────────────────────────

class MensagemChat(db.Model):
    __tablename__ = "mensagens_chat"

    id               = db.Column(db.Integer, primary_key=True)
    remetente_id     = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False, index=True)
    destinatario_id  = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False, index=True)
    texto            = db.Column(db.Text, nullable=False)
    lida             = db.Column(db.Boolean, nullable=False, default=False)
    criada_em        = db.Column(db.DateTime(timezone=True), default=now_utc, nullable=False, index=True)

    remetente     = db.relationship("Usuario", foreign_keys=[remetente_id])
    destinatario  = db.relationship("Usuario", foreign_keys=[destinatario_id])

    def to_dict(self) -> dict:
        return {
            "id":               self.id,
            "remetente_id":     self.remetente_id,
            "destinatario_id":  self.destinatario_id,
            "texto":            self.texto,
            "lida":             self.lida,
            "criada_em":        self.criada_em.isoformat(),
        }

    def __repr__(self) -> str:
        return f"<MensagemChat de={self.remetente_id} para={self.destinatario_id}>"
