"""
Funções utilitárias compartilhadas por todos os módulos.
"""
import os
import socket
from werkzeug.utils import secure_filename as _secure_filename

from core.config import UPLOAD_FOLDER, OCR_OUTPUT_FOLDER, ALLOWED_EXT


def resolve_pdf_path(pdf_filename_with_path):
    """
    Resolve o caminho completo de um PDF a partir do path web.
    Aceita '/uploads/arquivo.pdf', '/ocr_outputs/arquivo.pdf' ou só o nome.
    Retorna o caminho absoluto ou None se não encontrado.
    """
    if pdf_filename_with_path.startswith('/ocr_outputs/'):
        name = pdf_filename_with_path.replace('/ocr_outputs/', '')
        full = os.path.join(OCR_OUTPUT_FOLDER, name)
    elif pdf_filename_with_path.startswith('/uploads/'):
        name = pdf_filename_with_path.replace('/uploads/', '')
        full = os.path.join(UPLOAD_FOLDER, name)
    else:
        name = pdf_filename_with_path
        path_upload = os.path.join(UPLOAD_FOLDER, name)
        path_ocr = os.path.join(OCR_OUTPUT_FOLDER, name)
        if os.path.exists(path_ocr):
            return path_ocr
        elif os.path.exists(path_upload):
            return path_upload
        else:
            return None

    return full if os.path.exists(full) else None


def is_pdf_filename(name):
    """Valida se o nome do arquivo tem extensão .pdf."""
    return os.path.splitext(name)[1].lower() in ALLOWED_EXT


def gerar_iniciais(nome_completo):
    """Gera as iniciais de um nome completo (primeiro + último)."""
    palavras = nome_completo.split()
    if not palavras:
        return ""
    if len(palavras) == 1:
        return palavras[0][0].upper()
    return (palavras[0][0] + palavras[-1][0]).upper()


def get_local_ip():
    """Obtém o IP local da máquina via socket UDP."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        local_ip = sock.getsockname()[0]
        sock.close()
        return local_ip
    except Exception:
        return "127.0.0.1"


# Porta usada como "cadeado" de instância única
LOCK_PORT = 6002


def garantir_instancia_unica(port=5000):
    """Garante que apenas uma instância do servidor esteja rodando.

    Verifica a porta HTTP e reserva um socket-cadeado.
    O chamador DEVE manter a referência do socket retornado aberta.

    Retorna (ok: bool, motivo: str, lock_sock: socket ou None).
    """
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        probe.bind(('0.0.0.0', port))
        probe.close()
    except OSError:
        return False, f'Porta {port} já está em uso por outra instância do serviço', None

    try:
        lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        lock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        lock.bind(('127.0.0.1', LOCK_PORT))
    except OSError:
        return False, 'Outra instância do serviço já está rodando (cadeado ativo)', None

    return True, 'ok', lock
