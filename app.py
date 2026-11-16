# app.py
from flask import (Flask, render_template, request, jsonify, send_from_directory, session,
                   send_file, url_for, abort, Response, stream_with_context, redirect)
from flask_session import Session
import os, tempfile
import fitz  # PyMuPDF
import io
import concurrent.futures
from PIL import Image
try:
    import pytesseract
except Exception:
    pytesseract = None
from PyPDF2 import PdfMerger, PdfReader, PdfWriter
import threading
import time
import re
import json
import subprocess
import requests
import base64
from datetime import datetime
import uuid
import sys
from werkzeug.utils import secure_filename
from pdf2docx import Converter
import logging
from logging.handlers import RotatingFileHandler
from apscheduler.schedulers.background import BackgroundScheduler
from pdf2image import convert_from_path
from zipfile import ZipFile, ZIP_DEFLATED
from PIL import Image, UnidentifiedImageError
import shutil
import img2pdf
import secrets

# --- Módulos internos ---
from core.config import (
    BASE_DIR, DATA_DIR, SESSION_DIR, UPLOAD_FOLDER, OCR_OUTPUT_FOLDER,
    SIGNED_FOLDER, COMPRESSED_FOLDER, ALLOWED_EXT,
    get_tesseract_cmd, get_tessdata_prefix,
)
from core.utils import (
    resolve_pdf_path, is_pdf_filename, gerar_iniciais, get_local_ip,
)
from core import presence
from routes.upload import upload_bp, limpar_pastas
from routes.ocr import ocr_bp
from routes.compress import compress_bp
from routes.excel import excel_bp, limpar_excel
from routes.signing import signing_bp, set_pkcs11_service
from routes.editing import editing_bp
from routes.conversions import conversions_bp, limpar_conversions
from routes.manipulation import manipulation_bp

# Configurar logging com rotação de arquivo.
# O log fica na pasta de DADOS (na VPS: /var/lib/pdfcompleto/logs), e nao no
# codigo: assim o app continua funcionando mesmo se /opt/pdfcompleto for
# somente-leitura ou tiver sido criado por outro usuario.
LOG_DIR = os.path.join(DATA_DIR, 'logs')
try:
    os.makedirs(LOG_DIR, exist_ok=True)
except OSError:
    LOG_DIR = os.path.join(BASE_DIR, 'logs')
    os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, 'pdfcompleto.log')

_handlers = [logging.StreamHandler()]
try:
    _handlers.insert(0, RotatingFileHandler(
        LOG_FILE, maxBytes=5*1024*1024, backupCount=5, encoding='utf-8'))
except OSError as e:
    # Sem permissao para o arquivo de log: NAO pode derrubar o servico.
    # Segue so com o log no console (systemd/journalctl).
    print(f"AVISO: nao foi possivel abrir o arquivo de log "
          f"({LOG_FILE}): {e}. Usando apenas o console.")
    LOG_FILE = ''

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=_handlers
)
logger = logging.getLogger(__name__)

try:
    import pkcs11_service
except ImportError:
    print("ERRO CRÍTICO: Não foi possível importar pkcs11_service.py.")
    print(f"Caminhos de busca atuais: {sys.path}")
    pkcs11_service = None

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)

app.config['UPLOAD_FOLDER']     = UPLOAD_FOLDER
app.config['OCR_OUTPUT_FOLDER'] = OCR_OUTPUT_FOLDER
app.config['SIGNED_FOLDER']     = SIGNED_FOLDER
app.config['COMPRESSED_FOLDER'] = COMPRESSED_FOLDER
# Segredo das sessoes: em producao vem do ambiente (VPS), senao um valor
# aleatorio por start (nunca fixo no codigo).
SECRET_KEY = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
app.secret_key = SECRET_KEY

# Registrar Blueprints
app.register_blueprint(upload_bp)
app.register_blueprint(ocr_bp)
app.register_blueprint(compress_bp)
app.register_blueprint(excel_bp)
app.register_blueprint(signing_bp)
app.register_blueprint(editing_bp)
app.register_blueprint(conversions_bp)
app.register_blueprint(manipulation_bp)

# Configurar serviço PKCS#11 para o Blueprint de assinatura
set_pkcs11_service(pkcs11_service)

# Configuração Tesseract
pytesseract.pytesseract.tesseract_cmd = get_tesseract_cmd()
os.environ['TESSDATA_PREFIX'] = get_tessdata_prefix()

# O cookie seguro fica habilitado explicitamente na VPS. Em desenvolvimento
# local HTTP ele permanece desabilitado para não quebrar o fluxo do desktop.
SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0").strip().lower() in {
    "1", "true", "yes", "on"
}

app.config.update(
    SECRET_KEY=SECRET_KEY,
    SESSION_TYPE="filesystem",
    SESSION_FILE_DIR=SESSION_DIR,
    SESSION_PERMANENT=False,
    SESSION_COOKIE_SECURE=SESSION_COOKIE_SECURE,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE=os.environ.get("SESSION_COOKIE_SAMESITE", "Lax"),
    SESSION_COOKIE_PATH="/",
)
Session(app)


# Presença: cada requisição renova a sessão do navegador (ver core/presence.py)
@app.before_request
def _renovar_presenca():
    presence.registrar()


@app.route('/sessoes')
def sessoes():
    """Quantas sessões (navegadores) estão ativas agora."""
    return jsonify({"ativos": presence.ativos()})


# Error handlers globais
@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Recurso não encontrado"}), 404

@app.errorhandler(400)
def bad_request(e):
    return jsonify({"error": "Requisição inválida"}), 400

@app.errorhandler(500)
def internal_error(e):
    logger.error(f"Erro interno: {e}")
    return jsonify({"error": "Erro interno do servidor"}), 500


def _drain_request_stream_windows():
    """Drena o stream de requisição no Windows para evitar erro 431."""
    try:
        if request.stream:
            while True:
                chunk = request.stream.read(4096)
                if not chunk:
                    break
    except Exception:
        pass


@app.route('/load_pdf_session', methods=['POST'])
def load_pdf_session():
    if 'pdf' not in request.files:
        return jsonify({"error": "Nenhum PDF enviado"}), 400
    uploaded_file = request.files['pdf']
    session['original_pdf_bytes'] = uploaded_file.read()
    session['redactions'] = []
    return jsonify({"message": "PDF carregado para edição"}), 200


@app.route('/progress')
def progress():
    def generate():
        total_pages = 10
        for i in range(total_pages):
            time.sleep(1)
            percent = int(((i + 1) / total_pages) * 100)
            yield f"data: {percent}\n\n"
        yield "data: done\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


@app.route('/health')
def health_check():
    """Health check endpoint — HTML bonito ou JSON."""
    health = _collect_health_data()

    # Se aceitar JSON, retorna JSON
    if request.accept_mimetypes.best_match(['application/json', 'text/html']) == 'application/json':
        status_code = 200 if health["status"] == "ok" else 503
        return jsonify(health), status_code

    # Senão, retorna HTML bonitinho
    status_color = "#00ff88" if health["status"] == "ok" else "#ff4444"
    status_label = "OPERATIONAL" if health["status"] == "ok" else "DEGRADED"
    status_icon = "&#9679;" if health["status"] == "ok" else "&#9650;"

    checks_html = ""
    for name, check in health["checks"].items():
        s = check.get("status", "unknown")
        icon = "&#9679;" if s == "ok" else ("&#9650;" if s == "warning" else "&#10007;")
        color = "#00ff88" if s == "ok" else ("#ffaa00" if s == "warning" else "#ff4444")
        label = name.replace("_", " ").replace("folder ", "").upper()
        detail = ""
        if "free_gb" in check:
            detail = f'{check["used_pct"]}% used &middot; {check["free_gb"]} GB free of {check["total_gb"]} GB'
        elif "path" in check:
            detail = check["path"]
        elif "size_mb" in check:
            detail = f'{check["size_mb"]} MB'
        checks_html += f'''
        <div class="check-row">
            <span class="check-icon" style="color:{color}">{icon}</span>
            <span class="check-name">{label}</span>
            <span class="check-detail">{detail}</span>
            <span class="check-status" style="color:{color}">{s.upper()}</span>
        </div>'''

    ts = health["timestamp"].replace("T", " ").split(".")[0]

    html = f'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PDFCompleto — System Status</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    background: #0a0e17;
    color: #c9d1d9;
    font-family: 'Inter', sans-serif;
    min-height: 100vh;
    display: flex;
    justify-content: center;
    align-items: center;
    padding: 20px;
  }}
  .container {{
    width: 100%;
    max-width: 720px;
  }}
  .header {{
    text-align: center;
    margin-bottom: 32px;
  }}
  .header h1 {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 28px;
    color: #e6edf3;
    letter-spacing: -0.5px;
  }}
  .header .subtitle {{
    font-size: 13px;
    color: #484f58;
    margin-top: 4px;
    font-family: 'JetBrains Mono', monospace;
  }}
  .status-banner {{
    background: #0d1117;
    border: 1px solid #1a2332;
    border-radius: 12px;
    padding: 24px 32px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 24px;
  }}
  .status-left {{
    display: flex;
    align-items: center;
    gap: 14px;
  }}
  .status-dot {{
    font-size: 32px;
    line-height: 1;
    animation: pulse 2s ease-in-out infinite;
  }}
  @keyframes pulse {{
    0%, 100% {{ opacity: 1; }}
    50% {{ opacity: 0.5; }}
  }}
  .status-label {{
    font-size: 20px;
    font-weight: 700;
    letter-spacing: 2px;
  }}
  .status-time {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    color: #484f58;
    text-align: right;
  }}
  .status-time .ts {{
    color: #8b949e;
    font-size: 13px;
  }}
  .checks {{
    background: #0d1117;
    border: 1px solid #1a2332;
    border-radius: 12px;
    overflow: hidden;
  }}
  .checks-header {{
    padding: 14px 24px;
    border-bottom: 1px solid #1a2332;
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    color: #484f58;
    letter-spacing: 1.5px;
    text-transform: uppercase;
  }}
  .check-row {{
    display: flex;
    align-items: center;
    padding: 14px 24px;
    border-bottom: 1px solid #12171f;
    transition: background 0.15s;
  }}
  .check-row:last-child {{ border-bottom: none; }}
  .check-row:hover {{ background: #111820; }}
  .check-icon {{
    font-size: 10px;
    margin-right: 14px;
    width: 16px;
    text-align: center;
  }}
  .check-name {{
    font-weight: 600;
    font-size: 14px;
    color: #e6edf3;
    min-width: 120px;
  }}
  .check-detail {{
    flex: 1;
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    color: #484f58;
    padding: 0 16px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .check-status {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
  }}
  .footer {{
    text-align: center;
    margin-top: 24px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    color: #21262d;
  }}
  .footer a {{ color: #484f58; text-decoration: none; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>&#9881; PDFCompleto</h1>
    <div class="subtitle">SYSTEM STATUS MONITOR</div>
  </div>
  <div class="status-banner">
    <div class="status-left">
      <span class="status-dot" style="color:{status_color}">{status_icon}</span>
      <span class="status-label" style="color:{status_color}">{status_label}</span>
    </div>
    <div class="status-time">
      LAST CHECK<br>
      <span class="ts">{ts}</span>
    </div>
  </div>
  <div class="checks">
    <div class="checks-header">SERVICE CHECKS</div>
    {checks_html}
  </div>
  <div class="footer">
    PDFCompleto v1.0 &middot; <a href="/health.json">JSON</a>
  </div>
</div>
</body>
</html>'''

    status_code = 200 if health["status"] == "ok" else 503
    return html, status_code


def _collect_health_data():
    """Coleta dados de saúde do sistema (usado por /health e /health.json)."""
    import shutil
    health = {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "checks": {}
    }

    try:
        disk = shutil.disk_usage(BASE_DIR)
        health["checks"]["disk"] = {
            "status": "ok",
            "total_gb": round(disk.total / (1024**3), 1),
            "free_gb": round(disk.free / (1024**3), 1),
            "used_pct": round((disk.used / disk.total) * 100, 1)
        }
        if disk.free < 1024**3:
            health["checks"]["disk"]["status"] = "warning"
            health["status"] = "degraded"
    except Exception as e:
        health["checks"]["disk"] = {"status": "error", "msg": str(e)}
        health["status"] = "degraded"

    try:
        tesseract_path = get_tesseract_cmd()
        health["checks"]["tesseract"] = {
            "status": "ok" if os.path.isfile(tesseract_path) else "error",
            "path": tesseract_path
        }
        if not os.path.isfile(tesseract_path):
            health["status"] = "degraded"
    except Exception as e:
        health["checks"]["tesseract"] = {"status": "error", "msg": str(e)}
        health["status"] = "degraded"

    folders = {
        "uploads": UPLOAD_FOLDER,
        "ocr_outputs": OCR_OUTPUT_FOLDER,
        "signed": SIGNED_FOLDER,
        "compressed": COMPRESSED_FOLDER,
    }
    for name, path in folders.items():
        health["checks"][f"folder_{name}"] = {
            "status": "ok" if os.path.isdir(path) else "error",
            "path": path
        }
        if not os.path.isdir(path):
            health["status"] = "degraded"

    health["checks"]["pkcs11"] = {
        "status": "ok" if pkcs11_service else "unavailable",
    }

    health["checks"]["log_file"] = {
        "status": "ok" if LOG_FILE else "console-only",
        "path": LOG_FILE or "(somente console/journalctl)",
        "size_mb": round(os.path.getsize(LOG_FILE) / (1024**2), 2)
                  if LOG_FILE and os.path.isfile(LOG_FILE) else 0
    }

    return health


@app.route('/health.json')
def health_check_json():
    """Health check JSON."""
    health = _collect_health_data()
    status_code = 200 if health["status"] == "ok" else 503
    return jsonify(health), status_code


# Agenda limpeza a cada 1h (usa limpar_pastas do routes/upload.py)
scheduler = BackgroundScheduler()


def limpar_jobs_expirados():
    """Remove jobs de conversão órfãos dos blueprints."""
    try:
        limpar_conversions()
    except Exception:
        logger.exception('Falha ao limpar jobs de conversão')
    try:
        limpar_excel()
    except Exception:
        logger.exception('Falha ao limpar jobs de Excel')


scheduler.add_job(func=limpar_pastas, trigger="interval", hours=1)
scheduler.add_job(func=limpar_jobs_expirados, trigger="interval", minutes=15)
scheduler.start()


print("app.py carregado com sucesso ate aqui")

# --- Ponto de Entrada da Aplicação ---
if __name__ == '__main__':
    import sys

    port = 5000

    # ── Garante instância única (porta HTTP + socket-cadeado) ──────────────
    from core.utils import garantir_instancia_unica
    _ok, _motivo, _lock_sock = garantir_instancia_unica(port=port)
    if not _ok:
        print(f"⚠️  {_motivo}. Encerrando.")
        sys.exit(0)
    # ─────────────────────────────────────────────────────────────────────────

    local_ip = get_local_ip()

    print("Rotas registradas:")
    for rule in app.url_map.iter_rules():
        print(rule)

    print(f"Servidor Flask iniciando...")
    print(f"Acesse localmente: http://127.0.0.1:{port}")
    print(f"Acesse na rede: http://{local_ip}:{port}")
    print(f"Pasta uploads: {os.path.abspath(app.config['UPLOAD_FOLDER'])}")
    print(f"Pasta OCR: {os.path.abspath(app.config['OCR_OUTPUT_FOLDER'])}")
    print(f"Pasta signed: {os.path.abspath(app.config['SIGNED_FOLDER'])}")

    app.run(
        host='0.0.0.0',
        port=port,
        debug=False,
        use_reloader=False
    )
