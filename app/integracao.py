"""Porta de entrada para outros sistemas da empresa operarem o estoque (hoje: o Radar de Projetos).

Desde 23/11/2026 o Radar faz tudo o que a tela do celular faz — cadastrar, editar, entregar,
devolver, transferir, mandar para manutenção, registrar retorno, dar baixa, excluir e mexer nos
colaboradores. Tudo passa por `app/operacoes.py`, as mesmas funções que a tela usa, então as
regras são idênticas nas duas entradas.

Regras da porta:
- o sistema que chama se identifica por uma chave no cabeçalho `X-Chave` (uma por sistema, em
  `CHAVES_INTEGRACAO`);
- **quem pode o quê é decidido pelo sistema que chama** (o Radar tem login e perfis: só
  master/equipe escreve, só master exclui). Aqui a chave vale como "sistema autorizado", e o
  campo `por` diz qual pessoa fez, para o histórico não ficar anônimo;
- a **listagem** nunca traz valor do equipamento, nota fiscal nem observação do item. Esses
  campos só saem na ficha de um item (`GET /equipamentos/{id}`), que o Radar abre apenas para
  quem pode editar;
- `origem_id` deixa o reenvio seguro: a mesma chamada duas vezes não grava duas vezes.
"""
from __future__ import annotations

import hmac

from fastapi import APIRouter, HTTPException, Request

from . import config, dados, operacoes, regras

router = APIRouter(prefix="/api/integracao")

# o que a listagem mostra para fora
CAMPOS_PUBLICOS = (
    "id", "patrimonio", "tipo", "descricao", "marca", "modelo", "serie", "setor",
    "localizacao", "condicao", "status", "colaborador_id", "colaborador_nome",
    "colaborador_setor", "atualizado_em",
)
# a mais, só na ficha de um item (o Radar abre para master/equipe)
CAMPOS_FICHA = CAMPOS_PUBLICOS + ("valor", "observacao", "criado_em", "criado_por",
                                  "atualizado_por")


def quem_chama(req: Request) -> str:
    """Confere a chave do cabeçalho e devolve o nome do sistema que chamou."""
    chave = (req.headers.get("x-chave") or "").strip()
    if not chave:
        raise HTTPException(401, "Falta a chave de integração.")
    for nome, valor in config.chaves_integracao().items():
        if hmac.compare_digest(chave, valor):
            return nome
    raise HTTPException(401, "Chave de integração não reconhecida.")


def _publico(e: dict | None, campos=CAMPOS_PUBLICOS) -> dict:
    return {campo: (e or {}).get(campo) for campo in campos}


async def _corpo(req: Request) -> dict:
    try:
        corpo = await req.json()
    except (UnicodeDecodeError, ValueError):
        raise HTTPException(400, "Não consegui ler os dados enviados.")
    if not isinstance(corpo, dict):
        raise HTTPException(400, "Formato inesperado.")
    return corpo


def _autor(sistema: str, corpo: dict) -> str:
    """Quem fica no histórico: o sistema e a pessoa que mandou (ex.: radar:ana@…)."""
    pessoa = regras.texto(corpo.get("por"), 120)
    return f"{sistema}:{pessoa}" if pessoa else sistema


# ───────────────────────────── leitura ─────────────────────────────
@router.get("/estoque")
async def estoque(req: Request):
    """Tudo o que o outro sistema precisa para montar a tela de estoque."""
    quem_chama(req)
    itens = [_publico(e) for e in dados.equipamentos()]
    disponivel_por_tipo: dict[str, int] = {}
    for e in itens:
        if e["status"] == "em_estoque":
            disponivel_por_tipo[e["tipo"]] = disponivel_por_tipo.get(e["tipo"], 0) + 1
    return {
        "resumo": {**regras.resumo_vazio(), **dados.resumo()},
        "itens": itens,
        "disponivel_por_tipo": disponivel_por_tipo,
        "pessoas": [
            {"id": p["id"], "nome": p["nome"], "setor": p["setor"], "cargo": p.get("cargo"),
             "email": p.get("email"), "ativo": p.get("ativo"), "itens": p["itens"]}
            for p in dados.colaboradores()
        ],
        "movimentos": [
            {k: m.get(k) for k in ("id", "equipamento_id", "acao", "para_status", "setor",
                                   "observacao", "usuario", "criado_em", "patrimonio", "tipo",
                                   "descricao", "de_nome", "para_nome")}
            for m in dados.ultimos_movimentos(200)
        ],
        "sugestoes": dados.sugestoes(),
        "tipos_sugeridos": regras.TIPOS_SUGERIDOS,
        "condicoes": regras.CONDICOES,
        "acoes": {k: v["rotulo"] for k, v in regras.ACOES.items()},
        "url": config.URL_PUBLICA,
    }


@router.get("/equipamentos/{eid}")
async def ficha(eid: int, req: Request):
    """Ficha completa de um item (com valor e observação), para editar do outro lado."""
    quem_chama(req)
    item = dados.equipamento(eid)
    if not item:
        raise HTTPException(404, "Equipamento não encontrado.")
    return {"equipamento": _publico(item, CAMPOS_FICHA)}


@router.get("/estoque/{eid}/historico")
async def historico(eid: int, req: Request):
    quem_chama(req)
    if not dados.equipamento(eid):
        raise HTTPException(404, "Equipamento não encontrado.")
    return {"historico": dados.historico(eid)}


# ───────────────────────────── escrita ─────────────────────────────
@router.post("/equipamentos")
async def cadastrar(req: Request):
    sistema = quem_chama(req)
    corpo = await _corpo(req)
    novo, repetido = operacoes.cadastrar(corpo, _autor(sistema, corpo),
                                         regras.texto(corpo.get("origem_id"), 80))
    return {"equipamento": _publico(novo, CAMPOS_FICHA), "repetido": repetido}


@router.patch("/equipamentos/{eid}")
async def editar(eid: int, req: Request):
    sistema = quem_chama(req)
    corpo = await _corpo(req)
    novo = operacoes.editar(eid, corpo, _autor(sistema, corpo))
    return {"equipamento": _publico(novo, CAMPOS_FICHA)}


@router.post("/equipamentos/{eid}/mover")
async def mover(eid: int, req: Request):
    """Entrega, devolução, transferência, manutenção, retorno ou baixa."""
    sistema = quem_chama(req)
    corpo = await _corpo(req)
    novo, repetido = operacoes.mover(eid, corpo, _autor(sistema, corpo),
                                     regras.texto(corpo.get("origem_id"), 80))
    return {"equipamento": _publico(novo), "repetido": repetido}


@router.delete("/equipamentos/{eid}")
async def excluir(eid: int, req: Request):
    """Apaga o item e o histórico dele. O outro sistema é que decide quem pode fazer isso."""
    quem_chama(req)
    operacoes.excluir(eid)
    return {"ok": True}


@router.post("/colaboradores")
async def nova_pessoa(req: Request):
    quem_chama(req)
    return {"colaborador": operacoes.nova_pessoa(await _corpo(req))}


@router.patch("/colaboradores/{cid}")
async def editar_pessoa(cid: int, req: Request):
    quem_chama(req)
    return {"colaborador": operacoes.editar_pessoa(cid, await _corpo(req))}


@router.post("/entregar")
async def entregar(req: Request):
    """Atalho usado quando o Radar fecha um pedido de equipamento: aceita o item pelo
    patrimônio e escolhe entre entrega e transferência conforme a situação atual."""
    sistema = quem_chama(req)
    corpo = await _corpo(req)

    origem = regras.texto(corpo.get("origem_id"), 80)
    if origem and dados.movimento_por_origem(origem):
        return {"repetido": True}

    if not regras.texto(corpo.get("colaborador_nome"), 160) and not corpo.get("colaborador_id"):
        raise HTTPException(400, "Diga para qual colaborador o equipamento foi.")

    item = None
    if corpo.get("equipamento_id"):
        item = dados.equipamento(int(corpo["equipamento_id"]))
    elif regras.patrimonio(corpo.get("patrimonio")):
        item = dados.por_patrimonio(regras.patrimonio(corpo["patrimonio"]))
    if not item:
        raise HTTPException(404, "Equipamento não encontrado no estoque.")
    if item["status"] == "baixado":
        raise HTTPException(409, "Esse item está baixado: não pode ser entregue.")

    acao = "transferencia" if item["status"] == "com_colaborador" else "entrega"
    novo, repetido = operacoes.mover(
        item["id"],
        {**corpo, "acao": acao,
         "observacao": regras.texto(corpo.get("observacao"), 1000) or f"Registrado pelo {sistema}"},
        _autor(sistema, corpo), origem)
    return {"equipamento": _publico(novo), "acao": acao, "repetido": repetido}
