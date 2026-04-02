from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.models import db, RegistroPonto
from datetime import datetime

# Criação do Blueprint para as rotas de ponto
ponto_bp = Blueprint('ponto', __name__)

@ponto_bp.route('/registrar', methods=['POST'])
@jwt_required() # <--- O SEGURANÇA DA PORTA! Exige o Token JWT no cabeçalho
def registrar_ponto():
    # 1. Quem está batendo o ponto? O JWT extrai o ID do usuário de forma segura
    usuario_id = get_jwt_identity()
    
    # 2. O que ele está enviando? (entrada, pausa_inicio, pausa_fim ou saida)
    dados = request.get_json()
    if not dados or not dados.get('tipo_registro'):
         return jsonify({"erro": "O tipo_registro é obrigatório"}), 400
         
    tipo = dados.get('tipo_registro')
    
    # Validação de segurança para aceitar apenas os 4 tipos definidos na sua regra de negócio
    tipos_validos = ['entrada', 'pausa_inicio', 'pausa_fim', 'saida']
    if tipo not in tipos_validos:
        return jsonify({"erro": f"Tipo inválido. Escolha entre: {', '.join(tipos_validos)}"}), 400
        
    # 3. Pegando dados extras de auditoria (IP e Navegador/Dispositivo)
    ip_cliente = request.remote_addr
    dispositivo_info = request.headers.get('User-Agent', 'Desconhecido')
    
    # 4. Criando e salvando o registro no banco de dados
    novo_registro = RegistroPonto(
        usuario_id=usuario_id,
        tipo_registro=tipo,
        ip_origem=ip_cliente,
        dispositivo=dispositivo_info
        # O timestamp já é gerado automaticamente pelo default=datetime.utcnow no models.py
    )
    
    db.session.add(novo_registro)
    db.session.commit()
    
    return jsonify({
        "mensagem": f"Ponto de {tipo} registrado com sucesso!",
        "horario_servidor": datetime.utcnow().isoformat()
    }), 201

    # ... (código anterior da rota /registrar) ...

@ponto_bp.route('/historico', methods=['GET'])
@jwt_required()
def historico_ponto():
    # 1. Descobre quem é o usuário logado
    usuario_id = get_jwt_identity()
    
    # 2. Busca todos os registros desse usuário no banco, ordenados do mais recente pro mais antigo
    registros = RegistroPonto.query.filter_by(usuario_id=usuario_id).order_by(RegistroPonto.timestamp.desc()).all()
    
    # 3. Formata os dados para enviar como JSON
    lista_registros = []
    for reg in registros:
        lista_registros.append({
            "id": reg.id,
            "tipo": reg.tipo_registro,
            "horario": reg.timestamp.isoformat(),
            "status": reg.status
        })
        
    return jsonify({
        "total_registros": len(lista_registros),
        "historico": lista_registros
    }), 200

# ... (código anterior) ...

@ponto_bp.route('/solicitar-ajuste', methods=['POST'])
@jwt_required()
def solicitar_ajuste():
    # 1. Identifica o funcionário logado
    usuario_id = get_jwt_identity()
    
    # 2. Pega os dados que o funcionário enviou no app
    dados = request.get_json()
    tipo = dados.get('tipo_registro')
    horario_str = dados.get('horario')
    motivo = dados.get('motivo', 'Esqueci de registrar no horário correto.')
    
    if not tipo or not horario_str:
        return jsonify({"erro": "tipo_registro e horario são obrigatórios"}), 400
        
    try:
        horario_ajuste = datetime.fromisoformat(horario_str)
    except ValueError:
        return jsonify({"erro": "Formato de data inválido. Use ISO 8601"}), 400
        
    # 3. Salva no banco com o status de PENDENTE
    novo_registro = RegistroPonto(
        usuario_id=usuario_id,
        tipo_registro=tipo,
        timestamp=horario_ajuste,
        ip_origem=request.remote_addr,
        dispositivo=f"Solicitação via App | Motivo: {motivo}",
        status="pendente_ajuste" # <--- O pulo do gato!
    )
    
    db.session.add(novo_registro)
    db.session.commit()
    
    return jsonify({
        "mensagem": "Solicitação de ajuste enviada para o gestor com sucesso!",
        "status": "pendente_ajuste"
    }), 201

    # No app/routes/ponto.py
@ponto_bp.route('/status-atual', methods=['GET'])
@jwt_required()
def status_atual():
    user_id = get_jwt_identity()
    # Busca a última batida de hoje
    ultimo = RegistroPonto.query.filter_by(usuario_id=user_id).order_by(RegistroPonto.timestamp.desc()).first()
    
    if not ultimo or ultimo.tipo_registro == 'saida':
        return jsonify({"status": "desconectado"}), 200
        
    return jsonify({
        "status": "conectado",
        "ultimo_tipo": ultimo.tipo_registro,
        "segundos_desde_inicio": 0 # Aqui você poderia calcular a diferença de tempo
    }), 200