"""Configuração do Brabo Estoque (local: arquivo .env; EasyPanel: aba Environment)."""
import os
import secrets
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _carregar_env_local() -> None:
    """Lê o .env da raiz em desenvolvimento, sem sobrescrever o que já veio do ambiente."""
    arq = RAIZ / ".env"
    if not arq.exists():
        return
    for linha in arq.read_text(encoding="utf-8").splitlines():
        if "=" in linha and not linha.lstrip().startswith("#"):
            k, v = linha.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_carregar_env_local()

# Banco: Postgres do Supabase comercial, schema `estoque`, usuário dedicado `estoque_app`.
# Use sempre a porta 6543 (pooler em modo transação): a 5432 tem teto de 15 conexões
# somando todos os sistemas da empresa.
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Assina o cookie de sessão. Trocar desloga todo mundo.
SESSION_SECRET = os.environ.get("SESSION_SECRET", "")
if not SESSION_SECRET:
    if DATABASE_URL:
        raise RuntimeError(
            "SESSION_SECRET é obrigatório em produção "
            '(gere com: python -c "import secrets;print(secrets.token_urlsafe(48))")'
        )
    SESSION_SECRET = "dev-" + secrets.token_urlsafe(32)

COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "1") != "0"
SESSAO_HORAS = int(os.environ.get("SESSAO_HORAS", "720"))  # 30 dias: é celular em uso na empresa


def banco_configurado() -> bool:
    return bool(DATABASE_URL)
