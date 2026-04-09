"""
Endpoint: GET /api/ponto/resumo-dia

Adicione este bloco ao arquivo: app/routes/ponto.py

Ele calcula o resumo completo do dia do usuário autenticado e retorna
os dados que o front-end precisa para a tela "Resumo do Dia".

Inclui:
- tempo conectado, trabalhado e em pausas
- horário de início e quantidade de pausas
- atraso (se iniciou depois das 08:00)
- pontuação positiva, negativa e total
"""

from datetime import time as dt_time


# ── Configurações de pontuação (ajuste conforme regras de negócio) ──────────

JORNADA_ESPERADA_SEG = 8 * 3600          # 8 horas
HORARIO_ESPERADO_INICIO = dt_time(8, 0)  # 08:00
PONTOS_POR_HORA_PAUSA = 5                # descontar 5 pts por hora de pausa


def _calcular_pontuacao(trabalhado_seg: int, pausa_seg: int, atraso_seg: int) -> dict:
    """
    Heurística de pontuação:
    - positivos: proporcional ao tempo trabalhado (máx 100)
    - negativos: 5 pts por hora de pausa + 2 pts por hora de atraso
    """
    pct_trabalhado = min(1.0, trabalhado_seg / JORNADA_ESPERADA_SEG)
    positivos = round(pct_trabalhado * 100)

    negativos_pausa  = round((pausa_seg / 3600) * PONTOS_POR_HORA_PAUSA)
    negativos_atraso = round((atraso_seg / 3600) * 2)
    negativos = negativos_pausa + negativos_atraso

    return {
        "positive_points": positivos,
        "negative_points": negativos,
        "total_points": positivos - negativos,
    }


# ─── Cole este endpoint dentro do arquivo ponto.py ─────────────────────────

@ponto_bp.route("/resumo-dia", methods=["GET"])
@jwt_required()
def resumo_dia():
    """
    Retorna o resumo completo da jornada do dia para o usuário autenticado.
    Chamado pelo front-end após o logout, antes de limpar o estado.
    """
    usuario_id     = get_jwt_identity()
    registros_hoje = _registros_de_hoje(usuario_id)
    estado         = _estado_jornada(registros_hoje)

    if not registros_hoje:
        # Nenhuma jornada registrada hoje
        return jsonify({
            "connectedTimeInSeconds": 0,
            "workedTimeInSeconds":    0,
            "pauseTimeInSeconds":     0,
            "startedAt":              None,
            "pauseCount":             0,
            "lateTimeInSeconds":      0,
            "positivePoints":         0,
            "negativePoints":         0,
        }), 200

    agora  = datetime.now(timezone.utc)
    inicio = registros_hoje[0].timestamp

    # ── Tempo total conectado ───────────────────────────────────────────────
    fim = registros_hoje[-1].timestamp if estado == "done" else agora
    conectado_seg = int((fim - inicio).total_seconds())

    # ── Cálculo de pausas ───────────────────────────────────────────────────
    pausa_seg    = 0
    pausa_count  = 0
    inicio_pausa = None

    for reg in registros_hoje:
        if reg.tipo_registro == "pausa_inicio":
            inicio_pausa = reg.timestamp
            pausa_count += 1
        elif reg.tipo_registro == "pausa_fim" and inicio_pausa:
            pausa_seg   += int((reg.timestamp - inicio_pausa).total_seconds())
            inicio_pausa = None

    # Pausa ainda em andamento
    if estado == "paused" and inicio_pausa:
        pausa_seg += int((agora - inicio_pausa).total_seconds())

    trabalhado_seg = max(0, conectado_seg - pausa_seg)

    # ── Atraso ──────────────────────────────────────────────────────────────
    inicio_esperado = datetime.combine(
        inicio.date(),
        HORARIO_ESPERADO_INICIO,
        tzinfo=timezone.utc,
    )
    atraso_seg = max(0, int((inicio - inicio_esperado).total_seconds()))

    # ── Pontuação ───────────────────────────────────────────────────────────
    pontuacao = _calcular_pontuacao(trabalhado_seg, pausa_seg, atraso_seg)

    return jsonify({
        "connectedTimeInSeconds": conectado_seg,
        "workedTimeInSeconds":    trabalhado_seg,
        "pauseTimeInSeconds":     pausa_seg,
        "startedAt":              inicio.isoformat(),
        "pauseCount":             pausa_count,
        "lateTimeInSeconds":      atraso_seg,
        "positivePoints":         pontuacao["positive_points"],
        "negativePoints":         pontuacao["negative_points"],
    }), 200
