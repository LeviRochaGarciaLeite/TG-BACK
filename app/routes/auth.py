from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token
import bcrypt
from ..models import db, Usuario, Empresa

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['POST'])
def login():
    dados = request.get_json()

    if not dados or not dados.get('cpf') or not dados.get('senha'):
        return jsonify({"erro": "CPF e senha corporativa são obrigatórios"}), 400

    cpf_informado = ''.join(filter(str.isdigit, dados.get('cpf', '')))
    senha_informada = dados.get('senha').encode('utf-8')

    usuario = Usuario.query.filter_by(cpf=cpf_informado).first()

    if usuario and bcrypt.checkpw(senha_informada, usuario.senha_hash.encode('utf-8')):
        claims_adicionais = {
            "perfil": usuario.perfil,
            "empresa_id": usuario.empresa_id
        }

        token_acesso = create_access_token(
            identity=str(usuario.id),
            additional_claims=claims_adicionais
        )

        return jsonify({
            "token": token_acesso,
            "nome": usuario.nome,
            "perfil": usuario.perfil
        }), 200

    return jsonify({"erro": "Credenciais inválidas"}), 401


@auth_bp.route('/cadastro', methods=['POST'])
def cadastro():
    dados = request.get_json()

    if not dados:
        return jsonify({"erro": "Dados não enviados"}), 400

    cpf = ''.join(filter(str.isdigit, (dados.get('cpf') or '').strip()))
    senha = dados.get('senha') or ''
    confirmar_senha = dados.get('confirmar_senha') or ''

    if not cpf or not senha or not confirmar_senha:
        return jsonify({"erro": "CPF, senha e confirmação de senha são obrigatórios"}), 400

    if len(cpf) != 11:
        return jsonify({"erro": "CPF inválido"}), 400

    if senha != confirmar_senha:
        return jsonify({"erro": "As senhas não coincidem"}), 400

    usuario_existente = Usuario.query.filter_by(cpf=cpf).first()
    if usuario_existente:
        return jsonify({"erro": "Já existe um usuário cadastrado com esse CPF"}), 409

    empresa = Empresa.query.first()
    if not empresa:
        empresa = Empresa(
            nome_fantasia="Nexus",
            cnpj="00000000000000"
        )
        db.session.add(empresa)
        db.session.commit()

    senha_hash = bcrypt.hashpw(
        senha.encode('utf-8'),
        bcrypt.gensalt()
    ).decode('utf-8')

    novo_usuario = Usuario(
        empresa_id=empresa.id,
        nome=f"Usuário {cpf[-4:]}",
        cpf=cpf,
        senha_hash=senha_hash,
        perfil="colaborador"
    )

    db.session.add(novo_usuario)
    db.session.commit()

    return jsonify({
        "mensagem": "Usuário cadastrado com sucesso"
    }), 201