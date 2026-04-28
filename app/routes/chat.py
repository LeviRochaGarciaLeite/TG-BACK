"""
Rotas de chat — /api/chat

Endpoints:
  GET  /contatos               — Lista usuários com quem posso conversar
  GET  /mensagens/<user_id>    — Histórico de mensagens com um usuário
  POST /enviar                 — Envia uma mensagem
  POST /marcar-lidas/<user_id> — Marca mensagens como lidas
  GET  /nao-lidas-count        — Contagem de mensagens não lidas
"""

import logging
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from ..models import db, Usuario, Equipe, equipe_membros, MensagemChat

chat_bp = Blueprint("chat", __name__)
logger = logging.getLogger(__name__)


def _get_contatos_ids(usuario_id: int, perfil: str, empresa_id: int) -> list:
    """Retorna IDs de todos os usuários da empresa com quem este usuário pode conversar (todos menos ele mesmo)."""
    todos = Usuario.query.filter(
        Usuario.empresa_id == empresa_id,
        Usuario.ativo == True,
        Usuario.id != usuario_id,
    ).all()
    return [u.id for u in todos]


@chat_bp.route("/contatos", methods=["GET"])
@jwt_required()
def listar_contatos():
    claims = get_jwt()
    usuario_id = int(get_jwt_identity())
    perfil = claims.get("perfil")
    empresa_id = claims["empresa_id"]

    ids_contatos = _get_contatos_ids(usuario_id, perfil, empresa_id)

    contatos = Usuario.query.filter(
        Usuario.id.in_(ids_contatos),
        Usuario.ativo == True,
    ).all() if ids_contatos else []

    resultado = []
    for c in contatos:
        nao_lidas = MensagemChat.query.filter_by(
            remetente_id=c.id,
            destinatario_id=usuario_id,
            lida=False,
        ).count()

        ultima = (
            MensagemChat.query
            .filter(
                db.or_(
                    db.and_(MensagemChat.remetente_id == usuario_id, MensagemChat.destinatario_id == c.id),
                    db.and_(MensagemChat.remetente_id == c.id, MensagemChat.destinatario_id == usuario_id),
                )
            )
            .order_by(MensagemChat.criada_em.desc())
            .first()
        )

        resultado.append({
            **c.to_dict(),
            "nao_lidas": nao_lidas,
            "ultima_mensagem": ultima.to_dict() if ultima else None,
        })

    resultado.sort(key=lambda x: (
        0 if x["nao_lidas"] > 0 else 1,
        -(hash(x["ultima_mensagem"]["criada_em"]) if x["ultima_mensagem"] else 0),
    ))

    return jsonify({"contatos": resultado}), 200


@chat_bp.route("/mensagens/<int:outro_id>", methods=["GET"])
@jwt_required()
def listar_mensagens(outro_id):
    usuario_id = int(get_jwt_identity())

    mensagens = (
        MensagemChat.query
        .filter(
            db.or_(
                db.and_(MensagemChat.remetente_id == usuario_id, MensagemChat.destinatario_id == outro_id),
                db.and_(MensagemChat.remetente_id == outro_id, MensagemChat.destinatario_id == usuario_id),
            )
        )
        .order_by(MensagemChat.criada_em.asc())
        .limit(100)
        .all()
    )

    return jsonify({"mensagens": [m.to_dict() for m in mensagens]}), 200


@chat_bp.route("/enviar", methods=["POST"])
@jwt_required()
def enviar_mensagem():
    claims = get_jwt()
    usuario_id = int(get_jwt_identity())
    perfil = claims.get("perfil")
    empresa_id = claims["empresa_id"]

    dados = request.get_json(silent=True)
    if not dados:
        return jsonify({"erro": "Requisição inválida."}), 400

    destinatario_id = dados.get("destinatario_id")
    texto = (dados.get("texto") or "").strip()

    if not destinatario_id or not texto:
        return jsonify({"erro": "destinatario_id e texto são obrigatórios."}), 400

    if len(texto) > 1000:
        return jsonify({"erro": "Mensagem muito longa (máx 1000 caracteres)."}), 400

    ids_permitidos = _get_contatos_ids(usuario_id, perfil, empresa_id)
    if destinatario_id not in ids_permitidos:
        return jsonify({"erro": "Você não tem permissão para enviar mensagem a este usuário."}), 403

    msg = MensagemChat(
        remetente_id=usuario_id,
        destinatario_id=destinatario_id,
        texto=texto,
    )
    db.session.add(msg)
    db.session.commit()

    return jsonify({"mensagem": msg.to_dict()}), 201


@chat_bp.route("/marcar-lidas/<int:outro_id>", methods=["POST"])
@jwt_required()
def marcar_lidas(outro_id):
    usuario_id = int(get_jwt_identity())

    MensagemChat.query.filter_by(
        remetente_id=outro_id,
        destinatario_id=usuario_id,
        lida=False,
    ).update({"lida": True})

    db.session.commit()
    return jsonify({"ok": True}), 200


@chat_bp.route("/nao-lidas-count", methods=["GET"])
@jwt_required()
def nao_lidas_count():
    usuario_id = int(get_jwt_identity())
    count = MensagemChat.query.filter_by(destinatario_id=usuario_id, lida=False).count()
    return jsonify({"count": count}), 200
