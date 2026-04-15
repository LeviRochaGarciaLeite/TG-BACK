"""
Seed do supervisor com CPF 55382438854.
Executa: python seed_supervisor.py
- O usuário já deve ter se cadastrado pela tela de cadastro.
- Este script atualiza o perfil para 'supervisor' e ativa o usuário se estiver inativo.
"""

from app import create_app
from app.models import db, Usuario

CPF_SUPERVISOR = "55382438854"

app = create_app()

with app.app_context():
    usuario = Usuario.query.filter_by(cpf=CPF_SUPERVISOR).first()

    if not usuario:
        print(f"❌ Usuário com CPF {CPF_SUPERVISOR} não encontrado.")
        print("   Cadastre-se primeiro pela tela de cadastro do app.")
    else:
        changes = []
        if not usuario.ativo:
            usuario.ativo = True
            changes.append("ativado")
        if usuario.perfil != "supervisor":
            perfil_antigo = usuario.perfil
            usuario.perfil = "supervisor"
            changes.append(f"perfil: {perfil_antigo} → supervisor")
        
        if changes:
            db.session.commit()
            print(f"✅ Usuário atualizado: {', '.join(changes)} (CPF={CPF_SUPERVISOR})")
        else:
            print(f"ℹ️  Supervisor já configurado e ativo: CPF={CPF_SUPERVISOR}")

        print(f"\nDados do supervisor:")
        print(f"  CPF: {CPF_SUPERVISOR}")
        print(f"  Nome: {usuario.nome}")
        print(f"  Perfil: {usuario.perfil}")
        print(f"  Ativo: {usuario.ativo}")
        print(f"  Empresa: {usuario.empresa.nome_fantasia}")
