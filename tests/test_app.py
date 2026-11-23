"""Testes do Brabo Estoque: regras puras + rotas com um banco de mentira.

Não tocam no Supabase: o módulo `dados` é substituído por funções que guardam tudo num dicionário.
Rodar: .venv/Scripts/python.exe -m pytest -q
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SESSION_SECRET", "teste-" + "x" * 30)
os.environ.setdefault("COOKIE_SECURE", "0")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import dados, main, regras, security  # noqa: E402


# ───────────────────────── regras puras ─────────────────────────
def test_texto_limpa_e_corta():
    assert regras.texto("  Notebook  ") == "Notebook"
    assert regras.texto("") is None
    assert regras.texto(None) is None
    assert len(regras.texto("a" * 500, 60)) == 60


def test_patrimonio_normaliza_para_maiusculas():
    assert regras.patrimonio(" brb-12 ") == "BRB-12"
    assert regras.patrimonio("  ") is None


def test_numero_aceita_formato_brasileiro():
    assert regras.numero("1.234,56") == 1234.56
    assert regras.numero("R$ 99,90") == 99.9
    assert regras.numero("") is None
    with pytest.raises(regras.Invalido):
        regras.numero("-5")
    with pytest.raises(regras.Invalido):
        regras.numero("abc")


def test_equipamento_exige_tipo():
    with pytest.raises(regras.Invalido):
        regras.equipamento_do_formulario({"patrimonio": "1"})
    limpo = regras.equipamento_do_formulario({"tipo": "Monitor", "condicao": "bom"})
    assert limpo["tipo"] == "Monitor" and limpo["status"] == "em_estoque"


def test_equipamento_recusa_situacao_e_condicao_invalidas():
    with pytest.raises(regras.Invalido):
        regras.equipamento_do_formulario({"tipo": "Monitor", "status": "sumiu"})
    with pytest.raises(regras.Invalido):
        regras.equipamento_do_formulario({"tipo": "Monitor", "condicao": "mais ou menos"})


def test_entrega_exige_pessoa():
    with pytest.raises(regras.Invalido):
        regras.confere_acao("entrega", None)
    assert regras.confere_acao("entrega", 7)["status"] == "com_colaborador"
    assert regras.confere_acao("devolucao", None)["status"] == "em_estoque"
    with pytest.raises(regras.Invalido):
        regras.confere_acao("teleportar", None)


# ───────────────────────── banco de mentira ─────────────────────────
class BancoFalso:
    def __init__(self):
        self.equipamentos: dict[int, dict] = {}
        self.pessoas: dict[int, dict] = {}
        self.movimentos: list[dict] = []
        self.proximo = 1
        self.usuario = {
            "id": 1, "email": "mateus@aprovasim.com", "nome": "Mateus",
            "papel": "supervisor", "ativo": True,
            "senha_hash": security.hash_senha("senha-de-teste"),
        }

    def id(self):
        self.proximo += 1
        return self.proximo


@pytest.fixture(autouse=True)
def nunca_fala_com_o_banco_de_verdade(monkeypatch):
    """Trava de segurança: teste que esquecer de trocar uma função de dados falha aqui,
    em vez de escrever no Supabase da empresa (já aconteceu durante o desenvolvimento)."""
    def proibido(*_a, **_k):
        raise AssertionError("teste tentou falar com o banco real")
    from app import db
    for nome in ("consultar", "um", "executar", "pool"):
        monkeypatch.setattr(db, nome, proibido)


@pytest.fixture
def banco(monkeypatch):
    b = BancoFalso()

    def equipamento(eid):
        return b.equipamentos.get(int(eid))

    def criar(d, usuario, origem_id=None):
        if d.get("patrimonio") and any(
                e["patrimonio"] == d["patrimonio"] for e in b.equipamentos.values()):
            raise type("UniqueViolation", (Exception,), {})("patrimonio duplicado")
        eid = b.id()
        novo = {**d, "id": eid, "origem_id": origem_id, "criado_por": usuario,
                "atualizado_por": usuario, "atualizado_em": "2026-11-20T10:00:00+00:00",
                "colaborador_nome": (b.pessoas.get(d.get("colaborador_id")) or {}).get("nome")}
        b.equipamentos[eid] = novo
        b.movimentos.append({"equipamento_id": eid, "acao": "cadastro", "origem_id": origem_id})
        return novo

    def mover(eid, acao, status, colaborador_id, setor, observacao, usuario, origem_id=None):
        e = b.equipamentos.get(int(eid))
        if not e:
            return None
        e.update(status=status, colaborador_id=colaborador_id,
                 colaborador_nome=(b.pessoas.get(colaborador_id) or {}).get("nome"),
                 setor=setor or e.get("setor"), atualizado_por=usuario)
        b.movimentos.append({"equipamento_id": int(eid), "acao": acao, "origem_id": origem_id})
        return e

    def achar_ou_criar(nome, setor=None, cargo=None, email=None):
        for p in b.pessoas.values():
            if p["nome"].lower() == nome.lower():
                return p
        pid = b.id()
        b.pessoas[pid] = {"id": pid, "nome": nome, "setor": setor, "cargo": cargo, "email": email,
                          "ativo": True, "itens": 0}
        return b.pessoas[pid]

    def trocar_senha(uid, senha_hash):
        b.usuario["senha_hash"] = senha_hash

    monkeypatch.setattr(dados, "usuario_por_email", lambda e: b.usuario if "mateus" in e else None)
    monkeypatch.setattr(dados, "usuario_por_id", lambda i: b.usuario)
    monkeypatch.setattr(dados, "trocar_senha", trocar_senha)
    monkeypatch.setattr(dados, "equipamento", equipamento)
    monkeypatch.setattr(dados, "equipamentos", lambda: list(b.equipamentos.values()))
    monkeypatch.setattr(dados, "colaboradores", lambda: list(b.pessoas.values()))
    monkeypatch.setattr(dados, "resumo", lambda: {"total": len(b.equipamentos)})
    monkeypatch.setattr(dados, "sugestoes", lambda: {"setores": [], "tipos": []})
    monkeypatch.setattr(dados, "ultimos_movimentos", lambda limite=120: b.movimentos[-limite:])
    monkeypatch.setattr(dados, "historico", lambda eid, limite=200:
                        [m for m in b.movimentos if m["equipamento_id"] == int(eid)])
    monkeypatch.setattr(dados, "criar_equipamento", criar)
    monkeypatch.setattr(dados, "movimentar", mover)
    monkeypatch.setattr(dados, "achar_ou_criar_colaborador", achar_ou_criar)
    monkeypatch.setattr(dados, "editar_colaborador", lambda cid, d: {**b.pessoas[cid], **d})
    monkeypatch.setattr(dados, "editar_equipamento",
                        lambda eid, d, usuario: b.equipamentos[int(eid)].update(d)
                        or b.equipamentos[int(eid)])
    monkeypatch.setattr(dados, "excluir_equipamento",
                        lambda eid: bool(b.equipamentos.pop(int(eid), None)))
    monkeypatch.setattr(dados, "por_origem", lambda o:
                        next((e for e in b.equipamentos.values() if e.get("origem_id") == o), None))
    monkeypatch.setattr(dados, "movimento_por_origem", lambda o:
                        next((m for m in b.movimentos if m.get("origem_id") == o), None))
    main._cache_usuarios.clear()
    return b


@pytest.fixture
def cliente(banco):
    c = TestClient(main.app)
    r = c.post("/api/login", json={"email": "mateus@aprovasim.com", "senha": "senha-de-teste"})
    assert r.status_code == 200
    return c


# ───────────────────────── rotas ─────────────────────────
def test_sem_login_nao_ve_nada(banco):
    c = TestClient(main.app)
    assert c.get("/api/dados").status_code == 401
    assert c.post("/api/equipamentos", json={"tipo": "Monitor"}).status_code == 401


def test_senha_errada_nao_entra(banco):
    c = TestClient(main.app)
    r = c.post("/api/login", json={"email": "mateus@aprovasim.com", "senha": "chute"})
    assert r.status_code == 401


def test_healthz_responde_sem_login():
    assert TestClient(main.app).get("/healthz").json()["ok"] is True


def test_cadastra_e_aparece_na_tela(cliente):
    r = cliente.post("/api/equipamentos", json={
        "patrimonio": "brb-1", "tipo": "Notebook", "setor": "Marketing", "condicao": "bom"})
    assert r.status_code == 200
    assert r.json()["equipamento"]["patrimonio"] == "BRB-1"
    tela = cliente.get("/api/dados").json()
    assert len(tela["equipamentos"]) == 1
    assert tela["eu"]["papel"] == "supervisor"


def test_patrimonio_repetido_volta_409(cliente):
    cliente.post("/api/equipamentos", json={"patrimonio": "BRB-9", "tipo": "Monitor"})
    r = cliente.post("/api/equipamentos", json={"patrimonio": "brb-9", "tipo": "Monitor"})
    assert r.status_code == 409
    assert "patrimônio" in r.json()["detail"]


def test_cadastro_com_pessoa_cria_colaborador(cliente):
    r = cliente.post("/api/equipamentos", json={
        "tipo": "Headset", "status": "com_colaborador", "colaborador_nome": "Ana Souza",
        "setor": "Atendimento"})
    assert r.status_code == 200
    assert r.json()["equipamento"]["colaborador_nome"] == "Ana Souza"
    assert len(cliente.get("/api/dados").json()["colaboradores"]) == 1


def test_cadastro_com_colaborador_sem_nome_recusa(cliente):
    r = cliente.post("/api/equipamentos", json={"tipo": "Mouse", "status": "com_colaborador"})
    assert r.status_code == 400


def test_reenvio_da_fila_nao_duplica(cliente):
    corpo = {"tipo": "Monitor", "origem_id": "bilhete-123"}
    primeiro = cliente.post("/api/equipamentos", json=corpo).json()
    segundo = cliente.post("/api/equipamentos", json=corpo).json()
    assert segundo["repetido"] is True
    assert segundo["equipamento"]["id"] == primeiro["equipamento"]["id"]
    assert len(cliente.get("/api/dados").json()["equipamentos"]) == 1


def test_entrega_e_devolucao(cliente):
    eid = cliente.post("/api/equipamentos", json={"tipo": "Notebook"}).json()["equipamento"]["id"]
    r = cliente.post(f"/api/equipamentos/{eid}/mover",
                     json={"acao": "entrega", "colaborador_nome": "João Lima"})
    assert r.json()["equipamento"]["status"] == "com_colaborador"
    r = cliente.post(f"/api/equipamentos/{eid}/mover", json={"acao": "devolucao"})
    assert r.json()["equipamento"]["status"] == "em_estoque"
    assert r.json()["equipamento"]["colaborador_id"] is None
    historico = cliente.get(f"/api/equipamentos/{eid}/historico").json()["historico"]
    assert [m["acao"] for m in historico] == ["cadastro", "entrega", "devolucao"]


def test_entrega_sem_pessoa_recusa(cliente):
    eid = cliente.post("/api/equipamentos", json={"tipo": "Notebook"}).json()["equipamento"]["id"]
    r = cliente.post(f"/api/equipamentos/{eid}/mover", json={"acao": "entrega"})
    assert r.status_code == 400


def test_mover_item_que_nao_existe_404(cliente):
    r = cliente.post("/api/equipamentos/9999/mover", json={"acao": "devolucao"})
    assert r.status_code == 404


def test_exportar_csv_tem_cabecalho_em_portugues(cliente):
    cliente.post("/api/equipamentos", json={"patrimonio": "BRB-7", "tipo": "Monitor"})
    r = cliente.get("/api/exportar.csv")
    assert r.status_code == 200
    linhas = r.text.splitlines()
    assert "Código de patrimônio" in linhas[0] and "Com quem está" in linhas[0]
    assert "BRB-7" in linhas[1]


def test_operador_nao_exclui(cliente, banco):
    eid = cliente.post("/api/equipamentos", json={"tipo": "Monitor"}).json()["equipamento"]["id"]
    banco.usuario["papel"] = "operador"
    main._cache_usuarios.clear()
    assert cliente.delete(f"/api/equipamentos/{eid}").status_code == 403
    banco.usuario["papel"] = "supervisor"
    main._cache_usuarios.clear()
    assert cliente.delete(f"/api/equipamentos/{eid}").status_code == 200


def test_troca_de_senha_derruba_o_cookie_antigo(cliente, banco):
    r = cliente.post("/api/senha", json={"atual": "senha-de-teste", "nova": "outra-senha-123"})
    assert r.status_code == 200
    antigo = TestClient(main.app)
    antigo.cookies.set(main.COOKIE, security.assinar(
        {"uid": 1, "ver": "versao-velha"}, ttl_s=3600))
    assert antigo.get("/api/dados").status_code == 401


# ───────────────────────── integração (Radar de Projetos) ─────────────────────────
@pytest.fixture
def integra(banco, monkeypatch):
    """Cliente sem login, mas com a chave de integração do Radar."""
    from app import config, dados as d
    monkeypatch.setattr(config, "CHAVES_INTEGRACAO", "radar=chave-de-teste")
    monkeypatch.setattr(d, "por_patrimonio", lambda pat: next(
        (e for e in banco.equipamentos.values()
         if (e.get("patrimonio") or "").upper() == (pat or "").upper().strip()), None))
    return TestClient(main.app)


def test_integracao_exige_chave(integra):
    assert integra.get("/api/integracao/estoque").status_code == 401
    r = integra.get("/api/integracao/estoque", headers={"X-Chave": "chute"})
    assert r.status_code == 401


def test_integracao_le_estoque_sem_expor_valor(integra, cliente):
    cliente.post("/api/equipamentos", json={
        "patrimonio": "BRB-50", "tipo": "Notebook", "setor": "Comercial",
        "valor": "4200,00", "observacao": "arranhado na tampa"})
    r = integra.get("/api/integracao/estoque", headers={"X-Chave": "chave-de-teste"})
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["disponivel_por_tipo"] == {"Notebook": 1}
    item = corpo["itens"][0]
    assert item["patrimonio"] == "BRB-50"
    assert "valor" not in item and "observacao" not in item


def test_integracao_entrega_fecha_pedido_do_radar(integra, cliente):
    cliente.post("/api/equipamentos", json={"patrimonio": "BRB-51", "tipo": "Monitor"})
    r = integra.post("/api/integracao/entregar",
                     headers={"X-Chave": "chave-de-teste"},
                     json={"patrimonio": "brb-51", "colaborador_nome": "Ana Souza",
                           "setor": "CX", "por": "mateus@aprovasim.com",
                           "origem_id": "pedido-77"})
    assert r.status_code == 200
    assert r.json()["acao"] == "entrega"
    assert r.json()["equipamento"]["colaborador_nome"] == "Ana Souza"
    # repetir a mesma chamada não move o item de novo
    repetido = integra.post("/api/integracao/entregar",
                            headers={"X-Chave": "chave-de-teste"},
                            json={"patrimonio": "brb-51", "colaborador_nome": "Ana Souza",
                                  "origem_id": "pedido-77"})
    assert repetido.json() == {"repetido": True}


def test_integracao_entrega_item_inexistente(integra):
    r = integra.post("/api/integracao/entregar", headers={"X-Chave": "chave-de-teste"},
                     json={"patrimonio": "NAO-EXISTE", "colaborador_nome": "Ana"})
    assert r.status_code == 404


def test_integracao_entrega_exige_pessoa(integra, cliente):
    cliente.post("/api/equipamentos", json={"patrimonio": "BRB-52", "tipo": "Mouse"})
    r = integra.post("/api/integracao/entregar", headers={"X-Chave": "chave-de-teste"},
                     json={"patrimonio": "BRB-52"})
    assert r.status_code == 400
