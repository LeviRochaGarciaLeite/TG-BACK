from app import create_app
from app.models import db, Empresa, Usuario
import bcrypt

app = create_app()

with app.app_context():
    # 1. Cria uma empresa de teste se não existir
    empresa = Empresa.query.filter_by(cnpj="00000000000100").first()
    if not empresa:
        empresa = Empresa(nome_fantasia="Nexus Corp", cnpj="00000000000100")
        db.session.add(empresa)
        db.session.commit()
        print("Empresa 'Nexus Corp' criada com sucesso!")

    # 2. Cria o usuário gestor se não existir
    cpf_teste = "12345678900"
    usuario = Usuario.query.filter_by(cpf=cpf_teste).first()
    
    if not usuario:
        senha_plana = "senha_corporativa_123"
        # Gera o hash da senha usando bcrypt (como definimos na rota de login)
        senha_hash = bcrypt.hashpw(senha_plana.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        novo_usuario = Usuario(
            empresa_id=empresa.id,
            nome="Gestor Nexus",
            cpf=cpf_teste,
            senha_hash=senha_hash,
            perfil="gestor"
        )
        db.session.add(novo_usuario)
        db.session.commit()
        print("Usuário gestor criado com sucesso!")
    else:
        print("Usuário já existe no banco.")