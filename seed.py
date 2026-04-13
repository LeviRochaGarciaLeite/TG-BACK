"""
Seed do gestor.
Executa: python seed.py
- O usuário já deve ter se cadastrado pela tela de cadastro.
- Este script apenas atualiza o perfil para 'gestor'.
"""

from app import create_app
from app.models import db, Empresa, Usuario

app = create_app()

with app.app_context():
    # Garante que existe empresa
    empresa = Empresa.query.filter_by(cnpj="00000000000100").first()
    if not empresa:
        empresa = Empresa(nome_fantasia="Nexus Corp", cnpj="00000000000100")
        db.session.add(empresa)
        db.session.commit()
        print("Empresa 'Nexus Corp' criada com sucesso!")

    cpf_gestor = "12345678900"
    usuario = Usuario.query.filter_by(cpf=cpf_gestor).first()
    
    if not usuario:
        print(f"❌ Usuário com CPF {cpf_gestor} não encontrado.")
        print("   Cadastre-se primeiro pela tela de cadastro do app.")
    else:
        if usuario.perfil != "gestor":
            perfil_antigo = usuario.perfil
            usuario.perfil = "gestor"
            db.session.commit()
            print(f"✅ Perfil atualizado: {perfil_antigo} → gestor (CPF={cpf_gestor})")
        else:
            print(f"ℹ️  Gestor já configurado: CPF={cpf_gestor}")