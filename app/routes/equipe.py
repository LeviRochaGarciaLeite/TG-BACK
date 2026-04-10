"""
Rotas de equipe — /api/equipe

Endpoints:
  POST /criar          — Supervisor cria/atualiza sua equipe (vincula 2 colaboradores)
  GET  /minha          — Qualquer usuário vê a equipe a que pertence
  GET  /supervisor     — Supervisor vê a equipe que ele gerencia
"""

import logging
from functools import wraps

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from ..models import db, Usuario, Equipe

equipe_bp = Blueprint("equipe", __name__)
logger = logging.getLogger(__name__)


# ── Decorator: apenas supervisores/gestores/admin ─────────────────────────

def gestor_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        claims = get_jwt()
        if claims.get("perfil") not in Usuario.PERFIS_GESTORES:
            return jsonify({"erro": "Acesso negado. Restrito a gestores."}), 403
        return fn(*args, **kwargs)
    return wrapper


# ── POST /api/equipe/criar ────────────────────────────────────────────────

@equipe_bp.route("/criar", methods=["POST"])
@jwt_required()
@gestor_required
def criar_equipe():
    """
    Supervisor cria ou atualiza sua equipe vinculando exatamente 2 colaboradores.

    Body JSON:
    {
        "colaborador_ids": [1, 2]   // lista com exatamente 2 IDs
    }
    """
    claims        = get_jwt()
    supervisor_id = int(get_jwt_identity())
    empresa_id    = claims["empresa_id"]

    dados = request.get_json(silent=True)
    if not dados:
        return jsonify({"erro": "Corpo da requisição inválido."}), 400

    colaborador_ids = dados.get("colaborador_ids", [])

    if not isinstance(colaborador_ids, list) or len(colaborador_ids) != 2:
        return jsonify({"erro": "Informe exatamente 2 colaboradores em colaborador_ids."}), 400

    if supervisor_id in colaborador_ids:
        return jsonify({"erro": "O supervisor não pode ser colaborador da própria equipe."}), 400

    # Valida que os colaboradores existem e pertencem à mesma empresa
    colaboradores = (
        Usuario.query
        .filter(
            Usuario.id.in_(colaborador_ids),
            Usuario.empresa_id == empresa_id,
            Usuario.ativo == True,
        )
        .all()
    )

    if len(colaboradores) != 2:
        return jsonify({
            "erro": "Um ou mais colaboradores não foram encontrados ou não pertencem à sua empresa."
        }), 404

    # Verifica se esses colaboradores já estão em outra equipe como colaboradores
    for colab_id in colaborador_ids:
        equipe_existente = Equipe.query.filter(
            Equipe.empresa_id == empresa_id,
            db.or_(
                Equipe.colaborador1_id == colab_id,
                Equipe.colaborador2_id == colab_id,
            )
        ).filter(Equipe.supervisor_id != supervisor_id).first()

        if equipe_existente:
            nome_colab = next(c.nome for c in colaboradores if c.id == colab_id)
            return jsonify({
                "erro": f"O colaborador {nome_colab} já pertence a outra equipe."
            }), 409

    # Cria ou atualiza a equipe deste supervisor
    equipe = Equipe.query.filter_by(supervisor_id=supervisor_id, empresa_id=empresa_id).first()

    if equipe:
        equipe.colaborador1_id = colaborador_ids[0]
        equipe.colaborador2_id = colaborador_ids[1]
    else:
        equipe = Equipe(
            supervisor_id    = supervisor_id,
            empresa_id       = empresa_id,
            colaborador1_id  = colaborador_ids[0],
            colaborador2_id  = colaborador_ids[1],
        )
        db.session.add(equipe)

    db.session.commit()

    supervisor  = Usuario.query.get(supervisor_id)
    colabs_dict = [c.to_dict() for c in colaboradores]

    logger.info(
        f"Equipe criada/atualizada: supervisor_id={supervisor_id} "
        f"colaboradores={colaborador_ids} empresa_id={empresa_id}"
    )

    return jsonify({
        "mensagem":      "Equipe criada com sucesso.",
        "supervisor":    supervisor.to_dict(),
        "colaboradores": colabs_dict,
    }), 201


# ── GET /api/equipe/minha ─────────────────────────────────────────────────

@equipe_bp.route("/minha", methods=["GET"])
@jwt_required()
def minha_equipe():
    """
    Retorna a equipe do usuário logado.
    - Colaborador: busca equipe onde ele aparece como colaborador1 ou colaborador2
    - Supervisor: retorna a equipe que ele gerencia (mesma resposta do /supervisor)
    """
    claims     = get_jwt()
    usuario_id = int(get_jwt_identity())
    perfil     = claims.get("perfil")
    empresa_id = claims["empresa_id"]

    # Se for supervisor, retorna a equipe que ele criou
    if perfil in Usuario.PERFIS_GESTORES:
        equipe = Equipe.query.filter_by(
            supervisor_id=usuario_id,
            empresa_id=empresa_id,
        ).first()
    else:
        # Colaborador: busca equipe onde aparece
        equipe = Equipe.query.filter(
            Equipe.empresa_id == empresa_id,
            db.or_(
                Equipe.colaborador1_id == usuario_id,
                Equipe.colaborador2_id == usuario_id,
            )
        ).first()

    if not equipe:
        return jsonify({"erro": "Você ainda não pertence a nenhuma equipe."}), 404

    supervisor   = Usuario.query.get(equipe.supervisor_id)
    colaborador1 = Usuario.query.get(equipe.colaborador1_id)
    colaborador2 = Usuario.query.get(equipe.colaborador2_id)

    return jsonify({
        "supervisor":    supervisor.to_dict()    if supervisor   else None,
        "colaboradores": [
            colaborador1.to_dict() if colaborador1 else None,
            colaborador2.to_dict() if colaborador2 else None,
        ],
    }), 200


# ── GET /api/equipe/supervisor ────────────────────────────────────────────

@equipe_bp.route("/supervisor", methods=["GET"])
@jwt_required()
@gestor_required
def equipe_do_supervisor():
    """
    Supervisor consulta a equipe que ele gerencia.
    Também retorna lista de colaboradores disponíveis (sem equipe) para montar a equipe.
    """
    claims        = get_jwt()
    supervisor_id = int(get_jwt_identity())
    empresa_id    = claims["empresa_id"]

    equipe = Equipe.query.filter_by(
        supervisor_id=supervisor_id,
        empresa_id=empresa_id,
    ).first()

    # Colaboradores já vinculados em alguma equipe nesta empresa
    equipes_existentes = Equipe.query.filter_by(empresa_id=empresa_id).all()
    ids_vinculados = set()
    for eq in equipes_existentes:
        ids_vinculados.add(eq.colaborador1_id)
        ids_vinculados.add(eq.colaborador2_id)
        ids_vinculados.add(eq.supervisor_id)

    # Colaboradores disponíveis para este supervisor vincular
    disponiveis = (
        Usuario.query
        .filter(
            Usuario.empresa_id == empresa_id,
            Usuario.ativo == True,
            Usuario.perfil == "colaborador",
            ~Usuario.id.in_(ids_vinculados),
        )
        .all()
    )

    resposta = {
        "disponiveis": [u.to_dict() for u in disponiveis],
    }

    if equipe:
        supervisor   = Usuario.query.get(equipe.supervisor_id)
        colaborador1 = Usuario.query.get(equipe.colaborador1_id)
        colaborador2 = Usuario.query.get(equipe.colaborador2_id)

        resposta["equipe"] = {
            "supervisor":    supervisor.to_dict()    if supervisor   else None,
            "colaboradores": [
                colaborador1.to_dict() if colaborador1 else None,
                colaborador2.to_dict() if colaborador2 else None,
            ],
        }
    else:
        resposta["equipe"] = None

    return jsonify(resposta), 200
