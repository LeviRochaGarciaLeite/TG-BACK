"""
Rotas de autenticação — /api/auth
<<<<<<< HEAD
Endpoints: POST /login, POST /cadastro, PUT /perfil
=======
Endpoints: POST /login, POST /cadastro
>>>>>>> 7c764601258a759fe80901be7c9a33233464c5cb
"""

import re
import logging
import bcrypt
from flask import Blueprint, request, jsonify, current_app
<<<<<<< HEAD
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
=======
from flask_jwt_extended import create_access_token
>>>>>>> 7c764601258a759fe80901be7c9a33233464c5cb

from ..models import db, Usuario, Empresa

auth_bp = Blueprint("auth", __name__)
logger = logging.getLogger(__name__)


# ── Validações ─────────────────────────────────────────────────────────────

def _somente_digitos(valor: str) -> str:
    """Remove qualquer caractere não-numérico (máscaras de CPF, etc.)."""
    return re.sub(r"\D", "", valor or "")


def _cpf_valido(cpf: str) -> bool:
    """
    Valida dígitos verificadores do CPF.
    Rejeita sequências triviais como '00000000000'.
    """
    cpf = _somente_digitos(cpf)
    if len(cpf) != 11 or len(set(cpf)) == 1:
        return False

    # Primeiro dígito verificador
    soma = sum(int(cpf[i]) * (10 - i) for i in range(9))
    d1 = (soma * 10 % 11) % 10
    if d1 != int(cpf[9]):
        return False

    # Segundo dígito verificador
    soma = sum(int(cpf[i]) * (11 - i) for i in range(10))
    d2 = (soma * 10 % 11) % 10
    return d2 == int(cpf[10])


# ── Login ──────────────────────────────────────────────────────────────────

@auth_bp.route("/login", methods=["POST"])
def login():
    """
    Autentica o usuário com CPF e senha.
    Retorna JWT com perfil e empresa_id nos claims adicionais.
    """
    dados = request.get_json(silent=True)

    if not dados:
        return jsonify({"erro": "Requisição inválida. Envie JSON."}), 400

    cpf_raw   = dados.get("cpf", "")
    senha_raw = dados.get("senha", "")

    if not cpf_raw or not senha_raw:
        return jsonify({"erro": "CPF e senha são obrigatórios."}), 400

    cpf = _somente_digitos(cpf_raw)

    # Busca o usuário — resposta genérica para não revelar se o CPF existe
    usuario = Usuario.query.filter_by(cpf=cpf).first()

    credenciais_validas = (
        usuario is not None
        and usuario.ativo
        and bcrypt.checkpw(senha_raw.encode("utf-8"), usuario.senha_hash.encode("utf-8"))
    )

    if not credenciais_validas:
        logger.warning(f"Tentativa de login falhou para CPF={cpf} IP={request.remote_addr}")
        return jsonify({"erro": "CPF ou senha incorretos."}), 401

    # Claims extras no token — evitam consultas ao banco a cada request protegido
    token = create_access_token(
        identity=str(usuario.id),
        additional_claims={
            "perfil":     usuario.perfil,
            "empresa_id": usuario.empresa_id,
        },
    )

    logger.info(f"Login bem-sucedido: usuario_id={usuario.id} perfil={usuario.perfil}")

    return jsonify({
        "token":  token,
        "nome":   usuario.nome,
        "perfil": usuario.perfil,
<<<<<<< HEAD
        "foto_perfil": usuario.foto_perfil,
=======
>>>>>>> 7c764601258a759fe80901be7c9a33233464c5cb
    }), 200


# ── Cadastro ───────────────────────────────────────────────────────────────

@auth_bp.route("/cadastro", methods=["POST"])
def cadastro():
    """
    Cria um novo usuário.
    Requer CPF válido, senha mínima de 6 chars e confirmação de senha.
    Associa o usuário a uma empresa padrão (id=1) para ambiente de desenvolvimento.
    """
    dados = request.get_json(silent=True)

    if not dados:
        return jsonify({"erro": "Requisição inválida. Envie JSON."}), 400

    cpf_raw          = dados.get("cpf", "")
    senha            = dados.get("senha", "")
    confirmar_senha  = dados.get("confirmar_senha", "")

    # ── Validações de entrada ──────────────────────────────────────────────
    cpf = _somente_digitos(cpf_raw)

    if not _cpf_valido(cpf):
        return jsonify({"erro": "CPF inválido."}), 400

    if len(senha) < 6:
        return jsonify({"erro": "A senha deve ter no mínimo 6 caracteres."}), 400

    if senha != confirmar_senha:
        return jsonify({"erro": "As senhas não coincidem."}), 400

    # ── Verifica unicidade ─────────────────────────────────────────────────
    if Usuario.query.filter_by(cpf=cpf).first():
        return jsonify({"erro": "CPF já cadastrado."}), 409

    # ── Empresa padrão para desenvolvimento ───────────────────────────────
    # Em produção, o cadastro deve receber empresa_id ou um código de convite.
    empresa = Empresa.query.first()
    if not empresa:
<<<<<<< HEAD
        emp
=======
        empresa = Empresa(nome_fantasia="Nexus Desenvolvimento", cnpj="00000000000100")
        db.session.add(empresa)
        db.session.flush()  # Gera o id sem commitar

    # ── Hash da senha ──────────────────────────────────────────────────────
    senha_hash = bcrypt.hashpw(senha.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    novo_usuario = Usuario(
        nome=f"Usuário {cpf[-4:]}",  # Nome provisório; o usuário pode editar depois
        cpf=cpf,
        senha_hash=senha_hash,
        empresa_id=empresa.id,
        perfil="colaborador",
    )

    db.session.add(novo_usuario)
    db.session.commit()

    logger.info(f"Novo usuário cadastrado: cpf={cpf} empresa_id={empresa.id}")

    return jsonify({"mensagem": "Usuário cadastrado com sucesso!"}), 201
>>>>>>> 7c764601258a759fe80901be7c9a33233464c5cb
