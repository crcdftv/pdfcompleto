"""
Configurações centrais do PDFCompleto.
Todas as constantes, paths e configurações ficam aqui.
"""
import os
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
SESSION_DIR = os.path.join(BASE_DIR, '.flask_session')
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
OCR_OUTPUT_FOLDER = os.path.join(BASE_DIR, 'ocr_outputs')
SIGNED_FOLDER = os.path.join(BASE_DIR, 'signed')
COMPRESSED_FOLDER = os.path.join(BASE_DIR, 'compressed')

# --- Extensões Permitidas ---
ALLOWED_EXT = {'.pdf'}

# --- Configuração Tesseract OCR ---
_tesseract_paths = [
    r'\\SRVSQL\\tesseract-OCR\\tesseract.exe',
    r'\\SRVSQL\tesseract-OCR\tesseract.exe',
    r'C:\Program Files\Tesseract-OCR\tesseract.exe',
    r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
    os.path.join(BASE_DIR, 'Tesseract-OCR', 'tesseract.exe'),
]

_tessdata_paths = [
    r'\\SRVSQL\\Tesseract-OCR\\tessdata',
    r'\\SRVSQL\tesseract-OCR\tessdata',
    r'C:\Program Files\Tesseract-OCR\tessdata',
    r'C:\Program Files (x86)\Tesseract-OCR\tessdata',
    os.path.join(BASE_DIR, 'Tesseract-OCR', 'tessdata'),
]


def get_tesseract_cmd():
    """Retorna o caminho do executável do Tesseract."""
    return next(
        (p for p in _tesseract_paths if os.path.isfile(p)),
        _tesseract_paths[0]
    )


def get_tessdata_prefix():
    """Retorna o caminho do diretório tessdata."""
    return next(
        (p for p in _tessdata_paths if os.path.isdir(p)),
        _tessdata_paths[0]
    )


def _ensure_dir(path):
    """Cria diretório com teste de escrita; fallback para LOCALAPPDATA/temp."""
    try:
        os.makedirs(path, exist_ok=True)
        testfile = os.path.join(path, '.write_test')
        with open(testfile, 'w', encoding='utf-8') as f:
            f.write('ok')
        os.remove(testfile)
        return path
    except Exception:
        la = os.environ.get('LOCALAPPDATA')
        base = os.path.join(la, 'pdfcompleto') if la else os.path.join(tempfile.gettempdir(), 'pdfcompleto')
        final = os.path.join(base, os.path.basename(path))
        os.makedirs(final, exist_ok=True)
        return final


# Cria diretórios
os.makedirs(SESSION_DIR, exist_ok=True)
UPLOAD_FOLDER = _ensure_dir(UPLOAD_FOLDER)
OCR_OUTPUT_FOLDER = _ensure_dir(OCR_OUTPUT_FOLDER)
SIGNED_FOLDER = _ensure_dir(SIGNED_FOLDER)
COMPRESSED_FOLDER = _ensure_dir(COMPRESSED_FOLDER)
