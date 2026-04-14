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
from .notificacoes import criar_notificacao

gestor_bp = Blueprint("gestor", __name__)


def _notificar_gestores(empresa_id: int, mensagem: str, tipo: str, tela=None):
    """Envia notificação para todos os gestores/admins da empresa."""
    gestores = Usuario.query.filter(
        Usuario.empresa_id == empresa_id,
        Usuario.perfil.in_(["gestor", "admin"]),
        Usuario.ativo == True,
    ).all()
    for gestor in gestores:
        criar_notificacao(gestor.id, mensagem, tipo=tipo, tela=tela)
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
    gestor_id = int(get_jwt_identity())
    empresa_id = claims["empresa_id"]

    colaborador = _get_colaborador_da_empresa(id_colaborador, empresa_id)
    if not colaborador:
        return jsonify({"erro": "Colaborador não encontrado."}), 404

    dados = request.get_json()
    tipo_reg = dados.get("tipo_registro", "registro")

    registro = RegistroPonto(
        usuario_id=id_colaborador,
        tipo_registro=tipo_reg,
        timestamp=datetime.fromisoformat(dados.get("horario")),
        status="ajustado"
    )
    db.session.add(registro)

    gestor = db.session.get(Usuario, gestor_id)
    nome_gestor = gestor.nome if gestor else "Seu gestor"

    criar_notificacao(
        id_colaborador,
        f"\U0001f550 Seu ponto ({tipo_reg}) foi ajustado por {nome_gestor}.",
        tipo="ponto",
        tela="ponto",
    )
    _notificar_gestores(
        empresa_id,
        f"\U0001f550 Ponto de {colaborador.nome} ({tipo_reg}) foi ajustado por {nome_gestor}.",
        tipo="ponto",
        tela=None,
    )

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
    gestor_id = int(get_jwt_identity())
    gestor = db.session.get(Usuario, gestor_id)
    nome_gestor = gestor.nome if gestor else "Seu gestor"

    if "nome" in dados:
        colaborador.nome = dados["nome"]
    if "foto_perfil" in dados:
        colaborador.foto_perfil = dados["foto_perfil"]
    if "cidade" in dados:
        colaborador.cidade = dados["cidade"]
    if "celular" in dados:
        colaborador.celular = dados["celular"]
    if "perfil" in dados:
        novo_perfil = dados["perfil"]
        if novo_perfil in Usuario.PERFIS_VALIDOS and novo_perfil != colaborador.perfil:
            perfil_anterior = colaborador.perfil
            colaborador.perfil = novo_perfil

            # Notifica o colaborador sobre a mudança de cargo
            criar_notificacao(
                colaborador.id,
                f"\U0001f3f7\ufe0f Seu cargo foi alterado de '{perfil_anterior}' para '{novo_perfil}' por {nome_gestor}.",
                tipo="perfil",
                tela="perfil",
            )

            # Notifica os gestores/admins da empresa
            _notificar_gestores(
                empresa_id,
                f"\U0001f3f7\ufe0f O cargo de {colaborador.nome} foi alterado de '{perfil_anterior}' para '{novo_perfil}' por {nome_gestor}.",
                tipo="perfil",
                tela=None,
            )

    db.session.commit()

    return jsonify({
        "mensagem": "Perfil atualizado com sucesso",
        "nome": colaborador.nome,
        "cidade": colaborador.cidade,
        "celular": colaborador.celular,
        "perfil": colaborador.perfil
    }), 200