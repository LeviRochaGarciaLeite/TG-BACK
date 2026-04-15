"""
Rotas de notificações — /api/notificacoes

Endpoints:
  GET  /                   — Lista todas as notificações do usuário logado
  GET  /nao-lidas-count    — Retorna a contagem de notificações não lidas
  PUT  /<id>/marcar-lida   — Marca uma notificação como lida
  PUT  /marcar-todas-lidas — Marca todas as notificações do usuário como lidas
  DELETE /<id>             — Remove uma notificação

Helper interno:
  criar_notificacao(usuario_id, mensagem, tipo, tela) — cria uma notificação (sem commit)
"""

import logging
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt

from ..models import db, Notificacao, Usuario

notificacoes_bp = Blueprint("notificacoes", __name__)
logger = logging.getLogger(__name__)


# ── Helper reutilizável por outros módulos ────────────────────────────────────

def criar_notificacao(usuario_id: int, mensagem: str, tipo: str, tela: str | None = None) -> Notificacao:
    """
    Cria e adiciona uma Notificacao à sessão (sem commit).
    Quem chamar esta função deve fazer db.session.commit() depois.
    """
    notif = Notificacao(
        usuario_id=usuario_id,
        mensagem=mensagem,
        tipo=tipo,
        tela=tela,
    )
    db.session.add(notif)
    logger.info(f"Notificação criada para usuario_id={usuario_id} tipo={tipo}")
    return notif


# ── GET /api/notificacoes ─────────────────────────────────────────────────────

@notificacoes_bp.route("", methods=["GET"])
@jwt_required()
def listar_notificacoes():
    """
    Retorna todas as notificações do usuário logado, ordenadas da mais recente para a mais antiga.
    Query params opcionais:
      ?apenas_nao_lidas=true  — filtra somente as não lidas
      ?limite=50              — limita o número de resultados (padrão: 50)
    """
    usuario_id = int(get_jwt_identity())

    apenas_nao_lidas = request.args.get("apenas_nao_lidas", "false").lower() == "true"
    limite = request.args.get("limite", 50, type=int)
    limite = max(1, min(limite, 200))  # entre 1 e 200

    query = Notificacao.query.filter_by(usuario_id=usuario_id)

    if apenas_nao_lidas:
        query = query.filter_by(lida=False)

    notificacoes = (
        query
        .order_by(Notificacao.criada_em.desc())
        .limit(limite)
        .all()
    )

    total_nao_lidas = Notificacao.query.filter_by(
        usuario_id=usuario_id, lida=False
    ).count()

    return jsonify({
        "notificacoes": [n.to_dict() for n in notificacoes],
        "total":        len(notificacoes),
        "nao_lidas":    total_nao_lidas,
    }), 200


# ── GET /api/notificacoes/nao-lidas-count ─────────────────────────────────────

@notificacoes_bp.route("/nao-lidas-count", methods=["GET"])
@jwt_required()
def count_nao_lidas():
    """Retorna apenas a contagem de notificações não lidas — leve, para polling."""
    usuario_id = int(get_jwt_identity())

    count = Notificacao.query.filter_by(usuario_id=usuario_id, lida=False).count()

    return jsonify({"count": count}), 200


# ── PUT /api/notificacoes/<id>/marcar-lida ────────────────────────────────────

@notificacoes_bp.route("/<int:notif_id>/marcar-lida", methods=["PUT"])
@jwt_required()
def marcar_lida(notif_id: int):
    """Marca uma notificação específica como lida."""
    usuario_id = int(get_jwt_identity())

    notif = Notificacao.query.filter_by(id=notif_id, usuario_id=usuario_id).first()
    if not notif:
        return jsonify({"erro": "Notificação não encontrada."}), 404

    notif.lida = True
    db.session.commit()

    return jsonify({"mensagem": "Notificação marcada como lida.", "notificacao": notif.to_dict()}), 200


# ── PUT /api/notificacoes/marcar-todas-lidas ──────────────────────────────────

@notificacoes_bp.route("/marcar-todas-lidas", methods=["PUT"])
@jwt_required()
def marcar_todas_lidas():
    """Marca todas as notificações do usuário como lidas de uma vez."""
    usuario_id = int(get_jwt_identity())

    atualizadas = (
        Notificacao.query
        .filter_by(usuario_id=usuario_id, lida=False)
        .update({"lida": True})
    )
    db.session.commit()

    logger.info(f"Todas as notificações marcadas como lidas: usuario_id={usuario_id} ({atualizadas} registros)")

    return jsonify({
        "mensagem": f"{atualizadas} notificação(ões) marcada(s) como lida(s).",
        "atualizadas": atualizadas,
    }), 200


# ── DELETE /api/notificacoes/<id> ─────────────────────────────────────────────

@notificacoes_bp.route("/<int:notif_id>", methods=["DELETE"])
@jwt_required()
def deletar_notificacao(notif_id: int):
    """Remove uma notificação do usuário logado."""
    usuario_id = int(get_jwt_identity())

    notif = Notificacao.query.filter_by(id=notif_id, usuario_id=usuario_id).first()
    if not notif:
        return jsonify({"erro": "Notificação não encontrada."}), 404

    db.session.delete(notif)
    db.session.commit()

    return jsonify({"mensagem": "Notificação removida."}), 200
