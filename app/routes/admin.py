from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from ..models import db, Usuario

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/usuarios', methods=['GET'])
@jwt_required()
def listar_usuarios():
    """Retorna todos os usuários cadastrados."""
    usuarios = Usuario.query.all()
    return jsonify([u.to_dict() for u in usuarios]), 200


@admin_bp.route('/config', methods=['GET'])
def config():
    return jsonify({"mensagem": "Configurações de administrador (placeholder)"}), 200
