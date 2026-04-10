"""
ADICIONE ESTE TRECHO AO FINAL DO ARQUIVO: app/models.py
(logo após a classe RegistroPonto)
"""

class Equipe(db.Model):
    __tablename__ = "equipes"

    id               = db.Column(db.Integer, primary_key=True)
    empresa_id       = db.Column(db.Integer, db.ForeignKey("empresas.id"), nullable=False, index=True)
    supervisor_id    = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False, unique=True)
    colaborador1_id  = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    colaborador2_id  = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    criado_em        = db.Column(db.DateTime(timezone=True), default=now_utc, nullable=False)

    empresa      = db.relationship("Empresa", foreign_keys=[empresa_id])
    supervisor   = db.relationship("Usuario", foreign_keys=[supervisor_id])
    colaborador1 = db.relationship("Usuario", foreign_keys=[colaborador1_id])
    colaborador2 = db.relationship("Usuario", foreign_keys=[colaborador2_id])

    def to_dict(self) -> dict:
        return {
            "id":              self.id,
            "empresa_id":      self.empresa_id,
            "supervisor_id":   self.supervisor_id,
            "colaborador1_id": self.colaborador1_id,
            "colaborador2_id": self.colaborador2_id,
        }

    def __repr__(self) -> str:
        return f"<Equipe supervisor={self.supervisor_id}>"
