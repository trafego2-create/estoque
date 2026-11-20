"""Senhas (scrypt) e cookie de sessão assinado. Mesmo padrão do Radar de Projetos e do Brabo Send."""
import base64
import hashlib
import hmac
import json
import os
import time

from . import config


def hash_senha(senha: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(senha.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(h).decode()


def conferir_senha(senha: str, guardado: str | None) -> bool:
    if not guardado or not senha:
        return False
    tipo, _, resto = guardado.partition("$")
    if tipo != "scrypt":
        return False
    salt_b64, _, h_b64 = resto.partition("$")
    h = hashlib.scrypt(senha.encode(), salt=base64.b64decode(salt_b64), n=2**14, r=8, p=1, dklen=32)
    return hmac.compare_digest(h, base64.b64decode(h_b64))


def versao_senha(guardado: str | None) -> str:
    """Muda quando a senha muda: sessões antigas deixam de valer."""
    return hashlib.sha256((guardado or "").encode()).hexdigest()[:12]


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _assinatura(payload: str) -> str:
    return _b64(hmac.new(config.SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).digest())


def assinar(dados: dict, ttl_s: int) -> str:
    payload = _b64(json.dumps({**dados, "exp": int(time.time()) + ttl_s}, separators=(",", ":")).encode())
    return payload + "." + _assinatura(payload)


def ler_assinado(token: str | None) -> dict | None:
    if not token or "." not in token or not config.SESSION_SECRET:
        return None
    payload, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(sig, _assinatura(payload)):
        return None
    try:
        dados = json.loads(_unb64(payload))
    except (ValueError, json.JSONDecodeError):
        return None
    if int(dados.get("exp", 0)) < time.time():
        return None
    return dados
