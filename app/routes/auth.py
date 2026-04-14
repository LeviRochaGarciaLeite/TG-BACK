"""
Rotas de autenticação — /api/auth
Endpoints: POST /login, POST /cadastro, PUT /perfil
"""

import re
import logging
import bcrypt
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity

from ..models import db, Usuario, Empresa
from datetime import datetime

import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from werkzeug.security import generate_password_hash

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
        "foto_perfil": usuario.foto_perfil,
        "cidade": usuario.cidade, 
        "celular": usuario.celular, 
        "data_nascimento": usuario.data_nascimento.isoformat() if usuario.data_nascimento else None 
    }), 200


# ── Cadastro ───────────────────────────────────────────────────────────────

@auth_bp.route("/cadastro", methods=["POST"])
def cadastro():
    dados = request.get_json(silent=True)
    if not dados:
        return jsonify({"erro": "Requisição inválida. Envie JSON."}), 400

    cpf_raw          = dados.get("cpf", "")
    senha            = dados.get("senha", "")
    confirmar_senha  = dados.get("confirmar_senha", "")
    
    # Novos dados
    nascimento_str   = dados.get("data_nascimento")
    cidade           = dados.get("cidade", "")
    celular          = dados.get("celular", "")
    email            = dados.get("email", "")

    cpf = _somente_digitos(cpf_raw)

    if not _cpf_valido(cpf):
        return jsonify({"erro": "CPF inválido."}), 400
    if len(senha) < 6:
        return jsonify({"erro": "A senha deve ter no mínimo 6 caracteres."}), 400
    if senha != confirmar_senha:
        return jsonify({"erro": "As senhas não coincidem."}), 400
    if Usuario.query.filter_by(cpf=cpf).first():
        return jsonify({"erro": "CPF já cadastrado."}), 409

    # Convertendo a data de nascimento
    data_nasc_obj = None
    if nascimento_str:
        try:
            data_nasc_obj = datetime.strptime(nascimento_str, "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"erro": "Data de nascimento inválida."}), 400

    empresa = Empresa.query.first()
    if not empresa:
        empresa = Empresa(nome_fantasia="Nexus Desenvolvimento", cnpj="00000000000100")
        db.session.add(empresa)
        db.session.flush() 

    senha_hash = bcrypt.hashpw(senha.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    novo_usuario = Usuario(
        nome=f"Usuário {cpf[-4:]}",
        cpf=cpf,
        senha_hash=senha_hash,
        empresa_id=empresa.id,
        perfil="colaborador",
        data_nascimento=data_nasc_obj,
        cidade=cidade,
        celular=celular,
        email=email
    )

    db.session.add(novo_usuario)
    db.session.commit()

    return jsonify({"mensagem": "Usuário cadastrado com sucesso!"}), 201

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


# ── Atualizar perfil ──────────────────────────────────────────────────────

@auth_bp.route("/perfil", methods=["PUT"])
@jwt_required()
def atualizar_perfil():
    """
    Permite ao próprio usuário atualizar seu nome e/ou foto de perfil.
    """
    usuario_id = get_jwt_identity()
    usuario = db.session.get(Usuario, int(usuario_id))

    if not usuario:
        return jsonify({"erro": "Usuário não encontrado."}), 404

    dados = request.get_json(silent=True)
    if not dados:
        return jsonify({"erro": "Requisição inválida. Envie JSON."}), 400

    if "nome" in dados:
        nome = dados["nome"].strip()
        if not nome:
            return jsonify({"erro": "O nome não pode ser vazio."}), 400
        usuario.nome = nome

    if "foto_perfil" in dados:
        usuario.foto_perfil = dados["foto_perfil"]

    # ... final da sua função atualizar_perfil ...
    db.session.commit()

    return jsonify({
        "mensagem": "Perfil atualizado com sucesso!",
        "nome": usuario.nome,
        "foto_perfil": usuario.foto_perfil,
        "cidade": usuario.cidade,
        "celular": usuario.celular
    }), 200

# 👇 A ROTA TEM QUE FICAR AQUI, TOTALMENTE PARA A ESQUERDA! 👇
@auth_bp.route("/esqueci-senha", methods=["POST"])
def esqueci_senha():
    dados = request.get_json(silent=True)
    email_informado = dados.get("email")

    if not email_informado:
        return jsonify({"erro": "Informe o e-mail cadastrado."}), 400

    # Busca o usuário (funciona para qualquer perfil: colaborador, gestor ou supervisor)
    usuario = Usuario.query.filter_by(email=email_informado).first()

    if usuario:
        remetente = os.getenv("EMAIL_REMETENTE")
        senha_app = os.getenv("EMAIL_SENHA")
        
        # No def esqueci_senha():
        link = f"http://localhost:5173/reset-password?token=tk_{usuario.id}"

        # Configuração do e-mail
        msg = MIMEMultipart()
        msg['From'] = remetente
        msg['To'] = usuario.email
        msg['Subject'] = "Recuperacao de Senha - NEXUS"

        corpo = f"Olá {usuario.nome},\n\nRecebemos um pedido para redefinir sua senha.\nClique no link abaixo:\n{link}"
        msg.attach(MIMEText(corpo, 'plain'))

        try:
            # Conexão com o servidor do Gmail
            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls() 
            server.login(remetente, senha_app)
            server.send_message(msg)
            server.quit()
            print(f"✅ E-mail enviado para: {usuario.email}")
        except Exception as e:
            print(f"❌ Erro no disparo: {e}")
            return jsonify({"erro": "Falha técnica ao enviar e-mail."}), 500


    return jsonify({"mensagem": "Se o e-mail constar em nossa base, você receberá as instruções em instantes."}), 200

@auth_bp.route("/reset-senha", methods=["POST"])
def reset_senha():
    dados = request.get_json()
    token = dados.get("token")  # O token que vem do link (ex: tk_1)
    nova_senha = dados.get("nova_senha")

    if not token or not nova_senha:
        return jsonify({"erro": "Dados insuficientes."}), 400

    try:
        # Extrai o ID: se o token for "tk_1", o split('_')[1] pega o "1"
        user_id_str = token.split('_')[1]
        user_id = int(user_id_str)
        
        usuario = Usuario.query.get(user_id)
        
        if usuario:
            # Gera o novo hash da senha (segurança!)
            usuario.senha_hash = generate_password_hash(nova_senha)
            db.session.commit()
            return jsonify({"mensagem": "Senha alterada com sucesso!"}), 200
        
        return jsonify({"erro": "Usuário não encontrado."}), 404
    except (IndexError, ValueError):
        return jsonify({"erro": "Link de recuperação inválido ou corrompido."}), 400
    except Exception as e:
        print(f"Erro no reset: {e}")
        return jsonify({"erro": "Erro interno no servidor."}), 500