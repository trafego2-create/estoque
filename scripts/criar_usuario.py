"""Cria (ou atualiza) quem pode entrar no Brabo Estoque.

Rode do PC, com o .env na raiz do projeto:
    python scripts/criar_usuario.py "Nome da Pessoa" email@aprovasim.com [supervisor]

Sem a senha nos argumentos: ela é sorteada e aparece na tela uma única vez.
Supervisor é quem pode excluir equipamento; operador faz todo o resto.
"""
import secrets
import string
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, security  # noqa: E402


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    nome, email = sys.argv[1].strip(), sys.argv[2].strip().lower()
    papel = (sys.argv[3].strip().lower() if len(sys.argv) > 3 else "operador")
    if papel not in ("operador", "supervisor"):
        print("Papel precisa ser 'operador' ou 'supervisor'.")
        return 2
    alfabeto = string.ascii_letters + string.digits
    senha = sys.argv[4] if len(sys.argv) > 4 else "".join(secrets.choice(alfabeto) for _ in range(12))

    db.executar("""
        insert into estoque.usuarios (email, nome, senha_hash, papel)
        values (%s, %s, %s, %s)
        on conflict (lower(btrim(email))) do update
           set nome = excluded.nome, senha_hash = excluded.senha_hash,
               papel = excluded.papel, ativo = true
    """, (email, nome, security.hash_senha(senha), papel))

    print(f"ok: {nome} <{email}> como {papel}")
    print(f"senha: {senha}")
    print("Entregue a senha pessoalmente; da para trocar no site em Opcoes > Trocar minha senha.")
    db.fechar()  # sem isto o Python reclama das conexoes abertas ao terminar
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
