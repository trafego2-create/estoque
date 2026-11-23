"""As operações do estoque, num lugar só.

A tela do celular e a integração com o Radar de Projetos chamam exatamente estas funções, para
as duas entradas obedecerem às mesmas regras (patrimônio único, situação coerente com o dono,
histórico de tudo e reenvio que não duplica).
"""
from __future__ import annotations

from contextlib import contextmanager

from . import dados, regras


class JaExiste(Exception):
    """Patrimônio repetido ou registro duplicado (virará HTTP 409)."""


class NaoEncontrado(Exception):
    """Equipamento ou colaborador que não existe (virará HTTP 404)."""


@contextmanager
def erro_de_banco_virando_mensagem():
    """Erro do Postgres virando exceção que as rotas sabem traduzir."""
    try:
        yield
    except Exception as exc:
        nome = type(exc).__name__
        if nome == "UniqueViolation":
            if "patrimonio" in str(exc):
                raise JaExiste("Esse código de patrimônio já está cadastrado em outro item.") from exc
            raise JaExiste("Esse registro já existe.") from exc
        if nome == "CheckViolation":
            raise regras.Invalido("Combinação de situação e colaborador inválida.") from exc
        if nome == "ForeignKeyViolation":
            raise NaoEncontrado("Colaborador não encontrado.") from exc
        raise


def resolve_pessoa(corpo: dict, status: str) -> int | None:
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


def cadastrar(corpo: dict, usuario: str, origem_id: str | None = None) -> tuple[dict, bool]:
    """Devolve (equipamento, repetido). `repetido` = este 'bilhete' já havia sido gravado."""
    if origem_id:
        ja = dados.por_origem(origem_id)
        if ja:
            return ja, True
    limpo = regras.equipamento_do_formulario(corpo)
    with erro_de_banco_virando_mensagem():
        limpo["colaborador_id"] = resolve_pessoa(corpo, limpo["status"])
        novo = dados.criar_equipamento(limpo, usuario, origem_id)
    return novo, False


def editar(eid: int, corpo: dict, usuario: str) -> dict:
    atual = dados.equipamento(eid)
    if not atual:
        raise NaoEncontrado("Equipamento não encontrado.")
    juntos = {**atual, **corpo}
    limpo = regras.equipamento_do_formulario(juntos)
    with erro_de_banco_virando_mensagem():
        limpo["colaborador_id"] = resolve_pessoa(juntos, limpo["status"])
        novo = dados.editar_equipamento(eid, limpo, usuario)
    if not novo:
        raise NaoEncontrado("Equipamento não encontrado.")
    return novo


def mover(eid: int, corpo: dict, usuario: str, origem_id: str | None = None) -> tuple[dict, bool]:
    """Entrega, devolução, transferência, manutenção, retorno ou baixa."""
    if origem_id and dados.movimento_por_origem(origem_id):
        atual = dados.equipamento(eid)
        if not atual:
            raise NaoEncontrado("Equipamento não encontrado.")
        return atual, True
    atual = dados.equipamento(eid)
    if not atual:
        raise NaoEncontrado("Equipamento não encontrado.")
    acao = (corpo.get("acao") or "").strip().lower()
    with erro_de_banco_virando_mensagem():
        pessoa = corpo.get("colaborador_id")
        if not pessoa and regras.texto(corpo.get("colaborador_nome"), 160):
            pessoa = dados.achar_ou_criar_colaborador(
                regras.texto(corpo.get("colaborador_nome"), 160),
                regras.texto(corpo.get("colaborador_setor") or corpo.get("setor"), 80))["id"]
        regra = regras.confere_acao(acao, pessoa)
        novo = dados.movimentar(
            eid, acao, regra["status"], int(pessoa) if regra["exige_pessoa"] else None,
            regras.texto(corpo.get("setor"), 80), regras.texto(corpo.get("observacao"), 1000),
            usuario, origem_id)
    if not novo:
        raise NaoEncontrado("Equipamento não encontrado.")
    return novo, False


def excluir(eid: int) -> None:
    if not dados.excluir_equipamento(eid):
        raise NaoEncontrado("Equipamento não encontrado.")


def nova_pessoa(corpo: dict) -> dict:
    nome = regras.texto(corpo.get("nome"), 160)
    if not nome:
        raise regras.Invalido("Diga o nome do colaborador.")
    with erro_de_banco_virando_mensagem():
        return dados.jsonavel(dados.achar_ou_criar_colaborador(
            nome, regras.texto(corpo.get("setor"), 80), regras.texto(corpo.get("cargo"), 80),
            regras.texto(corpo.get("email"), 160)))


def editar_pessoa(cid: int, corpo: dict) -> dict:
    with erro_de_banco_virando_mensagem():
        pessoa = dados.editar_colaborador(cid, {
            "nome": regras.texto(corpo.get("nome"), 160),
            "setor": regras.texto(corpo.get("setor"), 80),
            "cargo": regras.texto(corpo.get("cargo"), 80),
            "email": regras.texto(corpo.get("email"), 160),
            "observacao": regras.texto(corpo.get("observacao"), 1000),
            "ativo": corpo.get("ativo"),
        })
    if not pessoa:
        raise NaoEncontrado("Colaborador não encontrado.")
    return pessoa
