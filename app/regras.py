"""Regras do estoque que não dependem do banco (ficam fáceis de testar)."""
from __future__ import annotations

STATUS = ["em_estoque", "com_colaborador", "manutencao", "emprestado", "baixado"]
CONDICOES = ["novo", "bom", "regular", "ruim", "defeito"]

# ação → para onde o item vai; exige_pessoa diz se a ação precisa de um colaborador
ACOES: dict[str, dict] = {
    "entrega":       {"status": "com_colaborador", "exige_pessoa": True,  "rotulo": "Entregue"},
    "transferencia": {"status": "com_colaborador", "exige_pessoa": True,  "rotulo": "Transferido"},
    "devolucao":     {"status": "em_estoque",      "exige_pessoa": False, "rotulo": "Devolvido ao estoque"},
    "manutencao":    {"status": "manutencao",      "exige_pessoa": False, "rotulo": "Enviado para manutenção"},
    "retorno":       {"status": "em_estoque",      "exige_pessoa": False, "rotulo": "Voltou da manutenção"},
    "baixa":         {"status": "baixado",         "exige_pessoa": False, "rotulo": "Baixado"},
}

# sugestões que aparecem na tela; a pessoa pode digitar qualquer outra coisa
TIPOS_SUGERIDOS = [
    "Notebook", "Desktop", "Monitor", "Teclado", "Mouse", "Headset", "Webcam", "Celular",
    "Chip", "Tablet", "Impressora", "Nobreak", "Roteador", "Switch", "Microfone", "Câmera",
    "Iluminação", "HD/SSD", "Pendrive", "Projetor", "TV", "Cadeira", "Mesa", "Outro",
]


class Invalido(ValueError):
    """Dado que o usuário mandou errado (virará HTTP 400)."""


def texto(valor, limite: int = 200) -> str | None:
    """Limpa um campo de texto: vazio vira None e o tamanho é limitado."""
    if valor is None:
        return None
    s = str(valor).strip()
    if not s:
        return None
    return s[:limite]


def patrimonio(valor) -> str | None:
    s = texto(valor, 60)
    return s.upper() if s else None


def numero(valor) -> float | None:
    if valor in (None, ""):
        return None
    s = str(valor).strip().replace("R$", "").replace(" ", "")
    if "," in s:  # 1.234,56 → 1234.56
        s = s.replace(".", "").replace(",", ".")
    try:
        v = float(s)
    except ValueError:
        raise Invalido("Valor inválido.")
    if v < 0:
        raise Invalido("Valor não pode ser negativo.")
    return round(v, 2)


def equipamento_do_formulario(d: dict) -> dict:
    """Valida e limpa o que veio da tela ao cadastrar/editar um equipamento."""
    tipo = texto(d.get("tipo"), 60)
    if not tipo:
        raise Invalido("Diga qual é o equipamento (ex.: Notebook).")

    condicao = (texto(d.get("condicao"), 20) or "bom").lower()
    if condicao not in CONDICOES:
        raise Invalido("Condição inválida.")

    status = (texto(d.get("status"), 30) or "em_estoque").lower()
    if status not in STATUS:
        raise Invalido("Situação inválida.")

    limpo = {
        "patrimonio": patrimonio(d.get("patrimonio")),
        "tipo": tipo,
        "descricao": texto(d.get("descricao"), 300),
        "marca": texto(d.get("marca"), 80),
        "modelo": texto(d.get("modelo"), 120),
        "serie": texto(d.get("serie"), 120),
        "setor": texto(d.get("setor"), 80),
        "localizacao": texto(d.get("localizacao"), 120),
        "condicao": condicao,
        "status": status,
        "valor": numero(d.get("valor")),
        "observacao": texto(d.get("observacao"), 1000),
    }
    return limpo


def confere_acao(acao: str, colaborador_id) -> dict:
    """Valida a movimentação pedida e devolve a regra correspondente."""
    regra = ACOES.get((acao or "").strip().lower())
    if not regra:
        raise Invalido("Movimentação desconhecida.")
    if regra["exige_pessoa"] and not colaborador_id:
        raise Invalido("Diga com qual colaborador o equipamento ficou.")
    return regra


def resumo_vazio() -> dict:
    return {"total": 0, **{s: 0 for s in STATUS}}
