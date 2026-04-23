"""
Rotas de ponto eletrônico — /api/ponto
Endpoints:
  POST /registrar         — Bate o ponto (entrada, pausa_inicio, pausa_fim, saida)
  GET  /historico         — Histórico do usuário logado (com paginação)
  GET  /status-atual      — Estado atual da jornada (idle | working | paused | done)
    GET  /resumo-dia        — Resumo da jornada com classificação por cenários
  POST /solicitar-ajuste  — Solicita ajuste manual para aprovação do gestor
"""

import logging
from datetime import datetime, timezone, date, timedelta
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from ..models import db, RegistroPonto, Usuario, Equipe
from .gestor import push_gestor_event
from .notificacoes import criar_notificacao

ponto_bp = Blueprint("ponto", __name__)
logger = logging.getLogger(__name__)


# ── Configuração dos cenários de pontuação ───────────────────────────────

CENARIO_BOM = {
    "min_conectado_seg": 6 * 3600 + 30 * 60,  # 6h30
    "min_trabalhado_seg": 6 * 3600,           # 6h
    "max_pausa_seg": 30 * 60,                 # 30min
    "max_inicio_hora": 8,
    "max_inicio_min": 30,
    "max_pausas": 2,
    "max_atraso_seg": 60,                     # 1min
}

CENARIO_RUIM = {
    "min_conectado_seg": 5 * 3600 + 30 * 60,  # 5h30
    "min_trabalhado_seg": 5 * 3600,           # 5h
    "max_pausa_seg": 35 * 60,                 # 35min
    "max_inicio_hora": 8,
    "max_inicio_min": 35,
    "max_pausas": 3,
    "max_atraso_seg": 5 * 60,                 # 5min
}

HORARIO_ESPERADO = {"hora": 8, "minuto": 0}


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


def _agora_compativel(referencia_dt: datetime | None) -> datetime:
    """Retorna "agora" com o mesmo padrão de timezone da referência."""
    if referencia_dt and referencia_dt.tzinfo is None:
        return datetime.utcnow()
    return datetime.now(timezone.utc)


def _calcular_pontos_por_cenario(
    conectado_seg: int,
    trabalhado_seg: int,
    pausa_seg: int,
    atraso_seg: int,
    qtd_pausas: int,
    inicio_hora: int,
    inicio_min: int,
):
    def verifica_cenario(cfg):
        inicio_ok = (
            inicio_hora < cfg["max_inicio_hora"]
            or (inicio_hora == cfg["max_inicio_hora"] and inicio_min <= cfg["max_inicio_min"])
        )
        return (
            conectado_seg >= cfg["min_conectado_seg"]
            and trabalhado_seg >= cfg["min_trabalhado_seg"]
            and pausa_seg <= cfg["max_pausa_seg"]
            and qtd_pausas <= cfg["max_pausas"]
            and atraso_seg <= cfg["max_atraso_seg"]
            and inicio_ok
        )

    if verifica_cenario(CENARIO_BOM):
        positivos = 100
        negativos = 0

        if qtd_pausas == 0:
            positivos += 10
        if inicio_hora < 8:
            positivos += 5

        if qtd_pausas > 1:
            negativos += (qtd_pausas - 1) * 5
        if atraso_seg > 0:
            negativos += int(atraso_seg / 60 + 0.999) * 2

        return "BOM", "Bom", positivos, negativos

    if verifica_cenario(CENARIO_RUIM):
        positivos = 60
        negativos = 10

        if qtd_pausas > 2:
            negativos += (qtd_pausas - 2) * 8
        if atraso_seg > 0:
            negativos += int(atraso_seg / 60 + 0.999) * 4

        pausa_extra = max(0, pausa_seg - CENARIO_BOM["max_pausa_seg"])
        negativos += int(pausa_extra / 600 + 0.999) * 3

        return "RUIM", "Ruim", positivos, negativos

    positivos = max(0, round((trabalhado_seg / (5 * 3600)) * 40))
    negativos = 30

    if qtd_pausas > 3:
        negativos += (qtd_pausas - 3) * 10
    if atraso_seg > 0:
        negativos += int(atraso_seg / 60 + 0.999) * 5

    return "PIOR", "Pior", positivos, negativos


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
    if colaborador:
        mensagens_ponto = {
            "entrada": f"🟢 {colaborador.nome} começou a trabalhar.",
            "pausa_inicio": f"🟡 {colaborador.nome} iniciou uma pausa.",
            "pausa_fim": f"🟢 {colaborador.nome} voltou da pausa.",
            "saida": f"🔴 {colaborador.nome} encerrou o ponto.",
        }
        msg = mensagens_ponto.get(tipo)
        if msg:
            _notificar_gestores_do_colaborador(colaborador, msg, tela="gestao")

    db.session.commit()

    if colaborador:
        push_gestor_event(colaborador.empresa_id, {
            "tipo": "ponto_atualizado",
            "colaborador_id": colaborador.id,
            "nome": colaborador.nome,
            "registro": tipo,
            "novo_estado": _estado_jornada(_registros_de_hoje(usuario_id)),
            "horario": novo.timestamp.isoformat(),
        })

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

    inicio        = registros_hoje[0].timestamp
    agora         = _agora_compativel(inicio)
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


# ── Resumo do dia ─────────────────────────────────────────────────────────

@ponto_bp.route("/resumo-dia", methods=["GET"])
@jwt_required()
def resumo_dia():
    """
    Retorna o resumo da jornada do dia atual para o colaborador logado.
    Calcula os pontos usando o sistema de cenários da empresa.
    """
    usuario_id = int(get_jwt_identity())
    registros = _registros_de_hoje(usuario_id)

    if not registros:
        return jsonify({
            "connectedTimeInSeconds": 0,
            "workedTimeInSeconds":    0,
            "pauseTimeInSeconds":     0,
            "startedAt":              None,
            "pauseCount":             0,
            "lateTimeInSeconds":      0,
            "positivePoints":         0,
            "negativePoints":         0,
            "cenario":                None,
            "cenarioLabel":           None,
            "cenarioColor":           None,
        }), 200

    entrada_dt = None
    saida_dt = None
    pausa_inicio = None
    pausas = []

    for r in registros:
        tipo = r.tipo_registro
        if tipo == "entrada" and entrada_dt is None:
            entrada_dt = r.timestamp
        elif tipo == "pausa_inicio":
            pausa_inicio = r.timestamp
        elif tipo == "pausa_fim" and pausa_inicio:
            pausas.append((pausa_inicio, r.timestamp))
            pausa_inicio = None
        elif tipo == "saida":
            saida_dt = r.timestamp

    referencia_dt = entrada_dt or registros[0].timestamp
    fim = saida_dt or _agora_compativel(referencia_dt)

    conectado_seg = 0
    if entrada_dt:
        conectado_seg = int((fim - entrada_dt).total_seconds())

    pausa_seg = 0
    for inicio_p, fim_p in pausas:
        pausa_seg += int((fim_p - inicio_p).total_seconds())

    if pausa_inicio:
        pausa_seg += int((fim - pausa_inicio).total_seconds())

    trabalhado_seg = max(0, conectado_seg - pausa_seg)

    atraso_seg = 0
    if entrada_dt:
        esperado = entrada_dt.replace(
            hour=HORARIO_ESPERADO["hora"],
            minute=HORARIO_ESPERADO["minuto"],
            second=0,
            microsecond=0,
        )
        diff = (entrada_dt - esperado).total_seconds()
        atraso_seg = max(0, int(diff))

    inicio_hora = entrada_dt.hour if entrada_dt else 9
    inicio_min = entrada_dt.minute if entrada_dt else 0
    qtd_pausas = len(pausas) + (1 if pausa_inicio else 0)

    cenario, cenario_label, positivos, negativos = _calcular_pontos_por_cenario(
        conectado_seg=conectado_seg,
        trabalhado_seg=trabalhado_seg,
        pausa_seg=pausa_seg,
        atraso_seg=atraso_seg,
        qtd_pausas=qtd_pausas,
        inicio_hora=inicio_hora,
        inicio_min=inicio_min,
    )

    cores_cenario = {
        "BOM": "#00e87a",
        "RUIM": "#f59e0b",
        "PIOR": "#ef4444",
    }

    # ── Atualiza os pontos no banco de dados ────────────────────────────────
    usuario = db.session.get(Usuario, usuario_id)
    if usuario:
        usuario.pontos_positivos = positivos
        usuario.pontos_negativos = negativos
        db.session.commit()
        logger.info(f"Pontos atualizados: usuario_id={usuario_id} positivos={positivos} negativos={negativos}")

    return jsonify({
        "connectedTimeInSeconds": conectado_seg,
        "workedTimeInSeconds":    trabalhado_seg,
        "pauseTimeInSeconds":     pausa_seg,
        "startedAt":              entrada_dt.isoformat() if entrada_dt else None,
        "pauseCount":             qtd_pausas,
        "lateTimeInSeconds":      atraso_seg,
        "positivePoints":         positivos,
        "negativePoints":         negativos,
        "cenario":                cenario,
        "cenarioLabel":           cenario_label,
        "cenarioColor":           cores_cenario[cenario],
    }), 200


# ── Histórico consolidado por dia ──────────────────────────────────────────

@ponto_bp.route("/historico-dias", methods=["GET"])
@jwt_required()
def historico_dias():
    """
    Retorna um resumo consolidado dos últimos N dias.
    Parâmetros:
      - dias: número de dias a retornar (default: 7)
    """
    usuario_id = int(get_jwt_identity())
    num_dias = min(30, max(1, request.args.get("dias", 7, type=int)))

    # Calcula a data de início (N dias atrás)
    data_inicio = datetime.combine(
        date.today() - timedelta(days=num_dias),
        datetime.min.time()
    ).replace(tzinfo=timezone.utc)

    # Busca todos os registros do período
    registros = (
        RegistroPonto.query
        .filter(
            RegistroPonto.usuario_id == usuario_id,
            RegistroPonto.timestamp >= data_inicio,
            RegistroPonto.status.in_(["valido", "ajustado"]),
        )
        .order_by(RegistroPonto.timestamp.asc())
        .all()
    )

    # Agrupa registros por dia
    dias_dict = {}
    for reg in registros:
        data_str = reg.timestamp.date().isoformat()
        if data_str not in dias_dict:
            dias_dict[data_str] = []
        dias_dict[data_str].append(reg)

    # Calcula o resumo para cada dia
    resumos = []
    for data_str in sorted(dias_dict.keys(), reverse=True):
        registros_dia = dias_dict[data_str]
        
        entrada_dt = None
        saida_dt = None
        pausa_inicio = None
        pausas = []

        for r in registros_dia:
            tipo = r.tipo_registro
            if tipo == "entrada" and entrada_dt is None:
                entrada_dt = r.timestamp
            elif tipo == "pausa_inicio":
                pausa_inicio = r.timestamp
            elif tipo == "pausa_fim" and pausa_inicio:
                pausas.append((pausa_inicio, r.timestamp))
                pausa_inicio = None
            elif tipo == "saida":
                saida_dt = r.timestamp

        fim = saida_dt or datetime.now(timezone.utc)

        conectado_seg = 0
        if entrada_dt:
            conectado_seg = int((fim - entrada_dt).total_seconds())

        pausa_seg = 0
        for inicio_p, fim_p in pausas:
            pausa_seg += int((fim_p - inicio_p).total_seconds())

        if pausa_inicio:
            pausa_seg += int((fim - pausa_inicio).total_seconds())

        trabalhado_seg = max(0, conectado_seg - pausa_seg)

        atraso_seg = 0
        if entrada_dt:
            esperado = entrada_dt.replace(
                hour=HORARIO_ESPERADO["hora"],
                minute=HORARIO_ESPERADO["minuto"],
                second=0,
                microsecond=0,
            )
            diff = (entrada_dt - esperado).total_seconds()
            atraso_seg = max(0, int(diff))

        inicio_hora = entrada_dt.hour if entrada_dt else 9
        inicio_min = entrada_dt.minute if entrada_dt else 0
        qtd_pausas = len(pausas) + (1 if pausa_inicio else 0)

        cenario, cenario_label, positivos, negativos = _calcular_pontos_por_cenario(
            conectado_seg=conectado_seg,
            trabalhado_seg=trabalhado_seg,
            pausa_seg=pausa_seg,
            atraso_seg=atraso_seg,
            qtd_pausas=qtd_pausas,
            inicio_hora=inicio_hora,
            inicio_min=inicio_min,
        )

        cores_cenario = {
            "BOM": "#00e87a",
            "RUIM": "#f59e0b",
            "PIOR": "#ef4444",
        }

        resumos.append({
            "date": data_str,
            "startedAt": entrada_dt.isoformat() if entrada_dt else None,
            "connectedTimeInSeconds": conectado_seg,
            "workedTimeInSeconds": trabalhado_seg,
            "pauseTimeInSeconds": pausa_seg,
            "pauseCount": qtd_pausas,
            "lateTimeInSeconds": atraso_seg,
            "positivePoints": positivos,
            "negativePoints": negativos,
            "cenario": cenario,
            "cenarioLabel": cenario_label,
            "cenarioColor": cores_cenario[cenario],
        })

    return jsonify(resumos), 200


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
