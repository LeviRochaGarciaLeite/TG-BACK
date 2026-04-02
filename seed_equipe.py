from app import create_app
from app.models import db, Empresa, Usuario
import bcrypt

app = create_app()

with app.app_context():
    # Pega a primeira empresa do banco (Nexus Corp)
    empresa = Empresa.query.first()
    
    if empresa:
        print(f"Adicionando equipe para a empresa: {empresa.nome_fantasia}")
        
        # Lista de funcionários fictícios
        colaboradores = [
            {"nome": "Levi Rocha (Atendimento)", "cpf": "11111111111"},
            {"nome": "Lucas Hilario (Suporte)", "cpf": "22222222222"},
            {"nome": "Rodrigo Matheus (Vendas)", "cpf": "33333333333"}
        ]
        
        # Gerando uma senha padrão para eles
        senha_hash = bcrypt.hashpw("senha123".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        adicionados = 0
        for func in colaboradores:
            # Verifica se o CPF já existe para não duplicar se rodar duas vezes
            if not Usuario.query.filter_by(cpf=func['cpf']).first():
                novo_usuario = Usuario(
                    empresa_id=empresa.id,
                    nome=func['nome'],
                    cpf=func['cpf'],
                    senha_hash=senha_hash,
                    perfil="colaborador" # <-- Note que o perfil deles é diferente do seu!
                )
                db.session.add(novo_usuario)
                adicionados += 1
                
        db.session.commit()
        print(f"{adicionados} colaboradores adicionados com sucesso!")
    else:
        print("Empresa não encontrada.")