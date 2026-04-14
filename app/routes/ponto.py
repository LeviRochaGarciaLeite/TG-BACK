"""
Rotas de ponto eletrônico — /api/ponto
Endpoints:
  POST /registrar         — Bate o ponto (entrada, pausa_inicio, pausa_fim, saida)
  GET  /historico         — Histórico do usuário logado (com paginação)
  GET  /status-atual      — Estado atual da jornada (idle | working | paused | done)
  POST /solicitar-ajuste  — Solicita ajuste manual para aprovação do gestor
"""

import logging
from datetime import datetime, timezone, date
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from ..models import db, RegistroPonto, Usuario, Equipe
from .notificacoes import criar_notificacao

ponto_bp = Blueprint("ponto", __name__)
logger = logging.getLogger(__name__)


# ── Helper ─────────────────────────────────────────────────────────────────

def _registros_de_hoje(usuario_id: int):
    hoje_inicio = datetime.combine(date.today(), datetime.min.time()).replace(tzinfo=timezone.utc)
    return (
        RegistroPonto.query
        .filter(
            RegistroPonto.usuario_id == usuario_id,
            RegistroPonto.timestamp >= hoje_inicio,
            RegistroPonto.status.in_(["valido", "ajustado"]),
        )
        .order_by(RegistroPonto.timestamp.asc())
        .all()
    )


def _estado_jornada(registros: list) -> str:
    if not registros:
        return "idle"
    ultimo_tipo = registros[-1].tipo_registro
    return {
        "entrada":      "working",
        "pausa_inicio": "paused",
        "pausa_fim":    "working",
        "saida":        "done",
    }.get(ultimo_tipo, "idle")


def _transicao_valida(estado_atual: str, novo_tipo: str) -> bool:
    transicoes_permitidas = {
        "idle":    ["entrada"],
        "working": ["pausa_inicio", "saida"],
        "paused":  ["pausa_fim"],
        "done":    [],
    }
    return novo_tipo in transicoes_permitidas.get(estado_atual, [])


def _notificar_gestores_do_colaborador(colaborador: Usuario, mensagem: str, tela: str):
    """
    Busca o(s) gestor(es) da empresa do colaborador e cria notificação para cada um.
    Também notifica o supervisor da equipe do colaborador, se houver.
    """
    empresa_id = colaborador.empresa_id

    # Notifica todos os gestores da empresa
    gestores = Usuario.query.filter(
        Usuario.empresa_id == empresa_id,
        Usuario.perfil.in_(["gestor", "admin"]),
        Usuario.ativo == True,
    ).all()

    for gestor in gestores:
        criar_notificacao(gestor.id, mensagem, tipo="ponto", tela=tela)

    # Notifica o supervisor da equipe do colaborador (se tiver)
    equipe = (
        Equipe.query
        .filter(Equipe.empresa_id == empresa_id)
        .all()
    )
    for eq in equipe:
        if any(m.id == colaborador.id for m in eq.membros):
            if eq.supervisor_id not in [g.id for g in gestores]:
                criar_notificacao(eq.supervisor_id, mensagem, tipo="ponto", tela=tela)
            break


# ── Registrar ponto ────────────────────────────────────────────────────────

@ponto_bp.route("/registrar", methods=["POST"])
@jwt_required()
def registrar_ponto():
    usuario_id = int(get_jwt_identity())
    dados = request.get_json(silent=True)

    if not dados or not dados.get("tipo_registro"):
        return jsonify({"erro": "O campo tipo_registro é obrigatório."}), 400

    tipo = dados["tipo_registro"]

    if tipo not in RegistroPonto.TIPOS_VALIDOS:
        return jsonify({
            "erro": f"Tipo inválido. Use: {', '.join(RegistroPonto.TIPOS_VALIDOS)}."
        }), 400

    registros_hoje = _registros_de_hoje(usuario_id)
    estado_atual   = _estado_jornada(registros_hoje)

    if not _transicao_valida(estado_atual, tipo):
        return jsonify({
            "erro": f"Ação '{tipo}' não permitida no estado atual '{estado_atual}'."
        }), 409

    novo = RegistroPonto(
        usuario_id    = usuario_id,
        tipo_registro = tipo,
        ip_origem     = request.remote_addr,
        dispositivo   = request.headers.get("User-Agent", "")[:255],
        status        = "valido",
    )
    db.session.add(novo)

    # ── Notificações de ponto ──────────────────────────────────────────────
    colaborador = db.session.get(Usuario, usuario_id)
    if colaborador and tipo in ("entrada", "saida"):
        if tipo == "entrada":
            msg = f"🟢 {colaborador.nome} começou a trabalhar."
        else:
            msg = f"🔴 {colaborador.nome} encerrou o ponto."
        _notificar_gestores_do_colaborador(colaborador, msg, tela="gestao")

    db.session.commit()

    logger.info(f"Ponto registrado: usuario_id={usuario_id} tipo={tipo}")

    return jsonify({
        "mensagem":         f"Ponto '{tipo}' registrado com sucesso.",
        "horario_servidor": novo.timestamp.isoformat(),
        "novo_estado":      _estado_jornada(_registros_de_hoje(usuario_id)),
    }), 201


# ── Histórico ──────────────────────────────────────────────────────────────

@ponto_bp.route("/historico", methods=["GET"])
@jwt_required()
def historico_ponto():
    usuario_id = get_jwt_identity()

    pagina     = max(1, request.args.get("pagina", 1, type=int))
    por_pagina = min(100, request.args.get("por_pagina", 50, type=int))

    paginado = (
        RegistroPonto.query
        .filter_by(usuario_id=usuario_id)
        .order_by(RegistroPonto.timestamp.desc())
        .paginate(page=pagina, per_page=por_pagina, error_out=False)
    )

    return jsonify({
        "pagina":          paginado.page,
        "por_pagina":      paginado.per_page,
        "total_registros": paginado.total,
        "total_paginas":   paginado.pages,
        "historico":       [r.to_dict() for r in paginado.items],
    }), 200


# ── Status atual ───────────────────────────────────────────────────────────

@ponto_bp.route("/status-atual", methods=["GET"])
@jwt_required()
def status_atual():
    usuario_id     = get_jwt_identity()
    registros_hoje = _registros_de_hoje(usuario_id)
    estado         = _estado_jornada(registros_hoje)

    if not registros_hoje:
        return jsonify({"estado": "idle"}), 200

    agora         = datetime.now(timezone.utc)
    inicio        = registros_hoje[0].timestamp
    conectado_seg = int((agora - inicio).total_seconds())

    pausa_seg    = 0
    inicio_pausa = None
    for reg in registros_hoje:
        if reg.tipo_registro == "pausa_inicio":
            inicio_pausa = reg.timestamp
        elif reg.tipo_registro == "pausa_fim" and inicio_pausa:
            pausa_seg += int((reg.timestamp - inicio_pausa).total_seconds())
            inicio_pausa = None

    if estado == "paused" and inicio_pausa:
        pausa_seg += int((agora - inicio_pausa).total_seconds())

    trabalhado_seg = max(0, conectado_seg - pausa_seg)
    fim = registros_hoje[-1].timestamp if estado == "done" else None

    return jsonify({
        "estado":         estado,
        "inicio":         inicio.isoformat(),
        "fim":            fim.isoformat() if fim else None,
        "conectado_seg":  conectado_seg,
        "pausa_seg":      pausa_seg,
        "trabalhado_seg": trabalhado_seg,
        "registros_hoje": [r.to_dict() for r in registros_hoje],
    }), 200


# ── Solicitar ajuste ───────────────────────────────────────────────────────

@ponto_bp.route("/solicitar-ajuste", methods=["POST"])
@jwt_required()
def solicitar_ajuste():
    usuario_id  = get_jwt_identity()
    dados       = request.get_json(silent=True)

    tipo        = dados.get("tipo_registro") if dados else None
    horario_str = dados.get("horario")       if dados else None
    observacao  = dados.get("observacao", "Sem motivo informado.")[:500]

    if not tipo or not horario_str:
        return jsonify({"erro": "tipo_registro e horario são obrigatórios."}), 400

    if tipo not in RegistroPonto.TIPOS_VALIDOS:
        return jsonify({"erro": "Tipo de registro inválido."}), 400

    try:
        horario = datetime.fromisoformat(horario_str)
        if horario.tzinfo is None:
            horario = horario.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return jsonify({"erro": "Formato de data inválido. Use ISO 8601."}), 400

    registro = RegistroPonto(
        usuario_id    = usuario_id,
        tipo_registro = tipo,
        timestamp     = horario,
        ip_origem     = request.remote_addr,
        dispositivo   = "Solicitação via App",
        status        = "pendente_ajuste",
        observacao    = observacao,
    )
    db.session.add(registro)
    db.session.commit()

    logger.info(f"Ajuste solicitado: usuario_id={usuario_id} tipo={tipo} horario={horario}")

    return jsonify({
        "mensagem": "Solicitação de ajuste enviada para aprovação do gestor.",
        "status":   "pendente_ajuste",
    }), 201
