"""
Rotas do painel de gestão — /api/gestor
Acesso restrito a perfis: gestor, admin.
"""

import logging
from datetime import datetime, timezone
from functools import wraps

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from ..models import db, Usuario, RegistroPonto

gestor_bp = Blueprint("gestor", __name__)
logger = logging.getLogger(__name__)


# ── Decorator de autorização ───────────────────────────────────────────────

def gestor_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        claims = get_jwt()
        if claims.get("perfil") not in Usuario.PERFIS_GESTORES:
            return jsonify({"erro": "Acesso negado. Restrito a gestores."}), 403
        return fn(*args, **kwargs)
    return wrapper


# ── Helper ─────────────────────────────────────────────────────────────────

def _get_colaborador_da_empresa(id_colaborador: int, empresa_id: int):
    return Usuario.query.filter_by(
        id=id_colaborador,
        empresa_id=empresa_id,
    ).first()


# ── Listar equipe ──────────────────────────────────────────────────────────

@gestor_bp.route("/equipe", methods=["GET"])
@jwt_required()
@gestor_required
def listar_equipe():
    claims = get_jwt()
    empresa_id = claims["empresa_id"]

    equipe = Usuario.query.filter_by(empresa_id=empresa_id, ativo=True).all()

    return jsonify({
        "empresa_id": empresa_id,
        "total_membros": len(equipe),
        "equipe": [m.to_dict() for m in equipe],
    }), 200


# ── Histórico ──────────────────────────────────────────────────────────────

@gestor_bp.route("/colaborador/<int:id_colaborador>/historico", methods=["GET"])
@jwt_required()
@gestor_required
def historico_colaborador(id_colaborador: int):
    claims = get_jwt()
    empresa_id = claims["empresa_id"]

    colaborador = _get_colaborador_da_empresa(id_colaborador, empresa_id)
    if not colaborador:
        return jsonify({"erro": "Colaborador não encontrado."}), 404

    registros = RegistroPonto.query.filter_by(
        usuario_id=id_colaborador
    ).order_by(RegistroPonto.timestamp.desc()).all()

    return jsonify({
        "colaborador": colaborador.to_dict(),
        "historico": [r.to_dict() for r in registros],
    }), 200


# ── Ajuste manual ──────────────────────────────────────────────────────────

@gestor_bp.route("/colaborador/<int:id_colaborador>/ajuste", methods=["POST"])
@jwt_required()
@gestor_required
def ajustar_ponto(id_colaborador: int):
    claims = get_jwt()
    empresa_id = claims["empresa_id"]

    colaborador = _get_colaborador_da_empresa(id_colaborador, empresa_id)
    if not colaborador:
        return jsonify({"erro": "Colaborador não encontrado."}), 404

    dados = request.get_json()

    registro = RegistroPonto(
        usuario_id=id_colaborador,
        tipo_registro=dados.get("tipo_registro"),
        timestamp=datetime.fromisoformat(dados.get("horario")),
        status="ajustado"
    )

    db.session.add(registro)
    db.session.commit()

    return jsonify({"mensagem": "Ponto ajustado com sucesso"}), 201


# ── Editar perfil do colaborador ───────────────────────────────────────────

@gestor_bp.route("/colaborador/<int:id_colaborador>/perfil", methods=["PUT"])
@jwt_required()
@gestor_required
def gestor_editar_perfil(id_colaborador: int):
    claims = get_jwt()
    empresa_id = claims["empresa_id"]

    colaborador = _get_colaborador_da_empresa(id_colaborador, empresa_id)
    if not colaborador:
        return jsonify({"erro": "Colaborador não encontrado."}), 404

    dados = request.get_json()

    if "nome" in dados:
        colaborador.nome = dados["nome"]

    if "foto_perfil" in dados:
        colaborador.foto_perfil = dados["foto_perfil"]

    db.session.commit()

    return jsonify({
        "mensagem": "Perfil atualizado com sucesso",
        "nome": colaborador.nome,
        "foto_perfil": colaborador.foto_perfil
    }), 200