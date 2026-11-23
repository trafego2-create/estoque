"""Tudo que fala com o banco (schema `estoque`). As rotas só chamam estas funções."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from . import db

CAMPOS_EQUIP = """e.id, e.patrimonio, e.tipo, e.descricao, e.marca, e.modelo, e.serie,
    e.setor, e.localizacao, e.condicao, e.status, e.colaborador_id,
    c.nome as colaborador_nome, c.setor as colaborador_setor,
    e.valor, e.observacao, e.criado_em, e.criado_por, e.atualizado_em, e.atualizado_por"""

SELECT_EQUIP = f"""select {CAMPOS_EQUIP}
    from estoque.equipamentos e
    left join estoque.colaboradores c on c.id = e.colaborador_id"""


def jsonavel(valor: Any) -> Any:
    """Decimal e data/hora não viram JSON sozinhos."""
    if isinstance(valor, Decimal):
        return float(valor)
    if hasattr(valor, "isoformat"):
        return valor.isoformat()
    if isinstance(valor, dict):
        return {k: jsonavel(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [jsonavel(v) for v in valor]
    return valor


# ───────────────────────────── login ─────────────────────────────
def usuario_por_email(email: str) -> dict | None:
    return db.um(
        "select * from estoque.usuarios where lower(btrim(email)) = lower(btrim(%s)) and ativo",
        (email,),
    )


def usuario_por_id(uid: int) -> dict | None:
    return db.um("select * from estoque.usuarios where id = %s and ativo", (uid,))


def trocar_senha(uid: int, senha_hash: str) -> None:
    db.executar("update estoque.usuarios set senha_hash = %s where id = %s", (senha_hash, uid))


# ──────────────────────────── leitura ────────────────────────────
def equipamentos() -> list[dict]:
    return jsonavel(db.consultar(SELECT_EQUIP + " order by e.atualizado_em desc"))


def equipamento(eid: int) -> dict | None:
    return jsonavel(db.um(SELECT_EQUIP + " where e.id = %s", (eid,)))


def por_patrimonio(patrimonio: str) -> dict | None:
    """Busca pelo código de patrimônio, ignorando maiúscula/minúscula e espaços."""
    return jsonavel(db.um(
        SELECT_EQUIP + " where e.patrimonio_norm = nullif(upper(btrim(%s)), '')", (patrimonio,)))


def colaboradores() -> list[dict]:
    return jsonavel(db.consultar("""
        select c.id, c.nome, c.setor, c.cargo, c.email, c.ativo, c.observacao, c.criado_em,
               count(e.id) filter (where e.status = 'com_colaborador') as itens
          from estoque.colaboradores c
          left join estoque.equipamentos e on e.colaborador_id = c.id
         group by c.id
         order by c.nome"""))


def resumo() -> dict:
    linhas = db.consultar("select status, count(*) as n from estoque.equipamentos group by status")
    r = {l["status"]: l["n"] for l in linhas}
    r["total"] = sum(r.values())
    return r


def sugestoes() -> dict:
    """Setores e tipos já usados, para o celular só escolher em vez de digitar."""
    setores = db.consultar("""
        select setor from (
            select setor from estoque.equipamentos where setor is not null
            union select setor from estoque.colaboradores where setor is not null
        ) s order by setor""")
    tipos = db.consultar(
        "select distinct tipo from estoque.equipamentos where tipo is not null order by tipo")
    return {"setores": [s["setor"] for s in setores], "tipos": [t["tipo"] for t in tipos]}


def historico(eid: int, limite: int = 200) -> list[dict]:
    return jsonavel(db.consultar("""
        select m.id, m.acao, m.de_status, m.para_status, m.setor, m.observacao, m.usuario,
               m.criado_em, de.nome as de_nome, para.nome as para_nome
          from estoque.movimentacoes m
          left join estoque.colaboradores de   on de.id   = m.de_colaborador_id
          left join estoque.colaboradores para on para.id = m.para_colaborador_id
         where m.equipamento_id = %s
         order by m.criado_em desc, m.id desc limit %s""", (eid, limite)))


def ultimos_movimentos(limite: int = 120) -> list[dict]:
    return jsonavel(db.consultar("""
        select m.id, m.equipamento_id, m.acao, m.para_status, m.setor, m.observacao, m.usuario,
               m.criado_em, e.patrimonio, e.tipo, e.descricao,
               de.nome as de_nome, para.nome as para_nome
          from estoque.movimentacoes m
          join estoque.equipamentos e on e.id = m.equipamento_id
          left join estoque.colaboradores de   on de.id   = m.de_colaborador_id
          left join estoque.colaboradores para on para.id = m.para_colaborador_id
         order by m.criado_em desc, m.id desc limit %s""", (limite,)))


# ──────────────────────────── escrita ────────────────────────────
def achar_ou_criar_colaborador(nome: str, setor: str | None = None,
                               cargo: str | None = None, email: str | None = None) -> dict:
    """Cadastra a pessoa na hora da coleta; se já existir, completa o setor que faltava."""
    return jsonavel(db.executar("""
        insert into estoque.colaboradores (nome, setor, cargo, email)
        values (%s, %s, %s, %s)
        on conflict (lower(btrim(nome))) do update
           set setor = coalesce(excluded.setor, estoque.colaboradores.setor),
               cargo = coalesce(excluded.cargo, estoque.colaboradores.cargo),
               email = coalesce(excluded.email, estoque.colaboradores.email),
               ativo = true
        returning *""", (nome, setor, cargo, email)))


def editar_colaborador(cid: int, d: dict) -> dict | None:
    return jsonavel(db.executar("""
        update estoque.colaboradores
           set nome = coalesce(%(nome)s, nome), setor = %(setor)s, cargo = %(cargo)s,
               email = %(email)s, observacao = %(observacao)s, ativo = coalesce(%(ativo)s, ativo)
         where id = %(id)s returning *""", {**d, "id": cid}))


def por_origem(origem_id: str) -> dict | None:
    """Item já gravado por este 'bilhete' do celular (reenvio da fila offline)."""
    return jsonavel(db.um(SELECT_EQUIP + " where e.origem_id = %s", (origem_id,)))


def movimento_por_origem(origem_id: str) -> dict | None:
    return db.um("select equipamento_id from estoque.movimentacoes where origem_id = %s",
                 (origem_id,))


def criar_equipamento(d: dict, usuario: str, origem_id: str | None = None) -> dict:
    novo = db.executar(f"""
        with inserido as (
            insert into estoque.equipamentos
                (patrimonio, tipo, descricao, marca, modelo, serie, setor, localizacao,
                 condicao, status, colaborador_id, valor, observacao, criado_por,
                 atualizado_por, origem_id)
            values (%(patrimonio)s, %(tipo)s, %(descricao)s, %(marca)s, %(modelo)s, %(serie)s,
                    %(setor)s, %(localizacao)s, %(condicao)s, %(status)s, %(colaborador_id)s,
                    %(valor)s, %(observacao)s, %(usuario)s, %(usuario)s, %(origem_id)s)
            returning *
        ), mov as (
            insert into estoque.movimentacoes
                (equipamento_id, acao, para_colaborador_id, para_status, setor, observacao,
                 usuario, origem_id)
            select id, 'cadastro', colaborador_id, status, setor, %(observacao)s, %(usuario)s,
                   case when %(origem_id)s is null then null else %(origem_id)s || ':cad' end
              from inserido
        )
        select {CAMPOS_EQUIP} from inserido e
        left join estoque.colaboradores c on c.id = e.colaborador_id
        """, {**d, "usuario": usuario, "origem_id": origem_id})
    return jsonavel(novo)


def editar_equipamento(eid: int, d: dict, usuario: str) -> dict | None:
    atual = db.executar(f"""
        with antes as (
            select id, status, colaborador_id from estoque.equipamentos
             where id = %(id)s for update
        ), mudou as (
            update estoque.equipamentos e set
                patrimonio = %(patrimonio)s, tipo = %(tipo)s, descricao = %(descricao)s,
                marca = %(marca)s, modelo = %(modelo)s, serie = %(serie)s, setor = %(setor)s,
                localizacao = %(localizacao)s, condicao = %(condicao)s, status = %(status)s,
                colaborador_id = %(colaborador_id)s, valor = %(valor)s,
                observacao = %(observacao)s, atualizado_por = %(usuario)s
              from antes where e.id = antes.id
            returning e.*, antes.status as de_status, antes.colaborador_id as de_colaborador_id
        ), mov as (
            insert into estoque.movimentacoes
                (equipamento_id, acao, de_colaborador_id, para_colaborador_id, de_status,
                 para_status, setor, observacao, usuario)
            select id, 'edicao', de_colaborador_id, colaborador_id, de_status, status, setor,
                   null, %(usuario)s
              from mudou
             where de_status is distinct from status
                or de_colaborador_id is distinct from colaborador_id
        )
        select {CAMPOS_EQUIP} from mudou e
        left join estoque.colaboradores c on c.id = e.colaborador_id
        """, {**d, "id": eid, "usuario": usuario})
    return jsonavel(atual)


def movimentar(eid: int, acao: str, status: str, colaborador_id: int | None, setor: str | None,
               observacao: str | None, usuario: str, origem_id: str | None = None) -> dict | None:
    atual = db.executar(f"""
        with antes as (
            select id, status, colaborador_id from estoque.equipamentos
             where id = %(id)s for update
        ), mudou as (
            update estoque.equipamentos e set
                status = %(status)s, colaborador_id = %(colaborador_id)s,
                setor = coalesce(%(setor)s, e.setor), atualizado_por = %(usuario)s
              from antes where e.id = antes.id
            returning e.*, antes.status as de_status, antes.colaborador_id as de_colaborador_id
        ), mov as (
            insert into estoque.movimentacoes
                (equipamento_id, acao, de_colaborador_id, para_colaborador_id, de_status,
                 para_status, setor, observacao, usuario, origem_id)
            select id, %(acao)s, de_colaborador_id, colaborador_id, de_status, status,
                   coalesce(%(setor)s, setor), %(observacao)s, %(usuario)s, %(origem_id)s
              from mudou
        )
        select {CAMPOS_EQUIP} from mudou e
        left join estoque.colaboradores c on c.id = e.colaborador_id
        """, {"id": eid, "acao": acao, "status": status, "colaborador_id": colaborador_id,
              "setor": setor, "observacao": observacao, "usuario": usuario,
              "origem_id": origem_id})
    return jsonavel(atual)


def excluir_equipamento(eid: int) -> bool:
    linha = db.executar("delete from estoque.equipamentos where id = %s returning id", (eid,))
    return bool(linha)
