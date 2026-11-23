"""
Brabo Estoque — controle dos equipamentos internos da empresa.

Duas perguntas que o site responde: o que a empresa tem (estoque) e com quem está cada coisa
(por colaborador). Feito para ser usado no celular, andando pela empresa: cadastro em
sequência, sugestões do que já foi digitado e fila local quando o sinal cai.

Banco: Postgres do Supabase comercial, schema `estoque`, usuário dedicado `estoque_app`
(só alcança esse schema).

Rotas:
  /healthz                                   saúde (EasyPanel)
  /api/login, /api/logout, /api/me, /api/senha
  /api/dados                                 tudo o que a tela mostra (ETag/304)
  /api/equipamentos            POST          cadastra
  /api/equipamentos/{id}       PATCH/DELETE  edita / apaga
  /api/equipamentos/{id}/mover POST          entrega, devolução, manutenção, baixa…
  /api/equipamentos/{id}/historico  GET
  /api/colaboradores           POST          cadastra pessoa
  /api/colaboradores/{id}      PATCH
  /api/exportar.csv            GET           planilha do estoque
  /api/integracao/*                          leitura para outros sistemas (ver integracao.py)
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import config, dados, integracao, regras, security

PUBLIC = Path(__file__).resolve().parent.parent / "public"
COOKIE = "brabo_estoque"

@asynccontextmanager
async def ciclo_de_vida(_app: FastAPI):
    yield
    from . import db
    db.fechar()  # devolve as conexões do pool ao desligar


app = FastAPI(title="Brabo Estoque", docs_url=None, redoc_url=None, openapi_url=None,
              lifespan=ciclo_de_vida)
app.add_middleware(GZipMiddleware, minimum_size=600)

_cache_usuarios: dict[int, tuple[float, dict]] = {}


async def corpo_json(req: Request) -> dict:
    """Corpo da requisição; texto quebrado vira 400 em vez de erro de servidor."""
    try:
        dados_corpo = await req.json()
    except (UnicodeDecodeError, ValueError):
        raise HTTPException(400, "Não consegui ler os dados enviados.")
    if not isinstance(dados_corpo, dict):
        raise HTTPException(400, "Formato inesperado.")
    return dados_corpo


@contextmanager
def erro_amigavel():
    """Erro do banco virando mensagem que faz sentido na tela (o resto sobe como 500)."""
    try:
        yield
    except Exception as exc:
        nome = type(exc).__name__
        if nome == "UniqueViolation":
            if "patrimonio" in str(exc):
                raise HTTPException(
                    409, "Esse código de patrimônio já está cadastrado em outro item.") from exc
            raise HTTPException(409, "Esse registro já existe.") from exc
        if nome == "CheckViolation":
            raise HTTPException(400, "Combinação de situação e colaborador inválida.") from exc
        if nome == "ForeignKeyViolation":
            raise HTTPException(400, "Colaborador não encontrado.") from exc
        raise


# ───────────────────────────── login ─────────────────────────────
def usuario_logado(req: Request) -> dict:
    """Lê o cookie assinado e confere no banco (com 60 s de folga) se a pessoa segue ativa."""
    sessao = security.ler_assinado(req.cookies.get(COOKIE))
    if not sessao or not sessao.get("uid"):
        raise HTTPException(401, "Faça login.")
    uid = int(sessao["uid"])
    agora = time.time()
    guardado = _cache_usuarios.get(uid)
    if guardado and agora - guardado[0] < 60:
        usuario = guardado[1]
    else:
        usuario = dados.usuario_por_id(uid)
        if not usuario:
            raise HTTPException(401, "Usuário desativado.")
        _cache_usuarios[uid] = (agora, usuario)
    if sessao.get("ver") != security.versao_senha(usuario["senha_hash"]):
        raise HTTPException(401, "A senha mudou: entre de novo.")
    return usuario


def supervisor(req: Request) -> dict:
    usuario = usuario_logado(req)
    if usuario["papel"] != "supervisor":
        raise HTTPException(403, "Só um supervisor pode fazer isso.")
    return usuario


def _sessao_cookie(resp: Response, usuario: dict) -> None:
    token = security.assinar(
        {"uid": usuario["id"], "email": usuario["email"], "nome": usuario["nome"],
         "papel": usuario["papel"], "ver": security.versao_senha(usuario["senha_hash"])},
        ttl_s=config.SESSAO_HORAS * 3600,
    )
    resp.set_cookie(COOKIE, token, max_age=config.SESSAO_HORAS * 3600, httponly=True,
                    samesite="lax", secure=config.COOKIE_SECURE, path="/")


@app.post("/api/login")
async def login(req: Request):
    corpo = await corpo_json(req)
    email = (corpo.get("email") or "").strip()
    senha = corpo.get("senha") or ""
    usuario = dados.usuario_por_email(email) if email else None
    if not usuario or not security.conferir_senha(senha, usuario["senha_hash"]):
        raise HTTPException(401, "E-mail ou senha não conferem.")
    resp = JSONResponse({"nome": usuario["nome"], "email": usuario["email"],
                         "papel": usuario["papel"]})
    _sessao_cookie(resp, usuario)
    return resp


@app.post("/api/logout")
async def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/")
    return resp


@app.get("/api/me")
async def me(req: Request):
    usuario = usuario_logado(req)
    return {"nome": usuario["nome"], "email": usuario["email"], "papel": usuario["papel"]}


@app.post("/api/senha")
async def trocar_senha(req: Request):
    usuario = usuario_logado(req)
    corpo = await corpo_json(req)
    if not security.conferir_senha(corpo.get("atual") or "", usuario["senha_hash"]):
        raise HTTPException(400, "A senha atual não confere.")
    nova = corpo.get("nova") or ""
    if len(nova) < 8:
        raise HTTPException(400, "A senha nova precisa de pelo menos 8 caracteres.")
    novo_hash = security.hash_senha(nova)
    dados.trocar_senha(usuario["id"], novo_hash)
    _cache_usuarios.pop(usuario["id"], None)
    resp = JSONResponse({"ok": True})
    _sessao_cookie(resp, {**usuario, "senha_hash": novo_hash})
    return resp


# ──────────────────────────── a tela ────────────────────────────
@app.get("/api/dados")
async def tela(req: Request):
    usuario = usuario_logado(req)
    corpo = {
        "equipamentos": dados.equipamentos(),
        "colaboradores": dados.colaboradores(),
        "resumo": {**regras.resumo_vazio(), **dados.resumo()},
        "sugestoes": dados.sugestoes(),
        "movimentos": dados.ultimos_movimentos(),
        "tipos_sugeridos": regras.TIPOS_SUGERIDOS,
        "acoes": {k: v["rotulo"] for k, v in regras.ACOES.items()},
        "eu": {"nome": usuario["nome"], "email": usuario["email"], "papel": usuario["papel"]},
    }
    bruto = json.dumps(corpo, ensure_ascii=False, default=str)
    etag = '"' + hashlib.sha256(bruto.encode()).hexdigest()[:24] + '"'
    if req.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})
    return Response(bruto, media_type="application/json",
                    headers={"ETag": etag, "Cache-Control": "no-cache"})


def _resolve_pessoa(corpo: dict, status: str) -> int | None:
    """Aceita colaborador_id OU um nome digitado na hora (cadastra a pessoa se for novo)."""
    if status != "com_colaborador":
        return None
    cid = corpo.get("colaborador_id")
    if cid:
        return int(cid)
    nome = regras.texto(corpo.get("colaborador_nome"), 160)
    if not nome:
        raise regras.Invalido("Diga com qual colaborador o equipamento está.")
    pessoa = dados.achar_ou_criar_colaborador(
        nome, regras.texto(corpo.get("colaborador_setor") or corpo.get("setor"), 80))
    return pessoa["id"]


@app.post("/api/equipamentos")
async def cadastrar(req: Request):
    usuario = usuario_logado(req)
    corpo = await corpo_json(req)
    origem = regras.texto(corpo.get("origem_id"), 80)
    if origem:  # reenvio da fila offline: já gravamos este bilhete?
        ja = dados.por_origem(origem)
        if ja:
            return {"equipamento": ja, "repetido": True}
    limpo = regras.equipamento_do_formulario(corpo)
    with erro_amigavel():
        limpo["colaborador_id"] = _resolve_pessoa(corpo, limpo["status"])
        novo = dados.criar_equipamento(limpo, usuario["email"], origem)
    return {"equipamento": novo}


@app.patch("/api/equipamentos/{eid}")
async def editar(eid: int, req: Request):
    usuario = usuario_logado(req)
    corpo = await corpo_json(req)
    atual = dados.equipamento(eid)
    if not atual:
        raise HTTPException(404, "Equipamento não encontrado.")
    limpo = regras.equipamento_do_formulario({**atual, **corpo})
    with erro_amigavel():
        limpo["colaborador_id"] = _resolve_pessoa({**atual, **corpo}, limpo["status"])
        novo = dados.editar_equipamento(eid, limpo, usuario["email"])
    return {"equipamento": novo}


@app.post("/api/equipamentos/{eid}/mover")
async def mover(eid: int, req: Request):
    usuario = usuario_logado(req)
    corpo = await corpo_json(req)
    origem = regras.texto(corpo.get("origem_id"), 80)
    if origem and dados.movimento_por_origem(origem):
        return {"equipamento": dados.equipamento(eid), "repetido": True}
    acao = (corpo.get("acao") or "").strip().lower()
    atual = dados.equipamento(eid)
    if not atual:
        raise HTTPException(404, "Equipamento não encontrado.")
    with erro_amigavel():
        pessoa = corpo.get("colaborador_id")
        if not pessoa and regras.texto(corpo.get("colaborador_nome"), 160):
            pessoa = dados.achar_ou_criar_colaborador(
                regras.texto(corpo.get("colaborador_nome"), 160),
                regras.texto(corpo.get("colaborador_setor") or corpo.get("setor"), 80))["id"]
        regra = regras.confere_acao(acao, pessoa)
        novo = dados.movimentar(
            eid, acao, regra["status"], int(pessoa) if regra["exige_pessoa"] else None,
            regras.texto(corpo.get("setor"), 80), regras.texto(corpo.get("observacao"), 1000),
            usuario["email"], origem)
    return {"equipamento": novo}


@app.get("/api/equipamentos/{eid}/historico")
async def historico(eid: int, req: Request):
    usuario_logado(req)
    return {"historico": dados.historico(eid)}


@app.delete("/api/equipamentos/{eid}")
async def apagar(eid: int, req: Request):
    supervisor(req)
    if not dados.excluir_equipamento(eid):
        raise HTTPException(404, "Equipamento não encontrado.")
    return {"ok": True}


@app.post("/api/colaboradores")
async def nova_pessoa(req: Request):
    usuario_logado(req)
    corpo = await corpo_json(req)
    nome = regras.texto(corpo.get("nome"), 160)
    if not nome:
        raise regras.Invalido("Diga o nome do colaborador.")
    with erro_amigavel():
        pessoa = dados.achar_ou_criar_colaborador(
            nome, regras.texto(corpo.get("setor"), 80), regras.texto(corpo.get("cargo"), 80),
            regras.texto(corpo.get("email"), 160))
    return {"colaborador": dados.jsonavel(pessoa)}


@app.patch("/api/colaboradores/{cid}")
async def editar_pessoa(cid: int, req: Request):
    usuario_logado(req)
    corpo = await corpo_json(req)
    with erro_amigavel():
        pessoa = dados.editar_colaborador(cid, {
            "nome": regras.texto(corpo.get("nome"), 160),
            "setor": regras.texto(corpo.get("setor"), 80),
            "cargo": regras.texto(corpo.get("cargo"), 80),
            "email": regras.texto(corpo.get("email"), 160),
            "observacao": regras.texto(corpo.get("observacao"), 1000),
            "ativo": corpo.get("ativo"),
        })
    if not pessoa:
        raise HTTPException(404, "Colaborador não encontrado.")
    return {"colaborador": pessoa}


COLUNAS_CSV = [
    ("patrimonio", "Código de patrimônio"), ("tipo", "Equipamento"), ("descricao", "Descrição"),
    ("marca", "Marca"), ("modelo", "Modelo"), ("serie", "Nº de série"), ("setor", "Setor"),
    ("localizacao", "Local"), ("condicao", "Condição"), ("status", "Situação"),
    ("colaborador_nome", "Com quem está"), ("colaborador_setor", "Setor da pessoa"),
    ("valor", "Valor"), ("observacao", "Observação"), ("criado_em", "Cadastrado em"),
    ("atualizado_em", "Atualizado em"), ("atualizado_por", "Por"),
]

SITUACAO = {"em_estoque": "Em estoque", "com_colaborador": "Com colaborador",
            "manutencao": "Manutenção", "emprestado": "Emprestado", "baixado": "Baixado"}
CONDICAO = {"novo": "Novo", "bom": "Bom", "regular": "Regular", "ruim": "Ruim",
            "defeito": "Com defeito"}


@app.get("/api/exportar.csv")
async def exportar(req: Request):
    usuario_logado(req)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow([rotulo for _, rotulo in COLUNAS_CSV])
    for e in dados.equipamentos():
        linha = []
        for campo, _ in COLUNAS_CSV:
            v = e.get(campo)
            if campo == "status":
                v = SITUACAO.get(v, v)
            elif campo == "condicao":
                v = CONDICAO.get(v, v)
            elif campo in ("criado_em", "atualizado_em") and v:
                # dd/mm/aaaa hh:mm no horário de Brasília, pronto para ler na planilha
                from datetime import datetime, timedelta, timezone
                try:
                    v = (datetime.fromisoformat(str(v)).astimezone(timezone(timedelta(hours=-3)))
                         .strftime("%d/%m/%Y %H:%M"))
                except ValueError:
                    pass
            linha.append("" if v is None else v)
        w.writerow(linha)
    # BOM: o Excel em português abre com acento certo
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="estoque-brabo.csv"'})


# ─────────────────────────── infraestrutura ───────────────────────────
@app.get("/healthz")
async def healthz():
    return {"ok": True, "banco": config.banco_configurado()}


@app.exception_handler(regras.Invalido)
async def _invalido(_req: Request, exc: regras.Invalido):
    return JSONResponse({"detail": str(exc)}, status_code=400)


# integração com outros sistemas da empresa (Radar de Projetos)
app.include_router(integracao.router)

app.mount("/", StaticFiles(directory=PUBLIC, html=True), name="public")
