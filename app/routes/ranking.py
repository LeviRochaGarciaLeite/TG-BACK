"""
Rotas de Ranking — /api/ranking

Endpoints:
  GET /funcionarios     — Top 3 funcionários com maior pontuação líquida
  GET /melhor-equipe    — Equipe com maior pontuação total (supervisor + membros)
"""

import logging
from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required, get_jwt

from ..models import db, Usuario, Equipe

ranking_bp = Blueprint("ranking", __name__)
logger = logging.getLogger(__name__)


def _pontuacao_liquida(usuario: Usuario) -> int:
    """Retorna pontos positivos menos pontos negativos."""
    return (usuario.pontos_positivos or 0) - (usuario.pontos_negativos or 0)


# ── GET /api/ranking/funcionarios ─────────────────────────────────────────

@ranking_bp.route("/funcionarios", methods=["GET"])
@jwt_required()
def ranking_funcionarios():
    """
    Retorna os top 3 funcionários (colaboradores) com maior pontuação líquida
    da empresa do usuário autenticado, ordenados do maior para o menor.
    """
    claims = get_jwt()
    empresa_id = claims.get("empresa_id")

    colaboradores = (
        Usuario.query
        .filter_by(empresa_id=empresa_id, ativo=True)
        .filter(Usuario.perfil.notin_(["gestor", "admin"]))
        .all()
    )

    ordenados = sorted(colaboradores, key=_pontuacao_liquida, reverse=True)[:3]

    return jsonify({
        "ranking": [u.to_dict() for u in ordenados],
        "total": len(ordenados),
    }), 200


# ── GET /api/ranking/melhor-equipe ────────────────────────────────────────

@ranking_bp.route("/melhor-equipe", methods=["GET"])
@jwt_required()
def ranking_melhor_equipe():
    """
    Retorna a equipe com maior pontuação total (soma das pontuações líquidas
    de todos os membros + supervisor) dentro da empresa do usuário autenticado.

    Resposta:
      {
        "id": int,
        "nome": str | null,
        "pontuacao_total": int,
        "supervisor": { ...usuario },
        "membros": [ { ...usuario }, ... ]
      }
    """
    claims = get_jwt()
    empresa_id = claims.get("empresa_id")

    equipes = (
        Equipe.query
        .filter_by(empresa_id=empresa_id)
        .all()
    )

    if not equipes:
        return jsonify({"erro": "Nenhuma equipe encontrada."}), 404

    def pontuacao_equipe(equipe: Equipe) -> int:
        total = 0
        if equipe.supervisor:
            total += _pontuacao_liquida(equipe.supervisor)
        for membro in equipe.membros:
            total += _pontuacao_liquida(membro)
        return total

    melhor = max(equipes, key=pontuacao_equipe)

    return jsonify({
        "id": melhor.id,
        "nome": melhor.nome,
        "pontuacao_total": pontuacao_equipe(melhor),
        "supervisor": melhor.supervisor.to_dict() if melhor.supervisor else None,
        "membros": [m.to_dict() for m in melhor.membros],
    }), 200
