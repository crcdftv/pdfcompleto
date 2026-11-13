"""
Rotas de upload e serving de arquivos.
"""
import os
import time
import shutil
import logging

from flask import (
    Blueprint, render_template, request, jsonify, send_from_directory,
    session, redirect, url_for, abort,
)
from werkzeug.utils import secure_filename

from core.config import (
    UPLOAD_FOLDER, OCR_OUTPUT_FOLDER, SIGNED_FOLDER, COMPRESSED_FOLDER,
)
from core.utils import is_pdf_filename

logger = logging.getLogger(__name__)

upload_bp = Blueprint('upload', __name__)


@upload_bp.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Recurso não encontrado"}), 404

@upload_bp.errorhandler(400)
def bad_request(e):
    return jsonify({"error": "Requisição inválida"}), 400

@upload_bp.errorhandler(500)
def internal_error(e):
    logger.error(f"Erro interno: {e}")
    return jsonify({"error": "Erro interno do servidor"}), 500


@upload_bp.route('/')
def index():
    """Serve a página principal do frontend (index.html)."""
    return render_template('index.html')


@upload_bp.route('/open')
def open_local_pdf():
    """Abre um PDF local do sistema de arquivos."""
    file_path = request.args.get('path', '')
    if not file_path:
        return redirect(url_for('upload.index'))

    file_path = os.path.normpath(file_path)

    if not os.path.isfile(file_path):
        return jsonify({"error": f"Arquivo não encontrado: {file_path}"}), 404

    if not file_path.lower().endswith('.pdf'):
        return jsonify({"error": "O arquivo não é um PDF"}), 400

    try:
        original_name = os.path.basename(file_path)
        timestamp = str(int(time.time() * 1000))
        safe_name = secure_filename(f"{timestamp}_{original_name}")
        if not safe_name:
            safe_name = f"{timestamp}_arquivo.pdf"

        dest = os.path.join(UPLOAD_FOLDER, safe_name)
        shutil.copy2(file_path, dest)

        return redirect(url_for('upload.index', file=safe_name))

    except Exception as e:
        logger.exception("Erro ao abrir PDF local")
        return jsonify({"error": f"Erro ao abrir arquivo: {e}"}), 500


@upload_bp.route('/static/<path:filename>')
def static_files(filename):
    """Serve arquivos estáticos como CSS e JavaScript."""
    return send_from_directory('static', filename)


@upload_bp.route('/signed/<path:filename>')
def serve_signed_pdfs(filename):
    """Serve arquivos PDF assinados da pasta 'signed'."""
    return send_from_directory(SIGNED_FOLDER, filename)


@upload_bp.route('/ocr_outputs/<path:filename>')
def download_ocr_file(filename):
    """Serve arquivos da pasta 'ocr_outputs'."""
    return send_from_directory(OCR_OUTPUT_FOLDER, filename)


@upload_bp.route('/uploads/<path:filename>')
def serve_upload(filename):
    """Serve arquivos PDF da pasta 'uploads' (com proteção path-traversal)."""
    folder = UPLOAD_FOLDER
    full = os.path.abspath(os.path.join(folder, filename))
    if not full.startswith(os.path.abspath(folder)) or not os.path.isfile(full):
        abort(404)
    return send_from_directory(folder, filename, as_attachment=False, mimetype='application/pdf')


@upload_bp.route('/upload', methods=['POST'])
def upload_pdf():
    """Faz o upload de um arquivo PDF para a pasta 'uploads'."""
    try:
        pdf_file = request.files.get('pdf')

        if pdf_file is None or not pdf_file.filename:
            return jsonify({"error": "Nenhum arquivo enviado"}), 400

        original_filename = pdf_file.filename or ''
        cleaned = os.path.basename(original_filename).replace('\\', '/').split('/')[-1]
        cleaned = secure_filename(cleaned)
        cleaned = cleaned.encode('ascii', errors='ignore').decode('ascii')
        if not cleaned:
            cleaned = 'arquivo.pdf'

        if not is_pdf_filename(cleaned):
            return jsonify({"error": "O arquivo deve ser um PDF"}), 400

        timestamp = str(int(time.time() * 1000))
        safe_name = f"{timestamp}_{cleaned}"
        file_path = os.path.join(UPLOAD_FOLDER, safe_name)
        pdf_file.save(file_path)

        return jsonify({
            "file_path": safe_name,
            "file_url": f"/uploads/{safe_name}",
            "original_name": cleaned,
            "message": "Arquivo carregado com sucesso"
        }), 200

    except Exception as e:
        logger.exception("Erro no upload")
        return jsonify({"error": str(e)}), 500


@upload_bp.route('/available_files', methods=['GET'])
def list_available_files():
    """Lista os arquivos PDF disponíveis nas pastas de upload."""
    try:
        uploads = []
        if os.path.exists(UPLOAD_FOLDER):
            for filename in os.listdir(UPLOAD_FOLDER):
                if filename.lower().endswith('.pdf'):
                    file_path = os.path.join(UPLOAD_FOLDER, filename)
                    file_size = os.path.getsize(file_path)
                    if '_' in filename and filename.split('_', 1)[0].isdigit():
                        display_name = filename.split('_', 1)[1]
                    else:
                        display_name = filename
                    uploads.append({
                        'filename': filename,
                        'display_name': display_name,
                        'size': file_size,
                        'size_mb': round(file_size / (1024 * 1024), 2)
                    })
        return jsonify({
            "files": uploads,
            "count": len(uploads)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def limpar_pastas():
    """Remove arquivos com mais de 1h nas pastas de trabalho."""
    agora = time.time()
    limite = 60 * 60  # 1 hora
    pastas = [UPLOAD_FOLDER, OCR_OUTPUT_FOLDER, SIGNED_FOLDER]

    for pasta in pastas:
        for arquivo in os.listdir(pasta):
            caminho = os.path.join(pasta, arquivo)
            try:
                if os.path.isfile(caminho):
                    if agora - os.path.getmtime(caminho) > limite:
                        os.remove(caminho)
                        print(f"Removido: {caminho}")
            except Exception as e:
                print(f"Erro ao remover {caminho}: {e}")


@upload_bp.route("/limpar")
def limpar_agora():
    """Executa limpeza manual de arquivos antigos."""
    limpar_pastas()
    return "Limpeza manual executada!"
