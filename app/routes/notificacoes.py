"""
Rotas de notificações — Nexus API
Inclui SSE (Server-Sent Events) para atualizações em tempo real.
"""

import json
import queue
import threading
import time
import logging
from datetime import datetime, timezone

from flask import Blueprint, Response, jsonify, request, stream_with_context
from flask_jwt_extended import get_jwt_identity, jwt_required, decode_token
from jwt.exceptions import PyJWTError

from ..models import Notificacao, db

notificacoes_bp = Blueprint("notificacoes", __name__)
logger = logging.getLogger(__name__)

# ── SSE: registro de clientes conectados ─────────────────────────────────────
# Dicionário { usuario_id (int): [Queue, Queue, ...] }
_sse_clients: dict[int, list[queue.Queue]] = {}
_sse_lock = threading.Lock()


def _register_client(usuario_id: int) -> queue.Queue:
    q: queue.Queue = queue.Queue(maxsize=50)
    with _sse_lock:
        _sse_clients.setdefault(usuario_id, []).append(q)
    return q


def _unregister_client(usuario_id: int, q: queue.Queue) -> None:
    with _sse_lock:
        lst = _sse_clients.get(usuario_id, [])
        if q in lst:
            lst.remove(q)
        if not lst:
            _sse_clients.pop(usuario_id, None)


def push_notification(usuario_id: int, notif_dict: dict) -> None:
    """Envia uma notificação SSE para todos os clientes do usuário."""
    payload = f"data: {json.dumps(notif_dict, ensure_ascii=False)}\n\n"
    with _sse_lock:
        queues = list(_sse_clients.get(usuario_id, []))
    for q in queues:
        try:
            q.put_nowait(payload)
        except queue.Full:
            pass


def criar_notificacao(
    usuario_id: int,
    mensagem: str,
    tipo: str = "geral",
    tela: str | None = None,
) -> Notificacao:
    """
    Cria uma notificação no banco e empurra via SSE imediatamente.
    Deve ser chamada dentro de um app context com sessão ativa.
    """
    notif = Notificacao(
        usuario_id=usuario_id,
        mensagem=mensagem,
        tipo=tipo,
        tela=tela,
    )
    db.session.add(notif)
    db.session.flush()  # gera o id sem commitar ainda

    # Push SSE imediato (não bloqueia — usa queue não-bloqueante)
    push_notification(usuario_id, notif.to_dict())

    return notif


# ── SSE endpoint ─────────────────────────────────────────────────────────────

@notificacoes_bp.route("/stream")
def stream():
    """
    GET /api/notificacoes/stream
    Aceita token via query-string (?token=...) porque EventSource do browser
    não permite headers customizados.
    """
    raw_token = request.args.get("token", "")
    if not raw_token:
        return jsonify({"erro": "Token ausente."}), 401

    try:
        from flask import current_app
        decoded = decode_token(raw_token)
        usuario_id = int(decoded["sub"])
    except Exception:
        return jsonify({"erro": "Token inválido."}), 401

    q = _register_client(usuario_id)

    @stream_with_context
    def generate():
        # Envia evento de conexão estabelecida
        yield f"data: {json.dumps({'tipo': '__connected__', 'usuario_id': usuario_id})}\n\n"

        # Envia heartbeat a cada 20s para manter a conexão viva
        last_heartbeat = time.time()
        while True:
            try:
                msg = q.get(timeout=20)
                yield msg
            except queue.Empty:
                # Heartbeat
                yield f": heartbeat {int(time.time())}\n\n"
            except GeneratorExit:
                break

        _unregister_client(usuario_id, q)

    response = Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
    return response


# ── CRUD de notificações ──────────────────────────────────────────────────────

@notificacoes_bp.route("", methods=["GET"])
@jwt_required()
def listar_notificacoes():
    usuario_id = int(get_jwt_identity())
    notifs = (
        Notificacao.query
        .filter_by(usuario_id=usuario_id)
        .order_by(Notificacao.criada_em.desc())
        .limit(80)
        .all()
    )
    return jsonify({"notificacoes": [n.to_dict() for n in notifs]}), 200


@notificacoes_bp.route("/nao-lidas-count", methods=["GET"])
@jwt_required()
def contar_nao_lidas():
    usuario_id = int(get_jwt_identity())
    count = Notificacao.query.filter_by(usuario_id=usuario_id, lida=False).count()
    return jsonify({"count": count}), 200


@notificacoes_bp.route("/<int:notif_id>/marcar-lida", methods=["PUT"])
@jwt_required()
def marcar_lida(notif_id: int):
    usuario_id = int(get_jwt_identity())
    notif = Notificacao.query.filter_by(id=notif_id, usuario_id=usuario_id).first_or_404()
    notif.lida = True
    db.session.commit()
    return jsonify({"ok": True}), 200


@notificacoes_bp.route("/marcar-todas-lidas", methods=["PUT"])
@jwt_required()
def marcar_todas_lidas():
    usuario_id = int(get_jwt_identity())
    Notificacao.query.filter_by(usuario_id=usuario_id, lida=False).update({"lida": True})
    db.session.commit()
    return jsonify({"ok": True}), 200


@notificacoes_bp.route("/<int:notif_id>", methods=["DELETE"])
@jwt_required()
def deletar_notificacao(notif_id: int):
    usuario_id = int(get_jwt_identity())
    notif = Notificacao.query.filter_by(id=notif_id, usuario_id=usuario_id).first_or_404()
    db.session.delete(notif)
    db.session.commit()
    return jsonify({"ok": True}), 200


@notificacoes_bp.route("/limpar-todas", methods=["DELETE"])
@jwt_required()
def limpar_todas():
    usuario_id = int(get_jwt_identity())
    Notificacao.query.filter_by(usuario_id=usuario_id).delete()
    db.session.commit()
    return jsonify({"ok": True}), 200
