"""
Rotas de autenticação — /api/auth
Endpoints: POST /login, POST /cadastro, PUT /perfil,
           POST /esqueci-senha, POST /reset-senha
"""

import re
import logging
import bcrypt
import smtplib
import os
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

from ..models import db, Usuario, Empresa
from .notificacoes import criar_notificacao

auth_bp = Blueprint("auth", __name__)
logger = logging.getLogger(__name__)


# ── Helpers de token seguro ─────────────────────────────────────────────────

def _gerar_token_reset(email: str) -> str:
    s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    return s.dumps(email, salt="reset-senha")


def _verificar_token_reset(token: str, expiracao: int = 3600):
    """Retorna o e-mail embutido no token ou lança exceção se inválido/expirado."""
    s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    return s.loads(token, salt="reset-senha", max_age=expiracao)


# ── Validações ─────────────────────────────────────────────────────────────

def _somente_digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor or "")


def _cpf_valido(cpf: str) -> bool:
    cpf = _somente_digitos(cpf)
    if len(cpf) != 11 or len(set(cpf)) == 1:
        return False
    soma = sum(int(cpf[i]) * (10 - i) for i in range(9))
    d1 = (soma * 10 % 11) % 10
    if d1 != int(cpf[9]):
        return False
    soma = sum(int(cpf[i]) * (11 - i) for i in range(10))
    d2 = (soma * 10 % 11) % 10
    return d2 == int(cpf[10])


def _enviar_email(destinatario: str, assunto: str, corpo: str) -> None:
    """Envia e-mail via Gmail SMTP. Lança Exception se falhar."""
    remetente = os.getenv("EMAIL_REMETENTE")
    senha_app = os.getenv("EMAIL_SENHA")

    if not remetente or not senha_app:
        raise RuntimeError(
            "Variáveis EMAIL_REMETENTE e/ou EMAIL_SENHA não configuradas no .env"
        )

    msg = MIMEMultipart()
    msg["From"] = remetente
    msg["To"] = destinatario
    msg["Subject"] = assunto
    msg.attach(MIMEText(corpo, "plain", "utf-8"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(remetente, senha_app)
        server.send_message(msg)

    logger.info(f"E-mail enviado para {destinatario}")


# ── Login ──────────────────────────────────────────────────────────────────

@auth_bp.route("/login", methods=["POST"])
def login():
    dados = request.get_json(silent=True)
    if not dados:
        return jsonify({"erro": "Requisição inválida. Envie JSON."}), 400

    cpf_raw   = dados.get("cpf", "")
    senha_raw = dados.get("senha", "")

    if not cpf_raw or not senha_raw:
        return jsonify({"erro": "CPF e senha são obrigatórios."}), 400

    cpf = _somente_digitos(cpf_raw)
    usuario = Usuario.query.filter_by(cpf=cpf).first()

    credenciais_validas = (
        usuario is not None
        and usuario.ativo
        and bcrypt.checkpw(senha_raw.encode("utf-8"), usuario.senha_hash.encode("utf-8"))
    )

    if not credenciais_validas:
        logger.warning(f"Login falhou para CPF={cpf} IP={request.remote_addr}")
        return jsonify({"erro": "CPF ou senha incorretos."}), 401

    token = create_access_token(
        identity=str(usuario.id),
        additional_claims={
            "perfil":     usuario.perfil,
            "empresa_id": usuario.empresa_id,
        },
    )

    logger.info(f"Login bem-sucedido: usuario_id={usuario.id} perfil={usuario.perfil}")

    return jsonify({
        "token":           token,
        "nome":            usuario.nome,
        "perfil":          usuario.perfil,
        "foto_perfil":     usuario.foto_perfil,
        "cidade":          usuario.cidade,
        "celular":         usuario.celular,
        "data_nascimento": usuario.data_nascimento.isoformat() if usuario.data_nascimento else None,
    }), 200


# ── Cadastro ───────────────────────────────────────────────────────────────

@auth_bp.route("/cadastro", methods=["POST"])
def cadastro():
    dados = request.get_json(silent=True)
    if not dados:
        return jsonify({"erro": "Requisição inválida. Envie JSON."}), 400

    cpf_raw         = dados.get("cpf", "")
    senha           = dados.get("senha", "")
    confirmar_senha = dados.get("confirmar_senha", "")
    nascimento_str  = dados.get("data_nascimento")
    cidade          = dados.get("cidade", "")
    celular         = dados.get("celular", "")
    email           = dados.get("email", "")

    cpf = _somente_digitos(cpf_raw)

    if not _cpf_valido(cpf):
        return jsonify({"erro": "CPF inválido."}), 400
    if len(senha) < 6:
        return jsonify({"erro": "A senha deve ter no mínimo 6 caracteres."}), 400
    if senha != confirmar_senha:
        return jsonify({"erro": "As senhas não coincidem."}), 400
    if Usuario.query.filter_by(cpf=cpf).first():
        return jsonify({"erro": "CPF já cadastrado."}), 409

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

    # ── bcrypt em todos os cadastros ───────────────────────────────────────
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
        email=email,
    )

    db.session.add(novo_usuario)
    db.session.commit()

    logger.info(f"Novo usuário cadastrado: cpf={cpf} empresa_id={empresa.id}")
    return jsonify({"mensagem": "Usuário cadastrado com sucesso!"}), 201


# ── Atualizar perfil ───────────────────────────────────────────────────────

@auth_bp.route("/perfil", methods=["PUT"])
@jwt_required()
def atualizar_perfil():
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

    db.session.commit()

    return jsonify({
        "mensagem":    "Perfil atualizado com sucesso!",
        "nome":        usuario.nome,
        "foto_perfil": usuario.foto_perfil,
        "cidade":      usuario.cidade,
        "celular":     usuario.celular,
    }), 200


# ── Esqueci a senha ────────────────────────────────────────────────────────

@auth_bp.route("/esqueci-senha", methods=["POST"])
def esqueci_senha():
    dados = request.get_json(silent=True)
    if not dados:
        return jsonify({"erro": "Requisição inválida. Envie JSON."}), 400

    email_informado = (dados.get("email") or "").strip().lower()

    if not email_informado:
        return jsonify({"erro": "Informe o e-mail cadastrado."}), 400

    # Resposta genérica — não revela se o e-mail existe na base
    usuario = Usuario.query.filter_by(email=email_informado).first()

    if usuario:
        try:
            token = _gerar_token_reset(usuario.email)

            # Em produção, troque localhost pela URL real do front-end
            frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
            link = f"{frontend_url}/reset-password?token={token}"

            corpo = (
                f"Olá {usuario.nome},\n\n"
                "Recebemos um pedido para redefinir sua senha no sistema Nexus.\n\n"
                f"Clique no link abaixo para criar uma nova senha (válido por 1 hora):\n{link}\n\n"
                "Se você não solicitou isso, ignore este e-mail — sua senha permanece a mesma.\n\n"
                "Equipe Nexus"
            )

            _enviar_email(usuario.email, "Recuperação de Senha — NEXUS", corpo)

        except RuntimeError as e:
            # Variáveis de ambiente ausentes
            logger.error(f"Configuração de e-mail ausente: {e}")
            return jsonify({"erro": "Serviço de e-mail não configurado no servidor."}), 500
        except Exception as e:
            logger.error(f"Falha ao enviar e-mail de recuperação: {e}")
            return jsonify({"erro": "Falha técnica ao enviar e-mail. Tente novamente."}), 500

    return jsonify({
        "mensagem": "Se o e-mail constar em nossa base, você receberá as instruções em instantes."
    }), 200


# ── Reset de senha ─────────────────────────────────────────────────────────

@auth_bp.route("/reset-senha", methods=["POST"])
def reset_senha():
    dados = request.get_json(silent=True)
    if not dados:
        return jsonify({"erro": "Requisição inválida. Envie JSON."}), 400

    token      = dados.get("token", "")
    nova_senha = dados.get("nova_senha", "")

    if not token or not nova_senha:
        return jsonify({"erro": "Dados insuficientes."}), 400

    if len(nova_senha) < 6:
        return jsonify({"erro": "A senha deve ter no mínimo 6 caracteres."}), 400

    try:
        email = _verificar_token_reset(token)
    except SignatureExpired:
        return jsonify({"erro": "Link de recuperação expirado. Solicite um novo."}), 400
    except BadSignature:
        return jsonify({"erro": "Link de recuperação inválido ou corrompido."}), 400

    usuario = Usuario.query.filter_by(email=email).first()
    if not usuario:
        return jsonify({"erro": "Usuário não encontrado."}), 404

    # ── bcrypt — mesma lib usada no login ──────────────────────────────────
    usuario.senha_hash = bcrypt.hashpw(
        nova_senha.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")

    # ── Notifica o próprio usuário e os gestores da empresa ───────────────
    criar_notificacao(
        usuario.id,
        "🔐 Sua senha foi alterada com sucesso.",
        tipo="senha",
        tela=None,
    )
    gestores = Usuario.query.filter(
        Usuario.empresa_id == usuario.empresa_id,
        Usuario.perfil.in_(["gestor", "admin"]),
        Usuario.ativo == True,
    ).all()
    for gestor in gestores:
        criar_notificacao(
            gestor.id,
            f"🔑 {usuario.nome} alterou a senha.",
            tipo="senha",
            tela=None,
        )

    db.session.commit()
    logger.info(f"Senha redefinida para usuario_id={usuario.id}")

    return jsonify({"mensagem": "Senha alterada com sucesso!"}), 200
