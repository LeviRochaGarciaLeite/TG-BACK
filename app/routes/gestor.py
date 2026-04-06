"""
Rotas do painel de gestão — /api/gestor
Acesso restrito a perfis: gestor, admin.

Endpoints:
  GET  /equipe                                 — Lista membros da equipe
  GET  /colaborador/<id>/historico             — Histórico de um colaborador
  POST /colaborador/<id>/ajuste                — Insere ajuste manual de ponto
  GET  /pendencias                             — Lista solicitações pendentes
  POST /pendencias/<id_registro>/avaliar       — Aprova ou recusa uma solicitação
  PUT  /colaborador/<id>/perfil                — Altera o perfil do colaborador
"""

import logging
from datetime import datetime, timezone
from functools import wraps

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from ..models import db, Usuario, RegistroPonto

gestor_bp = Blueprint("gestor", __name__)
logger = logging.getLogger(__name__)


# ── Decorator de autorização ───────────────────────────────────────────────

def gestor_required(fn):
    """
    Decorador que exige perfil de gestor ou admin.
    Deve ser usado APÓS @jwt_required().
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        claims = get_jwt()
        if claims.get("perfil") not in Usuario.PERFIS_GESTORES:
            return jsonify({"erro": "Acesso negado. Restrito a gestores."}), 403
        return fn(*args, **kwargs)
    return wrapper


# ── Helper de autorização de empresa ──────────────────────────────────────

def _get_colaborador_da_empresa(id_colaborador: int, empresa_id: int):
    """Busca colaborador garantindo que pertence à empresa do gestor."""
    return Usuario.query.filter_by(
        id=id_colaborador,
        empresa_id=empresa_id,
    ).first()


# ── Listar equipe ──────────────────────────────────────────────────────────

@gestor_bp.route("/equipe", methods=["GET"])
@jwt_required()
@gestor_required
def listar_equipe():
    claims     = get_jwt()
    empresa_id = claims["empresa_id"]

    equipe = Usuario.query.filter_by(empresa_id=empresa_id, ativo=True).all()

    return jsonify({
        "empresa_id":    empresa_id,
        "total_membros": len(equipe),
        "equipe":        [m.to_dict() for m in equipe],
    }), 200


# ── Histórico de colaborador ───────────────────────────────────────────────

@gestor_bp.route("/colaborador/<int:id_colaborador>/historico", methods=["GET"])
@jwt_required()
@gestor_required
def historico_colaborador(id_colaborador: int):
    claims     = get_jwt()
    empresa_id = claims["empresa_id"]

    colaborador = _get_colaborador_da_empresa(id_colaborador, empresa_id)
    if not colaborador:
        return jsonify({"erro": "Colaborador não encontrado ou não pertence à sua equipe."}), 404

    pagina     = max(1, request.args.get("pagina", 1, type=int))
    por_pagina = min(100, request.args.get("por_pagina", 50, type=int))

    paginado = (
        RegistroPonto.query
        .filter_by(usuario_id=id_colaborador)
        .order_by(RegistroPonto.timestamp.desc())
        .paginate(page=pagina, per_page=por_pagina, error_out=False)
    )

    return jsonify({
        "colaborador":     colaborador.to_dict(),
        "total_registros": paginado.total,
        "total_paginas":   paginado.pages,
        "pagina":          paginado.page,
        "historico":       [r.to_dict() for r in paginado.items],
    }), 200


# ── Ajuste manual de ponto ─────────────────────────────────────────────────

@gestor_bp.route("/colaborador/<int:id_colaborador>/ajuste", methods=["POST"])
@jwt_required()
@gestor_required
def ajustar_ponto(id_colaborador: int):
    claims     = get_jwt()
    empresa_id = claims["empresa_id"]
    gestor_id  = get_jwt_identity() if hasattr(get_jwt, '__self__') else None

    colaborador = _get_colaborador_da_empresa(id_colaborador, empresa_id)
    if not colaborador:
        return jsonify({"erro": "Colaborador não encontrado."}), 404

    dados = request.get_json(silent=True)
    if not dados:
        return jsonify({"erro": "Corpo da requisição inválido."}), 400

    tipo        = dados.get("tipo_registro")
    horario_str = dados.get("horario")
    observacao  = dados.get("observacao", "Ajuste manual pelo gestor.")[:500]

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
        usuario_id    = id_colaborador,
        tipo_registro = tipo,
        timestamp     = horario,
        ip_origem     = request.remote_addr,
        dispositivo   = "Painel do Gestor — Ajuste Manual",
        status        = "ajustado",
        observacao    = observacao,
    )
    db.session.add(registro)
    db.session.commit()

    logger.info(
        f"Ajuste manual: colaborador_id={id_colaborador} tipo={tipo} "
        f"horario={horario} empresa_id={empresa_id}"
    )

    return jsonify({
        "mensagem":        f"Ponto ajustado para {colaborador.nome}.",
        "horario_inserido": horario.isoformat(),
        "status":          "ajustado",
    }), 201


# ── Listar pendências ──────────────────────────────────────────────────────

@gestor_bp.route("/pendencias", methods=["GET"])
@jwt_required()
@gestor_required
def listar_pendencias():
    claims     = get_jwt()
    empresa_id = claims["empresa_id"]

    pendencias = (
        db.session.query(RegistroPonto)
        .join(Usuario)
        .filter(
            Usuario.empresa_id == empresa_id,
            RegistroPonto.status == "pendente_ajuste",
        )
        .order_by(RegistroPonto.timestamp.asc())
        .all()
    )

    resultado = []
    for p in pendencias:
        item = p.to_dict()
        item["colaborador"] = p.usuario.nome
        resultado.append(item)

    return jsonify({
        "total_pendencias": len(resultado),
        "pendencias":       resultado,
    }), 200


# ── Avaliar pendência ──────────────────────────────────────────────────────

@gestor_bp.route("/pendencias/<int:id_registro>/avaliar", methods=["POST"])
@jwt_required()
@gestor_required
def avaliar_pendencia(id_registro: int):
    claims     = get_jwt()
    empresa_id = claims["empresa_id"]

    registro = (
        db.session.query(RegistroPonto)
        .join(Usuario)
        .filter(
            RegistroPonto.id == id_registro,
            Usuario.empresa_id == empresa_id,
        )
        .first()
    )

    if not registro:
        return jsonify({"erro": "Registro não encontrado ou não pertence à sua equipe."}), 404

    if registro.status != "pendente_ajuste":
        return jsonify({"erro": "Este registro não está pendente de aprovação."}), 409

    dados = request.get_json(silent=True)
    acao  = dados.get("acao") if dados else None

    acoes_validas = {
        "aprovar": ("ajustado",  "Solicitação aprovada. Ponto ajustado."),
        "recusar": ("recusado",  "Solicitação recusada pelo gestor."),
    }

    if acao not in acoes_validas:
        return jsonify({"erro": "Ação inválida. Envie 'aprovar' ou 'recusar'."}), 400

    novo_status, mensagem = acoes_validas[acao]
    registro.status = novo_status
    db.session.commit()

    logger.info(
        f"Pendência avaliada: registro_id={id_registro} acao={acao} "
        f"empresa_id={empresa_id}"
    )

    return jsonify({
        "mensagem":    mensagem,
        "novo_status": registro.status,
    }), 200


# ── Editar Perfil do Colaborador (Gestor) ──────────────────────────────────

@gestor_bp.route("/colaborador/<int:id_colaborador>/perfil", methods=["PUT"])
@jwt_required()
@gestor_required
def gestor_editar_perfil(id_colaborador: int):
    """Permite ao gestor alterar o nome e a foto de um colaborador da sua equipe."""
    claims     = get_jwt()
    empresa_id = claims["empresa_id"]

    colaborador = _get_colaborador_da_empresa(id_colaborador, empresa_id)
    if not colaborador:
        return jsonify({"erro": "Colaborador não encontrado ou não pertence à sua equipe."}), 404

    dados = request.get_json(silent=True)
    if not dados:
        return jsonify({"erro": "Corpo da requisição inválido."}), 400

    if "nome" in dados and dados["nome"].strip():
        colaborador.nome = dados["nome"].strip()

    if "foto_perfil" in dados:
        colaborador.foto_perfil = dados["foto_perfil"]

    db.session.commit()
    logger.info(f"Perfil do colaborador editado pelo gestor: colaborador_id={id_colaborador}")

    return jsonify({
        "mensagem": "Perfil do colaborador atualizado com sucesso.",
        "nome": colaborador.nome,
        "foto_perfil": colaborador.foto_perfil
    }), 200