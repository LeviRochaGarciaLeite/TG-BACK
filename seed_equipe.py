"""
Seed da equipe.
Executa: python seed_equipe.py
- Verifica se os colaboradores já estão cadastrados (via tela de cadastro).
- NÃO cria usuários nem define senhas. Apenas lista o status.
"""

from app import create_app
from app.models import db, Empresa, Usuario

app = create_app()

with app.app_context():
    empresa = Empresa.query.first()
    
    if empresa:
        print(f"Verificando equipe da empresa: {empresa.nome_fantasia}")
        
        cpfs_colaboradores = [
            {"nome": "Levi Rocha (Atendimento)", "cpf": "11111111111"},
            {"nome": "Lucas Hilario (Suporte)", "cpf": "22222222222"},
            {"nome": "Rodrigo Matheus (Vendas)", "cpf": "33333333333"}
        ]
        
        for colab in cpfs_colaboradores:
            usuario = Usuario.query.filter_by(cpf=colab['cpf']).first()
            if usuario:
                print(f"  ✅ {colab['nome']} (CPF {colab['cpf']}) — cadastrado, perfil: {usuario.perfil}")
            else:
                print(f"  ❌ {colab['nome']} (CPF {colab['cpf']}) — não cadastrado. Cadastre pela tela do app.")
    else:
        print("❌ Nenhuma empresa encontrada. Execute seed.py primeiro.")