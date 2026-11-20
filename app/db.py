"""Acesso ao Postgres com poucas conexões reaproveitadas.

Mesma lição aprendida no Radar de Projetos: abrir conexão até o Supabase custa ~1,3 s, e o
pooler em modo sessão (5432) aceita só 15 clientes somados de todos os sistemas. Então:
pooler em modo transação (6543), pool pequeno, sem prepared statements, conexão reciclada a
cada 5 min (conexão longa pelo pooler já corrompeu acentos em outro projeto) e nova tentativa
se uma conexão cair no meio.
"""
from __future__ import annotations

import time
from typing import Any

from . import config

_pool = None
POOL_MAX = 3


def pool():
    global _pool
    if _pool is None:
        from psycopg_pool import ConnectionPool
        _pool = ConnectionPool(
            config.DATABASE_URL, min_size=1, max_size=POOL_MAX, max_lifetime=300,
            max_idle=120, timeout=20, name="estoque", open=True,
            kwargs={"autocommit": True, "prepare_threshold": None, "client_encoding": "utf8"},
        )
    return _pool


def fechar() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def _rodar(fn):
    """fn(cursor) com até 3 tentativas: o pooler reinicia e derruba conexões sem avisar."""
    import psycopg
    from psycopg.rows import dict_row
    from psycopg_pool import PoolTimeout

    ultimo: Exception | None = None
    for tentativa in range(3):
        try:
            with pool().connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    return fn(cur)
        except (psycopg.OperationalError, psycopg.InterfaceError, PoolTimeout) as e:
            ultimo = e
            time.sleep(0.4 * (tentativa + 1))
        except psycopg.errors.AdminShutdown as e:  # pragma: no cover - pooler reiniciando
            ultimo = e
            time.sleep(0.4 * (tentativa + 1))
    raise ultimo  # type: ignore[misc]


def consultar(sql: str, params: Any = None) -> list[dict]:
    return _rodar(lambda cur: (cur.execute(sql, params), cur.fetchall())[1])


def um(sql: str, params: Any = None) -> dict | None:
    linhas = consultar(sql, params)
    return linhas[0] if linhas else None


def executar(sql: str, params: Any = None) -> dict | None:
    """INSERT/UPDATE/DELETE. Com RETURNING, devolve a primeira linha."""
    def _f(cur):
        cur.execute(sql, params)
        if cur.description:
            linhas = cur.fetchall()
            return linhas[0] if linhas else None
        return None
    return _rodar(_f)
