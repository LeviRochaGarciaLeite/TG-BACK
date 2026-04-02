from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt
from app.models import db, Usuario, RegistroPonto
from datetime import datetime


# Criação do Blueprint para as rotas do painel gerencial
gestor_bp = Blueprint('gestor', __name__)

@gestor_bp.route('/equipe', methods=['GET'])
@jwt_required()
def listar_equipe():
    # 1. Puxa as informações extras (claims) que embutimos no token no momento do login
    claims = get_jwt()
    perfil_usuario = claims.get('perfil')
    empresa_usuario = claims.get('empresa_id')
    
    # 2. Barreira de Segurança: Se não for gestor ou admin, toma um erro 403 (Proibido)
    if perfil_usuario not in ['gestor', 'admin']:
        return jsonify({"erro": "Acesso negado. Funcionalidade restrita a gestores."}), 403
        
    # 3. Busca no banco todos os usuários que pertencem à MESMA empresa do gestor
    equipe = Usuario.query.filter_by(empresa_id=empresa_usuario).all()
    
    lista_equipe = []
    for membro in equipe:
        lista_equipe.append({
            "id": membro.id,
            "nome": membro.nome,
            "perfil": membro.perfil
        })
        
    return jsonify({
        "empresa_id": empresa_usuario,
        "total_membros": len(lista_equipe),
        "equipe": lista_equipe
    }), 200

@gestor_bp.route('/colaborador/<int:id_colaborador>/historico', methods=['GET'])
@jwt_required()
def historico_colaborador(id_colaborador):
    # 1. Puxa os dados do gestor logado
    claims = get_jwt()
    perfil_usuario = claims.get('perfil')
    empresa_usuario = claims.get('empresa_id')
    
    # 2. Barreira de Segurança Dupla
    if perfil_usuario not in ['gestor', 'admin']:
        return jsonify({"erro": "Acesso negado."}), 403
        
    # Verifica se o funcionário que ele quer ver existe e se é da mesma empresa dele
    colaborador = Usuario.query.filter_by(id=id_colaborador, empresa_id=empresa_usuario).first()
    if not colaborador:
        return jsonify({"erro": "Colaborador não encontrado ou não pertence à sua equipe."}), 404
        
    # 3. Busca as batidas de ponto desse colaborador específico
    registros = RegistroPonto.query.filter_by(usuario_id=id_colaborador).order_by(RegistroPonto.timestamp.desc()).all()
    
    lista_registros = []
    for reg in registros:
        lista_registros.append({
            "id": reg.id,
            "tipo": reg.tipo_registro,
            "horario": reg.timestamp.isoformat(),
            "status": reg.status
        })
        
    return jsonify({
        "colaborador": colaborador.nome,
        "total_registros": len(lista_registros),
        "historico": lista_registros
    }), 200

@gestor_bp.route('/colaborador/<int:id_colaborador>/ajuste', methods=['POST'])
@jwt_required()
def ajustar_ponto(id_colaborador):
    # 1. Barreira de Segurança
    claims = get_jwt()
    if claims.get('perfil') not in ['gestor', 'admin']:
        return jsonify({"erro": "Acesso negado."}), 403
        
    # 2. Verifica se o colaborador existe e é da mesma empresa
    colaborador = Usuario.query.filter_by(id=id_colaborador, empresa_id=claims.get('empresa_id')).first()
    if not colaborador:
        return jsonify({"erro": "Colaborador não encontrado."}), 404
        
    # 3. Pega os dados enviados pelo Gestor (Qual tipo de batida e que horas foi)
    dados = request.get_json()
    tipo = dados.get('tipo_registro')
    horario_str = dados.get('horario')
    
    if not tipo or not horario_str:
        return jsonify({"erro": "tipo_registro e horario são obrigatórios"}), 400
        
    # Tenta converter a string de data enviada para um objeto de tempo do Python
    try:
        horario_ajuste = datetime.fromisoformat(horario_str)
    except ValueError:
        return jsonify({"erro": "Formato de data inválido. Use ISO 8601 (ex: 2026-03-02T18:00:00)"}), 400
        
    # 4. Registra no banco com a MARCA DE AUDITORIA
    novo_registro = RegistroPonto(
        usuario_id=id_colaborador,
        tipo_registro=tipo,
        timestamp=horario_ajuste,
        ip_origem=request.remote_addr,
        dispositivo="Painel do Gestor (Ajuste Manual)", # Fica registrado de onde veio
        status="ajustado" # Status crucial para a regra de negócio
    )
    
    db.session.add(novo_registro)
    db.session.commit()
    
    return jsonify({
        "mensagem": f"Ponto ajustado com sucesso para {colaborador.nome}!",
        "horario_inserido": horario_ajuste.isoformat(),
        "status": "ajustado"
    }), 201

# ... (código anterior) ...

@gestor_bp.route('/pendencias', methods=['GET'])
@jwt_required()
def listar_pendencias():
    # 1. Barreira de Segurança
    claims = get_jwt()
    if claims.get('perfil') not in ['gestor', 'admin']:
        return jsonify({"erro": "Acesso negado."}), 403
        
    empresa_id = claims.get('empresa_id')
    
    # 2. Busca todos os pontos pendentes dos usuários que pertencem à empresa do gestor
    # Fazemos um "JOIN" (junção) entre a tabela de Registros e a de Usuários
    pendencias = db.session.query(RegistroPonto).join(Usuario).filter(
        Usuario.empresa_id == empresa_id,
        RegistroPonto.status == 'pendente_ajuste'
    ).all()
    
    lista_pendencias = []
    for p in pendencias:
        lista_pendencias.append({
            "id_registro": p.id,
            "colaborador": p.usuario.nome,
            "tipo_solicitado": p.tipo_registro,
            "horario": p.timestamp.isoformat(),
            "detalhes": p.dispositivo # É aqui que guardamos o motivo!
        })
        
    return jsonify({
        "total_pendencias": len(lista_pendencias),
        "pendencias": lista_pendencias
    }), 200

# ... (código anterior) ...

@gestor_bp.route('/pendencias/<int:id_registro>/avaliar', methods=['POST'])
@jwt_required()
def avaliar_pendencia(id_registro):
    # 1. Barreira de Segurança
    claims = get_jwt()
    if claims.get('perfil') not in ['gestor', 'admin']:
        return jsonify({"erro": "Acesso negado."}), 403
        
    empresa_id = claims.get('empresa_id')
    
    # 2. Busca o registro específico e garante que é de um funcionário desta empresa
    registro = db.session.query(RegistroPonto).join(Usuario).filter(
        RegistroPonto.id == id_registro,
        Usuario.empresa_id == empresa_id
    ).first()
    
    if not registro:
        return jsonify({"erro": "Registro não encontrado ou não pertence à sua equipe."}), 404
        
    if registro.status != 'pendente_ajuste':
        return jsonify({"erro": "Este registro não está pendente de aprovação."}), 400
        
    # 3. Pega a decisão do gestor (aprovar ou recusar)
    dados = request.get_json()
    acao = dados.get('acao')
    
    if acao == 'aprovar':
        registro.status = 'ajustado'
        mensagem = "Solicitação aprovada. Ponto ajustado com sucesso."
    elif acao == 'recusar':
        registro.status = 'recusado'
        mensagem = "Solicitação recusada pelo gestor."
    else:
        return jsonify({"erro": "Ação inválida. Envie 'aprovar' ou 'recusar'."}), 400
        
    # 4. Salva a decisão no banco
    db.session.commit()
    
    return jsonify({
        "mensagem": mensagem,
        "novo_status": registro.status
    }), 200