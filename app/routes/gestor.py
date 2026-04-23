"""
Rotas do painel de gestão — /api/gestor
Acesso restrito a perfis: gestor, admin.
"""

import logging
import json
import queue
import threading
import time
from datetime import datetime, timezone, date
from functools import wraps

from flask import Blueprint, request, jsonify, Response, stream_with_context
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity, decode_token

from ..models import db, Usuario, RegistroPonto, Equipe
from .notificacoes import criar_notificacao

gestor_bp = Blueprint("gestor", __name__)

_gestor_sse_clients: dict[int, list[queue.Queue]] = {}
_gestor_sse_lock = threading.Lock()


def _register_gestor_stream(empresa_id: int) -> queue.Queue:
    q: queue.Queue = queue.Queue(maxsize=50)
    with _gestor_sse_lock:
        _gestor_sse_clients.setdefault(empresa_id, []).append(q)
    return q


def _unregister_gestor_stream(empresa_id: int, q: queue.Queue) -> None:
    with _gestor_sse_lock:
        clientes = _gestor_sse_clients.get(empresa_id, [])
        if q in clientes:
            clientes.remove(q)
        if not clientes:
            _gestor_sse_clients.pop(empresa_id, None)


def push_gestor_event(empresa_id: int, payload: dict) -> None:
    """Envia um evento leve para os painéis de gestão conectados."""
    msg = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
    with _gestor_sse_lock:
        queues = list(_gestor_sse_clients.get(empresa_id, []))

    for q in queues:
        try:
            q.put_nowait(msg)
        except queue.Full:
            pass


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


def _pontuacao_liquida(usuario: Usuario) -> int:
    return (usuario.pontos_positivos or 0) - (usuario.pontos_negativos or 0)


def _agora_compativel(referencia_dt: datetime | None) -> datetime:
    if referencia_dt and referencia_dt.tzinfo is None:
        return datetime.utcnow()
    return datetime.now(timezone.utc)


def _calcular_status_jornada(registros: list[RegistroPonto]) -> dict:
    if not registros:
        return {
            "estado": "idle",
            "inicio": None,
            "fim": None,
            "conectado_seg": 0,
            "pausa_seg": 0,
            "trabalhado_seg": 0,
            "registros_hoje": [],
        }

    ultimo_tipo = registros[-1].tipo_registro
    estado = {
        "entrada": "working",
        "pausa_inicio": "paused",
        "pausa_fim": "working",
        "saida": "done",
    }.get(ultimo_tipo, "idle")

    entrada_dt = None
    saida_dt = None
    pausa_inicio = None
    pausa_seg = 0

    for registro in registros:
        if registro.tipo_registro == "entrada" and entrada_dt is None:
            entrada_dt = registro.timestamp
        elif registro.tipo_registro == "pausa_inicio":
            pausa_inicio = registro.timestamp
        elif registro.tipo_registro == "pausa_fim" and pausa_inicio:
            pausa_seg += int((registro.timestamp - pausa_inicio).total_seconds())
            pausa_inicio = None
        elif registro.tipo_registro == "saida":
            saida_dt = registro.timestamp

    referencia_dt = entrada_dt or registros[0].timestamp
    agora = _agora_compativel(referencia_dt)
    fim_dt = saida_dt or agora

    if pausa_inicio:
        pausa_seg += int((fim_dt - pausa_inicio).total_seconds())

    conectado_seg = int((fim_dt - entrada_dt).total_seconds()) if entrada_dt else 0
    trabalhado_seg = max(0, conectado_seg - pausa_seg)

    return {
        "estado": estado,
        "inicio": entrada_dt.isoformat() if entrada_dt else None,
        "fim": saida_dt.isoformat() if saida_dt else None,
        "conectado_seg": conectado_seg,
        "pausa_seg": pausa_seg,
        "trabalhado_seg": trabalhado_seg,
        "registros_hoje": [r.to_dict() for r in registros],
    }


def _usuario_com_status(usuario: Usuario, status_map: dict[int, dict]) -> dict:
    dados = usuario.to_dict()
    status = status_map.get(usuario.id, _calcular_status_jornada([]))
    dados.update({
        "status_jornada": status["estado"],
        "inicio": status["inicio"],
        "fim": status["fim"],
        "conectado_seg": status["conectado_seg"],
        "pausa_seg": status["pausa_seg"],
        "trabalhado_seg": status["trabalhado_seg"],
        "pontos_total": _pontuacao_liquida(usuario),
    })
    return dados


def _resumo_status(usuarios: list[Usuario], status_map: dict[int, dict]) -> dict:
    resumo = {
        "trabalhando": 0,
        "pausados": 0,
        "encerrados": 0,
        "nao_iniciaram": 0,
    }

    for usuario in usuarios:
        estado = status_map.get(usuario.id, {}).get("estado", "idle")
        if estado == "working":
            resumo["trabalhando"] += 1
        elif estado == "paused":
            resumo["pausados"] += 1
        elif estado == "done":
            resumo["encerrados"] += 1
        else:
            resumo["nao_iniciaram"] += 1

    return resumo


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


# ── Stream em tempo real para o painel de equipes ─────────────────────────

@gestor_bp.route("/equipes/stream", methods=["GET"])
def stream_equipes():
    """
    SSE leve para avisar o gestor quando algum ponto mudar.
    O payload não carrega a equipe inteira; o frontend busca /equipes/status.
    """
    raw_token = request.args.get("token", "")
    if not raw_token:
        return jsonify({"erro": "Token ausente."}), 401

    try:
        decoded = decode_token(raw_token)
        perfil = decoded.get("perfil")
        empresa_id = int(decoded["empresa_id"])
    except Exception:
        return jsonify({"erro": "Token inválido."}), 401

    if perfil not in Usuario.PERFIS_GESTORES:
        return jsonify({"erro": "Acesso negado. Restrito a gestores."}), 403

    q = _register_gestor_stream(empresa_id)

    @stream_with_context
    def generate():
        yield f"data: {json.dumps({'tipo': '__connected__', 'empresa_id': empresa_id})}\n\n"

        while True:
            try:
                msg = q.get(timeout=20)
                yield msg
            except queue.Empty:
                yield f": heartbeat {int(time.time())}\n\n"
            except GeneratorExit:
                break

        _unregister_gestor_stream(empresa_id, q)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ── Status consolidado das equipes ────────────────────────────────────────

@gestor_bp.route("/equipes/status", methods=["GET"])
@jwt_required()
@gestor_required
def status_equipes():
    """
    Retorna uma visão consolidada para o painel do gestor.
    Evita uma requisição de histórico por colaborador no frontend.
    """
    claims = get_jwt()
    empresa_id = claims["empresa_id"]

    usuarios = (
        Usuario.query
        .filter(
            Usuario.empresa_id == empresa_id,
            Usuario.ativo == True,
            Usuario.perfil.notin_(["gestor", "admin"]),
        )
        .all()
    )

    usuario_ids = [usuario.id for usuario in usuarios]
    hoje_inicio = datetime.combine(date.today(), datetime.min.time()).replace(tzinfo=timezone.utc)

    registros = []
    if usuario_ids:
        registros = (
            RegistroPonto.query
            .filter(
                RegistroPonto.usuario_id.in_(usuario_ids),
                RegistroPonto.timestamp >= hoje_inicio,
                RegistroPonto.status.in_(["valido", "ajustado"]),
            )
            .order_by(RegistroPonto.usuario_id.asc(), RegistroPonto.timestamp.asc())
            .all()
        )

    registros_por_usuario = {usuario_id: [] for usuario_id in usuario_ids}
    for registro in registros:
        registros_por_usuario.setdefault(registro.usuario_id, []).append(registro)

    status_map = {
        usuario_id: _calcular_status_jornada(registros_usuario)
        for usuario_id, registros_usuario in registros_por_usuario.items()
    }

    equipes = (
        Equipe.query
        .filter_by(empresa_id=empresa_id)
        .all()
    )

    ids_em_equipes = set()
    equipes_payload = []

    for equipe in equipes:
        integrantes = []
        if equipe.supervisor:
            integrantes.append(equipe.supervisor)
            ids_em_equipes.add(equipe.supervisor.id)

        membros_ativos = [membro for membro in equipe.membros if membro.ativo]
        integrantes.extend(membros_ativos)
        ids_em_equipes.update(membro.id for membro in membros_ativos)

        equipes_payload.append({
            "id": equipe.id,
            "nome": equipe.nome,
            "supervisor_id": equipe.supervisor_id,
            "supervisor": _usuario_com_status(equipe.supervisor, status_map) if equipe.supervisor else None,
            "membros": [_usuario_com_status(membro, status_map) for membro in membros_ativos],
            "pontos_total": sum(_pontuacao_liquida(usuario) for usuario in integrantes),
        })

    sem_equipe = [
        usuario
        for usuario in usuarios
        if usuario.id not in ids_em_equipes
    ]

    if sem_equipe:
        equipes_payload.append({
            "id": "sem-equipe",
            "nome": "Sem equipe",
            "supervisor_id": None,
            "supervisor": None,
            "membros": [_usuario_com_status(usuario, status_map) for usuario in sem_equipe],
            "pontos_total": sum(_pontuacao_liquida(usuario) for usuario in sem_equipe),
        })

    colaboradores_payload = [
        _usuario_com_status(usuario, status_map)
        for usuario in usuarios
    ]

    return jsonify({
        "empresa_id": empresa_id,
        "atualizado_em": datetime.now(timezone.utc).isoformat(),
        "resumo": _resumo_status(usuarios, status_map),
        "total_colaboradores": len(usuarios),
        "colaboradores": colaboradores_payload,
        "equipes": equipes_payload,
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
