from flask import Blueprint, jsonify

admin_bp = Blueprint('admin', __name__)

@admin_bp.route('/config', methods=['GET'])
def config():
    return jsonify({"mensagem": "Configurações de administrador (placeholder)"}), 200
