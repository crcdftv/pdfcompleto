"""
Presença de sessões: quem está com a página aberta agora.

Não existe login no sistema, então a contagem vem de heartbeat: o navegador
consulta `/sessoes` de tempos em tempos e a própria consulta renova a
presença daquele navegador. Quem parou de perguntar (fechou a aba, caiu a
rede) expira sozinho depois de PRESENCA_TTL segundos.

Uma sessão = um navegador (cookie de sessão). Várias abas do mesmo navegador
contam como uma.
"""
import threading
import time
import uuid

from flask import session

# Segundos que uma sessão fica "ativa" sem renovar o heartbeat
PRESENCA_TTL = 120

_lock = threading.Lock()
_vistos = {}  # id da sessão -> epoch da última visita


def registrar():
    """Marca a sessão atual como presente. Chamar a cada requisição."""
    cliente_id = session.get('cliente_id')
    if not cliente_id:
        cliente_id = uuid.uuid4().hex
        session['cliente_id'] = cliente_id

    agora = time.time()
    with _lock:
        _vistos[cliente_id] = agora
        # limpa quem ficou para trás
        for chave, visto in list(_vistos.items()):
            if agora - visto > PRESENCA_TTL:
                del _vistos[chave]
    return cliente_id


def ativos():
    """Quantas sessões estão ativas neste momento."""
    agora = time.time()
    with _lock:
        return sum(1 for visto in _vistos.values() if agora - visto <= PRESENCA_TTL)
