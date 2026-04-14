"""
Rotas de equipe — /api/equipe

Endpoints:
  POST /organizar         — Supervisor cria/atualiza sua equipe
  GET  /minha             — Qualquer usuário vê a equipe a que pertence
  GET  /supervisor        — Supervisor vê equipe que gerencia + colaboradores disponíveis
  GET  /colaboradores-disponiveis — Lista colaboradores sem equipe (para seleção)
  GET  /buscar?q=         — Supervisor busca colaboradores disponíveis por nome
  POST /adicionar         — Supervisor adiciona um colaborador à sua equipe
  POST /remover           — Supervisor remove um colaborador da sua equipe
"""

import logging
from functools import wraps

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from ..models import db, Usuario, Equipe, equipe_membros
from .notificacoes import criar_notificacao

equipe_bp = Blueprint("equipe", __name__)
logger = logging.getLogger(__name__)


def _notificar_gestores_equipe(empresa_id: int, mensagem: str, tela=None):
    """Notifica todos os gestores/admins da empresa sobre mudança na equipe."""
    gestores = Usuario.query.filter(
        Usuario.empresa_id == empresa_id,
        Usuario.perfil.in_(["gestor", "admin"]),
        Usuario.ativo == True,
    ).all()
    for gestor in gestores:
        criar_notificacao(gestor.id, mensagem, tipo="equipe", tela=tela)


# ── Decorator: apenas supervisor ──────────────────────────────────────────

def supervisor_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        claims = get_jwt()
        if claims.get("perfil") != Usuario.PERFIL_SUPERVISOR:
            return jsonify({"erro": "Acesso negado. Exclusivo para supervisores."}), 403
        return fn(*args, **kwargs)
    return wrapper


# ── POST /api/equipe/organizar ────────────────────────────────────────────

@equipe_bp.route("/organizar", methods=["POST"])
@jwt_required()
@supervisor_required
def organizar_equipe():
    claims        = get_jwt()
    supervisor_id = int(get_jwt_identity())
    empresa_id    = claims["empresa_id"]

    dados = request.get_json(silent=True)
    if not dados:
        return jsonify({"erro": "Corpo da requisição inválido."}), 400

    membro_ids  = dados.get("membro_ids", [])
    nome_equipe = dados.get("nome", None)

    if not isinstance(membro_ids, list) or len(membro_ids) == 0:
        return jsonify({"erro": "Informe pelo menos um membro em membro_ids."}), 400

    if supervisor_id in membro_ids:
        return jsonify({"erro": "O supervisor não pode ser membro da própria equipe."}), 400

    membros = (
        Usuario.query
        .filter(
            Usuario.id.in_(membro_ids),
            Usuario.empresa_id == empresa_id,
            Usuario.ativo == True,
        )
        .all()
    )

    if len(membros) != len(membro_ids):
        return jsonify({
            "erro": "Um ou mais membros não foram encontrados ou não pertencem à sua empresa."
        }), 404

    for membro_id in membro_ids:
        vinculo = (
            db.session.query(equipe_membros)
            .join(Equipe, Equipe.id == equipe_membros.c.equipe_id)
            .filter(
                equipe_membros.c.usuario_id == membro_id,
                Equipe.empresa_id == empresa_id,
                Equipe.supervisor_id != supervisor_id,
            )
            .first()
        )
        if vinculo:
            nome_membro = next((m.nome for m in membros if m.id == membro_id), str(membro_id))
            return jsonify({
                "erro": f"O colaborador {nome_membro} já pertence a outra equipe."
            }), 409

    equipe = Equipe.query.filter_by(supervisor_id=supervisor_id, empresa_id=empresa_id).first()

    # Get current members for notification purposes
    membros_anteriores = set(m.id for m in equipe.membros) if equipe else set()

    if equipe:
        equipe.membros = membros
        if nome_equipe is not None:
            equipe.nome = nome_equipe
    else:
        equipe = Equipe(
            supervisor_id=supervisor_id,
            empresa_id=empresa_id,
            nome=nome_equipe,
        )
        equipe.membros = membros
        db.session.add(equipe)

    # Send notifications to new members
    supervisor = db.session.get(Usuario, supervisor_id)
    nome_supervisor = supervisor.nome if supervisor else "Seu supervisor"
    novos_membros = [m for m in membros if m.id not in membros_anteriores]
    for membro in novos_membros:
        criar_notificacao(
            membro.id,
            f"👥 Você foi adicionado à equipe por {nome_supervisor}.",
            tipo="equipe",
            tela="equipe",
        )

    # Notifica gestores sobre a organização da equipe
    n_membros = len(membros)
    nome_equipe_str = f' "{equipe.nome}"' if equipe.nome else ""
    supervisor_obj = db.session.get(Usuario, supervisor_id)
    nome_sup = supervisor_obj.nome if supervisor_obj else "Supervisor"
    _notificar_gestores_equipe(
        empresa_id,
        f"\U0001f465 {nome_sup} organizou a equipe{nome_equipe_str} com {n_membros} membro(s).",
        tela=None,
    )

    db.session.commit()

    logger.info(
        f"Equipe organizada: supervisor_id={supervisor_id} "
        f"membros={membro_ids} empresa_id={empresa_id}"
    )

    return jsonify({
        "mensagem": "Equipe organizada com sucesso.",
        "equipe": equipe.to_dict(),
    }), 200


# ── POST /api/equipe/salvar ──────────────────────────────────────────────

@equipe_bp.route("/salvar", methods=["POST"])
@jwt_required()
@supervisor_required
def salvar_equipe():
    claims        = get_jwt()
    supervisor_id = int(get_jwt_identity())
    empresa_id    = claims["empresa_id"]

    dados = request.get_json(silent=True)
    if not dados or "membros_ids" not in dados:
        return jsonify({"erro": "Informe membros_ids."}), 400

    membro_ids = dados["membros_ids"]

    if not isinstance(membro_ids, list):
        return jsonify({"erro": "membros_ids deve ser uma lista."}), 400

    if supervisor_id in membro_ids:
        return jsonify({"erro": "O supervisor não pode ser membro da própria equipe."}), 400

    membros = (
        Usuario.query
        .filter(
            Usuario.id.in_(membro_ids),
            Usuario.empresa_id == empresa_id,
            Usuario.ativo == True,
        )
        .all()
    ) if membro_ids else []

    if len(membros) != len(membro_ids):
        return jsonify({"erro": "Um ou mais membros não foram encontrados."}), 404

    for membro_id in membro_ids:
        vinculo = (
            db.session.query(equipe_membros)
            .join(Equipe, Equipe.id == equipe_membros.c.equipe_id)
            .filter(
                equipe_membros.c.usuario_id == membro_id,
                Equipe.empresa_id == empresa_id,
                Equipe.supervisor_id != supervisor_id,
            )
            .first()
        )
        if vinculo:
            nome_membro = next((m.nome for m in membros if m.id == membro_id), str(membro_id))
            return jsonify({"erro": f"{nome_membro} já pertence a outra equipe."}), 409

    equipe = Equipe.query.filter_by(supervisor_id=supervisor_id, empresa_id=empresa_id).first()

    # Get current members for notification purposes
    membros_anteriores = set(m.id for m in equipe.membros) if equipe else set()

    if equipe:
        equipe.membros = membros
    else:
        equipe = Equipe(supervisor_id=supervisor_id, empresa_id=empresa_id)
        equipe.membros = membros
        db.session.add(equipe)

    # Send notifications to new members
    supervisor = db.session.get(Usuario, supervisor_id)
    nome_supervisor = supervisor.nome if supervisor else "Seu supervisor"
    novos_membros = [m for m in membros if m.id not in membros_anteriores]
    for membro in novos_membros:
        criar_notificacao(
            membro.id,
            f"👥 Você foi adicionado à equipe por {nome_supervisor}.",
            tipo="equipe",
            tela="equipe",
        )

    db.session.commit()

    logger.info(f"Equipe salva: supervisor_id={supervisor_id} membros={membro_ids}")

    return jsonify({
        "mensagem": "Equipe salva com sucesso!",
        "equipe": equipe.to_dict(),
    }), 200


# ── GET /api/equipe/minha ─────────────────────────────────────────────────

@equipe_bp.route("/minha", methods=["GET"])
@jwt_required()
def minha_equipe():
    claims     = get_jwt()
    usuario_id = int(get_jwt_identity())
    perfil     = claims.get("perfil")
    empresa_id = claims["empresa_id"]

    if perfil == Usuario.PERFIL_SUPERVISOR:
        equipe = Equipe.query.filter_by(
            supervisor_id=usuario_id,
            empresa_id=empresa_id,
        ).first()
    else:
        equipe = (
            Equipe.query
            .filter(Equipe.empresa_id == empresa_id)
            .join(equipe_membros, equipe_membros.c.equipe_id == Equipe.id)
            .filter(equipe_membros.c.usuario_id == usuario_id)
            .first()
        )

    if not equipe:
        return jsonify({"erro": "Você ainda não pertence a nenhuma equipe."}), 404

    return jsonify(equipe.to_dict()), 200


# ── GET /api/equipe/supervisor ────────────────────────────────────────────

@equipe_bp.route("/supervisor", methods=["GET"])
@jwt_required()
@supervisor_required
def equipe_do_supervisor():
    claims        = get_jwt()
    supervisor_id = int(get_jwt_identity())
    empresa_id    = claims["empresa_id"]

    equipe = Equipe.query.filter_by(
        supervisor_id=supervisor_id,
        empresa_id=empresa_id,
    ).first()

    ids_vinculados = set()
    for eq in Equipe.query.filter_by(empresa_id=empresa_id).all():
        ids_vinculados.add(eq.supervisor_id)
        for m in eq.membros:
            ids_vinculados.add(m.id)

    membros_da_equipe_ids = set()
    if equipe:
        membros_da_equipe_ids = {m.id for m in equipe.membros}
        ids_vinculados -= membros_da_equipe_ids

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

    return jsonify({
        "disponiveis": [u.to_dict() for u in disponiveis],
        "equipe": equipe.to_dict() if equipe else None,
    }), 200


# ── GET /api/equipe/colaboradores-disponiveis ─────────────────────────────

@equipe_bp.route("/colaboradores-disponiveis", methods=["GET"])
@jwt_required()
@supervisor_required
def colaboradores_disponiveis():
    claims     = get_jwt()
    empresa_id = claims["empresa_id"]

    ids_vinculados = set()
    for eq in Equipe.query.filter_by(empresa_id=empresa_id).all():
        ids_vinculados.add(eq.supervisor_id)
        for m in eq.membros:
            ids_vinculados.add(m.id)

    disponiveis = (
        Usuario.query
        .filter(
            Usuario.empresa_id == empresa_id,
            Usuario.ativo == True,
            Usuario.perfil == "colaborador",
            ~Usuario.id.in_(ids_vinculados) if ids_vinculados else True,
        )
        .all()
    )

    return jsonify({
        "disponiveis": [u.to_dict() for u in disponiveis],
        "total": len(disponiveis),
    }), 200


# ── GET /api/equipe/disponiveis ───────────────────────────────────────────

@equipe_bp.route("/disponiveis", methods=["GET"])
@jwt_required()
@supervisor_required
def disponiveis():
    claims     = get_jwt()
    empresa_id = claims["empresa_id"]

    ids_vinculados = set()
    for eq in Equipe.query.filter_by(empresa_id=empresa_id).all():
        ids_vinculados.add(eq.supervisor_id)
        for m in eq.membros:
            ids_vinculados.add(m.id)

    query = Usuario.query.filter(
        Usuario.empresa_id == empresa_id,
        Usuario.ativo == True,
        Usuario.perfil == "colaborador",
    )
    if ids_vinculados:
        query = query.filter(~Usuario.id.in_(ids_vinculados))

    usuarios = query.all()

    return jsonify({
        "disponiveis": [
            {"id": u.id, "nome": u.nome, "foto_perfil": u.foto_perfil}
            for u in usuarios
        ],
    }), 200


# ── GET /api/equipe/buscar?q= ────────────────────────────────────────────

@equipe_bp.route("/buscar", methods=["GET"])
@jwt_required()
@supervisor_required
def buscar_colaboradores():
    claims     = get_jwt()
    empresa_id = claims["empresa_id"]
    q          = request.args.get("q", "").strip()

    ids_vinculados = set()
    for eq in Equipe.query.filter_by(empresa_id=empresa_id).all():
        ids_vinculados.add(eq.supervisor_id)
        for m in eq.membros:
            ids_vinculados.add(m.id)

    query = Usuario.query.filter(
        Usuario.empresa_id == empresa_id,
        Usuario.ativo == True,
        Usuario.perfil == "colaborador",
    )

    if ids_vinculados:
        query = query.filter(~Usuario.id.in_(ids_vinculados))

    if q:
        query = query.filter(Usuario.nome.ilike(f"%{q}%"))

    resultados = query.limit(20).all()

    return jsonify({
        "resultados": [
            {"id": u.id, "nome": u.nome, "foto_perfil": u.foto_perfil}
            for u in resultados
        ],
    }), 200


# ── POST /api/equipe/adicionar ────────────────────────────────────────────

@equipe_bp.route("/adicionar", methods=["POST"])
@jwt_required()
@supervisor_required
def adicionar_membro():
    claims        = get_jwt()
    supervisor_id = int(get_jwt_identity())
    empresa_id    = claims["empresa_id"]

    dados = request.get_json(silent=True)
    if not dados or "colaborador_id" not in dados:
        return jsonify({"erro": "Informe colaborador_id."}), 400

    colaborador_id = dados["colaborador_id"]

    if colaborador_id == supervisor_id:
        return jsonify({"erro": "O supervisor não pode ser membro da própria equipe."}), 400

    colaborador = Usuario.query.filter_by(
        id=colaborador_id,
        empresa_id=empresa_id,
        ativo=True,
        perfil="colaborador",
    ).first()

    if not colaborador:
        return jsonify({"erro": "Colaborador não encontrado."}), 404

    vinculo = (
        db.session.query(equipe_membros)
        .join(Equipe, Equipe.id == equipe_membros.c.equipe_id)
        .filter(
            equipe_membros.c.usuario_id == colaborador_id,
            Equipe.empresa_id == empresa_id,
        )
        .first()
    )
    if vinculo:
        return jsonify({"erro": "Colaborador já pertence a uma equipe."}), 409

    equipe = Equipe.query.filter_by(supervisor_id=supervisor_id, empresa_id=empresa_id).first()
    if not equipe:
        equipe = Equipe(supervisor_id=supervisor_id, empresa_id=empresa_id)
        db.session.add(equipe)
        db.session.flush()

    equipe.membros.append(colaborador)

    # ── Notificação para o colaborador ─────────────────────────────────────
    supervisor = db.session.get(Usuario, supervisor_id)
    nome_supervisor = supervisor.nome if supervisor else "Seu supervisor"
    criar_notificacao(
        colaborador_id,
        f"👥 Você foi adicionado à equipe por {nome_supervisor}.",
        tipo="equipe",
        tela="equipe",
    )

    db.session.commit()

    logger.info(f"Membro adicionado: colaborador_id={colaborador_id} equipe_id={equipe.id}")

    return jsonify({
        "mensagem": f"{colaborador.nome} adicionado à equipe.",
        "equipe": equipe.to_dict(),
    }), 200


# ── POST /api/equipe/remover ─────────────────────────────────────────────

@equipe_bp.route("/remover", methods=["POST"])
@jwt_required()
@supervisor_required
def remover_membro():
    claims        = get_jwt()
    supervisor_id = int(get_jwt_identity())
    empresa_id    = claims["empresa_id"]

    dados = request.get_json(silent=True)
    if not dados or "colaborador_id" not in dados:
        return jsonify({"erro": "Informe colaborador_id."}), 400

    colaborador_id = dados["colaborador_id"]

    equipe = Equipe.query.filter_by(supervisor_id=supervisor_id, empresa_id=empresa_id).first()
    if not equipe:
        return jsonify({"erro": "Você não possui uma equipe."}), 404

    colaborador = next((m for m in equipe.membros if m.id == colaborador_id), None)
    if not colaborador:
        return jsonify({"erro": "Colaborador não faz parte da sua equipe."}), 404

    equipe.membros.remove(colaborador)

    # ── Notificação para o colaborador ─────────────────────────────────────
    supervisor = db.session.get(Usuario, supervisor_id)
    nome_supervisor = supervisor.nome if supervisor else "Seu supervisor"
    criar_notificacao(
        colaborador_id,
        f"⚠️ Você foi removido da equipe por {nome_supervisor}.",
        tipo="equipe",
        tela="equipe",
    )

    db.session.commit()

    logger.info(f"Membro removido: colaborador_id={colaborador_id} equipe_id={equipe.id}")

    return jsonify({
        "mensagem": f"{colaborador.nome} removido da equipe.",
        "equipe": equipe.to_dict(),
    }), 200
