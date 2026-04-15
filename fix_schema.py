"""Verifica e corrige o schema do banco de dados."""
import sqlite3

conn = sqlite3.connect("instance/nexus.db")
c = conn.cursor()

# Colunas atuais de equipes
c.execute("PRAGMA table_info(equipes)")
colunas = [r[1] for r in c.fetchall()]
print(f"Colunas equipes: {colunas}")

# Precisa recriar se tem colunas antigas (colaborador1_id, colaborador2_id)
if "colaborador1_id" in colunas or "nome" not in colunas:
    print("Recriando tabela equipes com novo schema...")

    # Salva dados existentes (apenas colunas que permanecem)
    c.execute("SELECT id, empresa_id, supervisor_id, criado_em FROM equipes")
    dados = c.fetchall()
    print(f"  {len(dados)} equipe(s) existente(s) salvas")

    c.execute("DROP TABLE IF EXISTS equipes")
    c.execute("""
        CREATE TABLE equipes (
            id INTEGER PRIMARY KEY,
            empresa_id INTEGER NOT NULL,
            supervisor_id INTEGER NOT NULL UNIQUE,
            nome VARCHAR(100),
            criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (empresa_id) REFERENCES empresas(id),
            FOREIGN KEY (supervisor_id) REFERENCES usuarios(id)
        )
    """)

    # Reinsere dados
    for row in dados:
        c.execute(
            "INSERT INTO equipes (id, empresa_id, supervisor_id, criado_em, atualizado_em) VALUES (?, ?, ?, ?, ?)",
            (row[0], row[1], row[2], row[3], row[3])
        )
    conn.commit()
    print("  Tabela equipes recriada!")
else:
    print("Tabela equipes ja esta atualizada.")

# Cria tabela equipe_membros se nao existir
c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='equipe_membros'")
if not c.fetchone():
    c.execute("""
        CREATE TABLE equipe_membros (
            equipe_id INTEGER NOT NULL,
            usuario_id INTEGER NOT NULL,
            PRIMARY KEY (equipe_id, usuario_id),
            FOREIGN KEY (equipe_id) REFERENCES equipes(id),
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
        )
    """)
    conn.commit()
    print("Tabela 'equipe_membros' criada")
else:
    print("Tabela 'equipe_membros' ja existe")

# Confirma estado final
c.execute("PRAGMA table_info(equipes)")
print(f"\nColunas finais equipes: {[r[1] for r in c.fetchall()]}")

conn.close()
print("\nSchema atualizado com sucesso!")
