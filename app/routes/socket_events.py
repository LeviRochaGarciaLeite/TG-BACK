"""
Eventos WebSocket do Nexus Chat — Flask-SocketIO

Fluxo:
  1. Cliente conecta e emite  'autenticar'  com { token }
  2. Servidor valida JWT e junta o cliente numa room pessoal  user_<id>
  3. Para enviar mensagem, cliente emite 'enviar_mensagem' com { destinatario_id, texto }
  4. Servidor salva no banco e faz emit() para a room do destinatário em tempo real
  5. Cliente escuta 'nova_mensagem' e atualiza a UI instantaneamente
"""

import logging
from flask import request
from flask_socketio import emit, join_room, leave_room
from flask_jwt_extended import decode_token
from jwt.exceptions import ExpiredSignatureError, DecodeError

from .. import socketio
from ..models import db, Usuario, Equipe, equipe_membros, MensagemChat

logger = logging.getLogger(__name__)

# sid → usuario_id  (mapeamento de conexão ativa)
_sid_to_user: dict[str, int] = {}


def _get_contatos_ids(usuario_id: int, perfil: str, empresa_id: int) -> list:
    todos = Usuario.query.filter(
        Usuario.empresa_id == empresa_id,
        Usuario.ativo == True,
        Usuario.id != usuario_id,
    ).all()
    return [u.id for u in todos]


# ── Conexão ───────────────────────────────────────────────────────────────

@socketio.on("connect")
def on_connect():
    logger.info(f"Socket conectado: sid={request.sid}")


@socketio.on("disconnect")
def on_disconnect():
    uid = _sid_to_user.pop(request.sid, None)
    if uid:
        leave_room(f"user_{uid}")
        logger.info(f"Socket desconectado: sid={request.sid} usuario_id={uid}")


# ── Autenticação ──────────────────────────────────────────────────────────

@socketio.on("autenticar")
def on_autenticar(data):
    """
    Recebe { token } e valida o JWT.
    Junta o socket na room pessoal do usuário: user_<id>
    """
    token = (data or {}).get("token", "")
    if not token:
        emit("erro_auth", {"msg": "Token não fornecido."})
        return

    try:
        decoded = decode_token(token)
        usuario_id = int(decoded["sub"])
        perfil     = decoded.get("perfil", "")
        empresa_id = decoded.get("empresa_id")
    except (ExpiredSignatureError, DecodeError, Exception) as e:
        emit("erro_auth", {"msg": "Token inválido ou expirado."})
        logger.warning(f"Auth WebSocket falhou: {e}")
        return

    _sid_to_user[request.sid] = usuario_id
    join_room(f"user_{usuario_id}")

    emit("autenticado", {
        "usuario_id": usuario_id,
        "perfil": perfil,
        "msg": "Conectado ao chat em tempo real.",
    })
    logger.info(f"WS autenticado: usuario_id={usuario_id} sid={request.sid}")


# ── Envio de mensagem ─────────────────────────────────────────────────────

@socketio.on("enviar_mensagem")
def on_enviar_mensagem(data):
    """
    Recebe { destinatario_id, texto }
    Salva no banco e entrega em tempo real ao destinatário.
    """
    sid = request.sid
    remetente_id = _sid_to_user.get(sid)

    if not remetente_id:
        emit("erro", {"msg": "Não autenticado. Envie 'autenticar' primeiro."})
        return

    destinatario_id = data.get("destinatario_id")
    texto = (data.get("texto") or "").strip()

    if not destinatario_id or not texto:
        emit("erro", {"msg": "destinatario_id e texto são obrigatórios."})
        return

    if len(texto) > 1000:
        emit("erro", {"msg": "Mensagem muito longa (máx 1000 caracteres)."})
        return

    remetente = db.session.get(Usuario, remetente_id)
    if not remetente:
        emit("erro", {"msg": "Remetente não encontrado."})
        return

    # Valida permissão
    ids_permitidos = _get_contatos_ids(remetente_id, remetente.perfil, remetente.empresa_id)
    if destinatario_id not in ids_permitidos:
        emit("erro", {"msg": "Sem permissão para enviar mensagem a este usuário."})
        return

    # Salva no banco
    msg = MensagemChat(
        remetente_id=remetente_id,
        destinatario_id=destinatario_id,
        texto=texto,
    )
    db.session.add(msg)
    db.session.commit()

    payload = msg.to_dict()
    payload["remetente_nome"]     = remetente.nome
    payload["remetente_foto"]     = remetente.foto_perfil
    payload["remetente_perfil"]   = remetente.perfil

    # ── Entrega em tempo real ─────────────────────────────────────────────
    # Para o destinatário
    socketio.emit("nova_mensagem", payload, to=f"user_{destinatario_id}")
    # Confirmação para o remetente (para sincronizar outras abas/dispositivos)
    emit("mensagem_enviada", payload)

    logger.info(f"Mensagem WS: {remetente_id} → {destinatario_id} ({len(texto)} chars)")


# ── Marcar mensagens como lidas ───────────────────────────────────────────

@socketio.on("marcar_lidas")
def on_marcar_lidas(data):
    """
    Recebe { outro_id }
    Marca todas as mensagens de outro_id → meu_id como lidas
    e notifica o remetente que suas mensagens foram lidas (✓✓).
    """
    meu_id   = _sid_to_user.get(request.sid)
    outro_id = (data or {}).get("outro_id")

    if not meu_id or not outro_id:
        return

    atualizadas = MensagemChat.query.filter_by(
        remetente_id=outro_id,
        destinatario_id=meu_id,
        lida=False,
    ).all()

    ids_atualizados = [m.id for m in atualizadas]

    for m in atualizadas:
        m.lida = True
    db.session.commit()

    if ids_atualizados:
        # Avisa o remetente que as mensagens foram lidas (check azul)
        socketio.emit("mensagens_lidas", {
            "ids":          ids_atualizados,
            "lidas_por_id": meu_id,
        }, to=f"user_{outro_id}")
