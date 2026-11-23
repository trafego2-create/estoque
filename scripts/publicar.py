"""Manda as variáveis de ambiente do Brabo Estoque para o EasyPanel e pede o deploy.

Por que existe: o DATABASE_URL e o SESSION_SECRET são segredos. Este script fala direto com
o MCP do EasyPanel, então os valores saem do .env local para o painel sem aparecer em
nenhuma conversa, print ou log.

Uso (do PC, com o .env na raiz e a variável de usuário EASYPANEL_NOVO_KEY):
    .venv/Scripts/python.exe scripts/publicar.py            # envia variáveis + deploy
    .venv/Scripts/python.exe scripts/publicar.py --so-env   # só as variáveis
"""
from __future__ import annotations

import json
import os
import pathlib
import secrets
import sys
import urllib.error
import urllib.request

PAINEL = "https://qacfzn.easypanel.host/api/mcp"
PROJETO = "automacoes"
SERVICO = "estoque"
RAIZ = pathlib.Path(__file__).resolve().parent.parent


def ler_env(arquivo: pathlib.Path) -> dict[str, str]:
    d: dict[str, str] = {}
    if not arquivo.exists():
        return d
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        if "=" in linha and not linha.lstrip().startswith("#"):
            k, v = linha.split("=", 1)
            d[k.strip()] = v.strip().strip('"').strip("'")
    return d


class Mcp:
    """Cliente mínimo do MCP (Streamable HTTP): initialize → tools/call."""

    def __init__(self, url: str, chave: str):
        self.url = url
        self.chave = chave
        self.sessao: str | None = None
        self.proximo = 0

    def _post(self, corpo: dict) -> tuple[dict | None, dict]:
        dados = json.dumps(corpo).encode()
        req = urllib.request.Request(self.url, data=dados, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json, text/event-stream")
        req.add_header("Authorization", f"Bearer {self.chave}")
        req.add_header("MCP-Protocol-Version", "2025-06-18")
        if self.sessao:
            req.add_header("Mcp-Session-Id", self.sessao)
        with urllib.request.urlopen(req, timeout=120) as resp:
            cabecalhos = dict(resp.headers)
            bruto = resp.read().decode("utf-8", "replace")
        if not bruto.strip():
            return None, cabecalhos
        if bruto.lstrip().startswith("event:") or "data:" in bruto.split("\n")[0]:
            for linha in bruto.splitlines():          # resposta em SSE
                if linha.startswith("data:"):
                    return json.loads(linha[5:].strip()), cabecalhos
            return None, cabecalhos
        return json.loads(bruto), cabecalhos

    def iniciar(self) -> None:
        self.proximo += 1
        resposta, cabecalhos = self._post({
            "jsonrpc": "2.0", "id": self.proximo, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "brabo-estoque-publicar", "version": "1"}},
        })
        self.sessao = cabecalhos.get("Mcp-Session-Id") or cabecalhos.get("mcp-session-id")
        if resposta and resposta.get("error"):
            raise RuntimeError(resposta["error"])
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

    def chamar(self, ferramenta: str, argumentos: dict) -> dict:
        self.proximo += 1
        resposta, _ = self._post({
            "jsonrpc": "2.0", "id": self.proximo, "method": "tools/call",
            "params": {"name": ferramenta, "arguments": argumentos},
        })
        if not resposta:
            raise RuntimeError("o painel não respondeu")
        if resposta.get("error"):
            raise RuntimeError(resposta["error"])
        return resposta.get("result", {})


def main() -> int:
    chave = os.environ.get("EASYPANEL_NOVO_KEY", "").strip()
    if not chave:
        print("Falta a variável de usuário EASYPANEL_NOVO_KEY.")
        return 2

    local = ler_env(RAIZ / ".env")
    if not local.get("DATABASE_URL"):
        print("Falta DATABASE_URL no .env da raiz.")
        return 2

    # o segredo do cookie de produção é separado do usado no PC; fica guardado para as
    # próximas publicações não deslogarem todo mundo
    arq_prod = RAIZ / ".env.producao"
    prod = ler_env(arq_prod)
    if not prod.get("SESSION_SECRET"):
        prod["SESSION_SECRET"] = secrets.token_urlsafe(48)
        arq_prod.write_text(f"SESSION_SECRET={prod['SESSION_SECRET']}\n", encoding="utf-8")
        print("gerei o SESSION_SECRET de produção e guardei em .env.producao (fora do git)")

    # chave que o Radar de Projetos usa para ler o estoque (uma chave por sistema)
    if not prod.get("CHAVE_RADAR"):
        prod["CHAVE_RADAR"] = secrets.token_urlsafe(32)
        print("gerei a CHAVE_RADAR e guardei em .env.producao (o script do Radar lê daqui)")
    arq_prod.write_text(
        f"SESSION_SECRET={prod['SESSION_SECRET']}\nCHAVE_RADAR={prod['CHAVE_RADAR']}\n",
        encoding="utf-8")

    env = "\n".join([
        f"DATABASE_URL={local['DATABASE_URL']}",
        f"SESSION_SECRET={prod['SESSION_SECRET']}",
        "COOKIE_SECURE=1",
        "SESSAO_HORAS=720",
        "URL_PUBLICA=https://automacoes-estoque.qacfzn.easypanel.host",
        f"CHAVES_INTEGRACAO=radar={prod['CHAVE_RADAR']}",
    ])

    mcp = Mcp(PAINEL, chave)
    mcp.iniciar()
    mcp.chamar("execute_destructive", {
        "procedure": "updateAppEnv",
        "input": {"projectName": PROJETO, "serviceName": SERVICO, "env": env},
    })
    print(f"variáveis enviadas: {len(env.splitlines())} (valores não aparecem aqui)")

    if "--so-env" not in sys.argv:
        mcp.chamar("execute_destructive", {
            "procedure": "deployAppService",
            "input": {"projectName": PROJETO, "serviceName": SERVICO},
        })
        print("deploy pedido: o build leva alguns minutos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
