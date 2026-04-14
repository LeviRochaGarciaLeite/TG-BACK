"""
Rota de holerite — /api/holerite
Endpoints:
  GET  /dados   — Retorna os dados do holerite do mês atual para o usuário logado
  POST /confirmar — Registra que o usuário confirmou o recebimento
"""

import logging
from datetime import datetime, timezone, date
from calendar import monthrange
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from ..models import db, Usuario, RegistroPonto
from .notificacoes import criar_notificacao

holerite_bp = Blueprint("holerite", __name__)
logger = logging.getLogger(__name__)

# ── Configurações fixas (ajuste conforme necessidade) ──────────────────────────
SALARIO_BASE      = 3573.27   # R$ — substitua por campo no modelo se houver
DIA_PAGAMENTO     = 8         # Dia fixo de pagamento todo mês
HORA_CONTRATUAL   = 8.0       # Horas diárias contratadas
VALOR_HORA        = SALARIO_BASE / 22 / HORA_CONTRATUAL  # Valor por hora (22 dias úteis)
INSS_ALIQUOTA     = 0.075     # 7,5% INSS simplificado
IRRF_ALIQUOTA     = 0.075     # 7,5% IRRF simplificado (faixa exemplo)
VT_DESCONTO       = 6.0       # % de desconto de Vale Transporte
VR_VALOR          = 25.0      # R$ por dia de Vale Refeição

# ── Helpers ────────────────────────────────────────────────────────────────────

def _formatar_cpf(cpf: str) -> str:
    """Formata CPF: 12345678901 → 123.456.789-01"""
    c = cpf.replace(".", "").replace("-", "").strip()
    if len(c) == 11:
        return f"{c[:3]}.{c[3:6]}.{c[6:9]}-{c[9:]}"
    return cpf


def _registros_do_mes(usuario_id: int, ano: int, mes: int) -> list:
    """Retorna todos os registros válidos do mês/ano para o usuário."""
    inicio = datetime(ano, mes, 1, tzinfo=timezone.utc)
    ultimo_dia = monthrange(ano, mes)[1]
    fim = datetime(ano, mes, ultimo_dia, 23, 59, 59, tzinfo=timezone.utc)

    return (
        RegistroPonto.query
        .filter(
            RegistroPonto.usuario_id == usuario_id,
            RegistroPonto.timestamp >= inicio,
            RegistroPonto.timestamp <= fim,
            RegistroPonto.status.in_(["valido", "ajustado"]),
        )
        .order_by(RegistroPonto.timestamp.asc())
        .all()
    )


def _agrupar_por_dia(registros: list) -> dict:
    """Agrupa registros por data (YYYY-MM-DD)."""
    dias = {}
    for r in registros:
        dia_key = r.timestamp.strftime("%Y-%m-%d")
        if dia_key not in dias:
            dias[dia_key] = []
        dias[dia_key].append(r)
    return dias


def _calcular_horas_dia(registros_dia: list) -> float:
    """Calcula horas trabalhadas em um dia (descontando pausas). Retorna float em horas."""
    if not registros_dia:
        return 0.0

    entrada = None
    saida   = None
    pausa_seg = 0
    inicio_pausa = None

    for r in registros_dia:
        if r.tipo_registro == "entrada":
            entrada = r.timestamp
        elif r.tipo_registro == "saida":
            saida = r.timestamp
        elif r.tipo_registro == "pausa_inicio":
            inicio_pausa = r.timestamp
        elif r.tipo_registro == "pausa_fim" and inicio_pausa:
            pausa_seg += int((r.timestamp - inicio_pausa).total_seconds())
            inicio_pausa = None

    if not entrada:
        return 0.0

    fim = saida if saida else registros_dia[-1].timestamp
    total_seg = max(0, int((fim - entrada).total_seconds()) - pausa_seg)
    return round(total_seg / 3600, 2)


def _calcular_holerite(usuario: Usuario, ano: int, mes: int) -> dict:
    """Monta o dicionário completo de dados do holerite."""
    registros = _registros_do_mes(usuario.id, ano, mes)
    dias_grupo = _agrupar_por_dia(registros)

    # ── Resumo de frequência ───────────────────────────────────────────────
    dias_trabalhados = 0
    total_horas_mes  = 0.0
    detalhes_dias    = []

    for dia_key in sorted(dias_grupo.keys()):
        regs = dias_grupo[dia_key]
        horas = _calcular_horas_dia(regs)
        if horas > 0:
            dias_trabalhados += 1
            total_horas_mes  += horas

        # Determina entrada e saída do dia
        entrada_reg = next((r for r in regs if r.tipo_registro == "entrada"), None)
        saida_reg   = next((r for r in regs if r.tipo_registro == "saida"),   None)
        n_pausas    = sum(1 for r in regs if r.tipo_registro == "pausa_inicio")

        detalhes_dias.append({
            "data":    dia_key,
            "entrada": entrada_reg.timestamp.strftime("%H:%M") if entrada_reg else "--",
            "saida":   saida_reg.timestamp.strftime("%H:%M")   if saida_reg   else "--",
            "pausas":  n_pausas,
            "horas":   horas,
        })

    # ── Cálculos de vencimentos ───────────────────────────────────────────
    salario_bruto = SALARIO_BASE

    # Horas extras (acima de 8h/dia com 50%)
    horas_extras = 0.0
    for dia_key in sorted(dias_grupo.keys()):
        horas_dia = _calcular_horas_dia(dias_grupo[dia_key])
        extra = max(0, horas_dia - HORA_CONTRATUAL)
        horas_extras += extra

    valor_hora_extra = round(VALOR_HORA * 1.5, 4)
    total_hora_extra = round(horas_extras * valor_hora_extra, 2)

    vr_total = round(dias_trabalhados * VR_VALOR, 2)   # Vale Refeição (não é descontado)

    total_vencimentos = round(salario_bruto + total_hora_extra, 2)

    # ── Descontos ─────────────────────────────────────────────────────────
    inss       = round(total_vencimentos * INSS_ALIQUOTA, 2)
    irrf       = round(total_vencimentos * IRRF_ALIQUOTA, 2)
    vt_desc    = round(salario_bruto * (VT_DESCONTO / 100), 2)

    total_descontos = round(inss + irrf + vt_desc, 2)
    salario_liquido = round(total_vencimentos - total_descontos, 2)

    # ── Data de pagamento ─────────────────────────────────────────────────
    data_pgto = date(ano, mes, min(DIA_PAGAMENTO, monthrange(ano, mes)[1]))

    nome_meses = [
        "Janeiro","Fevereiro","Março","Abril","Maio","Junho",
        "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"
    ]

    return {
        # Dados do colaborador
        "colaborador": {
            "nome":        usuario.nome,
            "cpf":         _formatar_cpf(usuario.cpf),
            "cargo":       usuario.perfil.capitalize(),
            "empresa_id":  usuario.empresa_id,
        },
        # Competência
        "competencia": {
            "mes":         mes,
            "ano":         ano,
            "mes_nome":    nome_meses[mes - 1],
            "descricao":   f"{nome_meses[mes - 1]} / {ano}",
        },
        # Pagamento
        "pagamento": {
            "data":            data_pgto.strftime("%d/%m/%Y"),
            "dia":             DIA_PAGAMENTO,
        },
        # Frequência
        "frequencia": {
            "dias_trabalhados": dias_trabalhados,
            "total_horas":      round(total_horas_mes, 2),
            "horas_extras":     round(horas_extras, 2),
            "detalhes_dias":    detalhes_dias,
        },
        # Financeiro
        "financeiro": {
            "salario_base":       salario_bruto,
            "horas_extras_valor": total_hora_extra,
            "vale_refeicao":      vr_total,
            "total_vencimentos":  total_vencimentos,
            "descontos": {
                "inss":              inss,
                "irrf":              irrf,
                "vale_transporte":   vt_desc,
                "total_descontos":   total_descontos,
            },
            "salario_liquido":    salario_liquido,
        },
    }


# ── Rota: dados do holerite ───────────────────────────────────────────────────

@holerite_bp.route("/dados", methods=["GET"])
@jwt_required()
def dados_holerite():
    """
    Retorna os dados do holerite do mês/ano especificado (default: mês atual).
    Query params: ?mes=4&ano=2025
    """
    usuario_id = int(get_jwt_identity())
    usuario    = Usuario.query.get(usuario_id)

    if not usuario or not usuario.ativo:
        return jsonify({"erro": "Usuário não encontrado."}), 404

    hoje = date.today()
    mes  = request.args.get("mes", hoje.month, type=int)
    ano  = request.args.get("ano", hoje.year,  type=int)

    # Validações básicas
    if not (1 <= mes <= 12):
        return jsonify({"erro": "Mês inválido."}), 400
    if ano < 2020 or ano > hoje.year:
        return jsonify({"erro": "Ano inválido."}), 400

    try:
        dados = _calcular_holerite(usuario, ano, mes)
        logger.info(f"Holerite consultado: usuario_id={usuario_id} {mes}/{ano}")
        return jsonify(dados), 200
    except Exception as e:
        logger.error(f"Erro ao calcular holerite: {e}", exc_info=True)
        return jsonify({"erro": "Erro ao calcular holerite."}), 500


# ── Rota: confirmar recebimento ───────────────────────────────────────────────

@holerite_bp.route("/confirmar", methods=["POST"])
@jwt_required()
def confirmar_holerite():
    """
    Registra a confirmação de recebimento do holerite.
    Body JSON: { "mes": 4, "ano": 2025 }
    """
    usuario_id = int(get_jwt_identity())
    dados = request.get_json(silent=True) or {}

    hoje = date.today()
    mes  = dados.get("mes", hoje.month)
    ano  = dados.get("ano", hoje.year)

    usuario = db.session.get(Usuario, usuario_id)
    if not usuario:
        return jsonify({"erro": "Usuário não encontrado."}), 404

    nome_meses = [
        "Janeiro","Fevereiro","Março","Abril","Maio","Junho",
        "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"
    ]
    mes_nome = nome_meses[mes - 1] if 1 <= mes <= 12 else str(mes)

    # Notifica o próprio colaborador
    criar_notificacao(
        usuario_id,
        f"\U0001f4c4 Você confirmou o recebimento do holerite de {mes_nome}/{ano}.",
        tipo="holerite",
        tela="holerite",
    )

    # Notifica os gestores da empresa
    gestores = Usuario.query.filter(
        Usuario.empresa_id == usuario.empresa_id,
        Usuario.perfil.in_(["gestor", "admin"]),
        Usuario.ativo == True,
    ).all()
    for gestor in gestores:
        criar_notificacao(
            gestor.id,
            f"\U0001f4c4 {usuario.nome} confirmou o holerite de {mes_nome}/{ano}.",
            tipo="holerite",
            tela=None,
        )

    db.session.commit()
    logger.info(f"Holerite confirmado: usuario_id={usuario_id} {mes}/{ano}")

    return jsonify({
        "mensagem":   "Recebimento confirmado com sucesso.",
        "usuario_id": usuario_id,
        "mes":        mes,
        "ano":        ano,
        "confirmado_em": datetime.now(timezone.utc).isoformat(),
    }), 200
