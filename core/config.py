"""
Configurações centrais do PDFCompleto.
Todas as constantes, paths e configurações ficam aqui.
"""
import os
import shutil
import sys
import tempfile


def _base_dir():
    """Diretório base, lidando com PyInstaller/cx_Freeze."""
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        internal = os.path.join(exe_dir, "_internal")
        return internal if os.path.isdir(internal) else exe_dir
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


BASE_DIR = _base_dir()

# Garante que o diretório do projeto esteja no path
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

# --- Diretórios de Trabalho ---
# PDFCOMPLETO_DATA_DIR separa os dados do código (na VPS, por exemplo,
# /var/lib/pdfcompleto), mantendo o repositório somente-leitura.
DATA_DIR = os.environ.get('PDFCOMPLETO_DATA_DIR') or BASE_DIR

SESSION_DIR = os.path.join(DATA_DIR, '.flask_session')
UPLOAD_FOLDER = os.path.join(DATA_DIR, 'uploads')
OCR_OUTPUT_FOLDER = os.path.join(DATA_DIR, 'ocr_outputs')
SIGNED_FOLDER = os.path.join(DATA_DIR, 'signed')
COMPRESSED_FOLDER = os.path.join(DATA_DIR, 'compressed')

# --- Extensões Permitidas ---
ALLOWED_EXT = {'.pdf'}

# --- Configuração Tesseract OCR ---
# A ordem importa: primeiro o ambiente (TESSERACT_CMD), depois os caminhos
# da rede Windows, depois a instalação local e por último o Linux/Unix.
_tesseract_paths = [
    os.environ.get('TESSERACT_CMD', ''),
    r'\\SRVSQL\\tesseract-OCR\\tesseract.exe',
    r'\\SRVSQL\tesseract-OCR\tesseract.exe',
    r'C:\Program Files\Tesseract-OCR\tesseract.exe',
    r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
    os.path.join(BASE_DIR, 'Tesseract-OCR', 'tesseract.exe'),
    '/usr/bin/tesseract',
    '/usr/local/bin/tesseract',
    '/opt/tesseract/bin/tesseract',
]

_tessdata_paths = [
    os.environ.get('TESSDATA_PREFIX', ''),
    r'\\SRVSQL\\tesseract-OCR\\tessdata',
    r'\\SRVSQL\tesseract-OCR\tessdata',
    r'C:\Program Files\Tesseract-OCR\tessdata',
    r'C:\Program Files (x86)\Tesseract-OCR\tessdata',
    os.path.join(BASE_DIR, 'Tesseract-OCR', 'tessdata'),
    '/usr/share/tesseract-ocr/5/tessdata',
    '/usr/share/tesseract-ocr/4.00/tessdata',
    '/usr/share/tesseract-ocr/tessdata',
    '/usr/local/share/tessdata',
]


def get_tesseract_cmd():
    """Retorna o caminho do executável do Tesseract."""
    for p in _tesseract_paths:
        if p and os.path.isfile(p):
            return p
    # último recurso: procura no PATH do sistema (Linux/VPS)
    achado = shutil.which('tesseract')
    return achado or '/usr/bin/tesseract'


def get_tessdata_prefix():
    """Retorna o caminho do diretório tessdata."""
    for p in _tessdata_paths:
        if p and os.path.isdir(p):
            return p
    return '/usr/share/tesseract-ocr/5/tessdata'


def _ensure_dir(path):
    """Cria diretório com teste de escrita; fallback para pasta do usuário."""
    try:
        os.makedirs(path, exist_ok=True)
        testfile = os.path.join(path, '.write_test')
        with open(testfile, 'w', encoding='utf-8') as f:
            f.write('ok')
        os.remove(testfile)
        return path
    except Exception:
        la = os.environ.get('LOCALAPPDATA')
        if la:
            base = os.path.join(la, 'pdfcompleto')
        else:
            home = os.environ.get('HOME') or tempfile.gettempdir()
            base = os.path.join(home, '.pdfcompleto')
        final = os.path.join(base, os.path.basename(path))
        os.makedirs(final, exist_ok=True)
        return final


# Cria diretórios
os.makedirs(SESSION_DIR, exist_ok=True)
UPLOAD_FOLDER = _ensure_dir(UPLOAD_FOLDER)
OCR_OUTPUT_FOLDER = _ensure_dir(OCR_OUTPUT_FOLDER)
SIGNED_FOLDER = _ensure_dir(SIGNED_FOLDER)
COMPRESSED_FOLDER = _ensure_dir(COMPRESSED_FOLDER)
