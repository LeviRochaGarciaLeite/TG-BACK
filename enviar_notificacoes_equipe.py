"""
Script para enviar notificações manuais para usuários adicionados à equipe.
Executa: python enviar_notificacoes_equipe.py
"""

from app import create_app
from app.models import db, Usuario, Equipe
from app.routes.notificacoes import criar_notificacao

app = create_app()

with app.app_context():
    # Encontrar usuários por nome
    rodrigo = Usuario.query.filter(Usuario.nome.ilike('%rodrigo%'), Usuario.perfil == 'colaborador').first()
    monica_mota = Usuario.query.filter(Usuario.nome.ilike('%monica%'), Usuario.nome.ilike('%mota%')).first()

    usuarios = []
    if rodrigo:
        usuarios.append(rodrigo)
        print(f"Encontrado: {rodrigo.nome} (ID: {rodrigo.id})")
    else:
        print("Usuário 'rodrigo' não encontrado.")

    if monica_mota:
        usuarios.append(monica_mota)
        print(f"Encontrado: {monica_mota.nome} (ID: {monica_mota.id})")
    else:
        print("Usuário 'monica mota' não encontrado.")

    if not usuarios:
        print("Nenhum usuário encontrado.")
        exit()

    # Para cada usuário, verificar se está em uma equipe e enviar notificação
    for usuario in usuarios:
        # Verificar se o usuário está em alguma equipe
        equipe = (
            Equipe.query
            .join(Equipe.membros)
            .filter(Usuario.id == usuario.id)
            .first()
        )
        if equipe:
            supervisor = equipe.supervisor
            nome_supervisor = supervisor.nome if supervisor else "Seu supervisor"
            criar_notificacao(
                usuario.id,
                f"👥 Você foi adicionado à equipe por {nome_supervisor}.",
                tipo="equipe",
                tela="equipe",
            )
            print(f"Notificação enviada para {usuario.nome}.")
        else:
            print(f"{usuario.nome} não está em nenhuma equipe.")

    db.session.commit()
    print("Notificações enviadas com sucesso.")