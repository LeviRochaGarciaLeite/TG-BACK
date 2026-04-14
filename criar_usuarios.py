from app import create_app, db
from app.models import Usuario, Empresa
import bcrypt

app = create_app()

with app.app_context():
    # 1. Garante que a empresa existe
    empresa = Empresa.query.first()
    if not empresa:
        empresa = Empresa(nome_fantasia="Agência Pompéia", cnpj="00000000000100")
        db.session.add(empresa)
        db.session.flush()

    senha_padrao = bcrypt.hashpw("123456".encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    # 2. Cria o Gestor
    if not Usuario.query.filter_by(cpf="00000000000").first():
        gestor = Usuario(
            nome="Rodrigo (Gestor)",
            cpf="00000000000",
            senha_hash=senha_padrao,
            empresa_id=empresa.id,
            perfil="gestor",
            cidade="Pompéia",
            email="SEU_EMAIL_DE_TESTE@gmail.com" # <--- ADICIONE AQUI
        )
        db.session.add(gestor)

    # 3. Cria o Supervisor
    if not Usuario.query.filter_by(cpf="11111111111").first():
        supervisor = Usuario(
            nome="Zaraki (Supervisor)",
            cpf="11111111111",
            senha_hash=senha_padrao,
            empresa_id=empresa.id,
            perfil="supervisor",
            cidade="Pompéia",
            email="OUTRO_EMAIL_SEU@gmail.com" # <--- ADICIONE AQUI
        )
        db.session.add(supervisor)

    db.session.commit()
    print("✅ Usuários criados com sucesso!")
    print("GESTOR     -> CPF: 000.000.000-00 | Senha: 123456")
    print("SUPERVISOR -> CPF: 111.111.111-11 | Senha: 123456")