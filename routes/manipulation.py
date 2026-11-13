"""
Rotas de manipulação de PDF (juntar, dividir).
"""
import os
import io
import logging

import fitz  # PyMuPDF
import pikepdf
from flask import Blueprint, request, jsonify, send_file
from werkzeug.utils import secure_filename
from zipfile import ZipFile, ZIP_DEFLATED

from core.config import UPLOAD_FOLDER, OCR_OUTPUT_FOLDER

logger = logging.getLogger(__name__)

manipulation_bp = Blueprint('manipulation', __name__)


@manipulation_bp.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Recurso não encontrado"}), 404

@manipulation_bp.errorhandler(400)
def bad_request(e):
    return jsonify({"error": "Requisição inválida"}), 400

@manipulation_bp.errorhandler(500)
def internal_error(e):
    logger.error(f"Erro interno: {e}")
    return jsonify({"error": "Erro interno do servidor"}), 500


@manipulation_bp.route("/juntar_pdfs", methods=["POST"])
def juntar_pdfs():
    arquivos_originais = request.files.getlist("pdfs")
    nome = request.form.get("nome", "resultado")

    if not arquivos_originais or len(arquivos_originais) < 2:
        return "Envie pelo menos 2 PDFs", 400

    file_order_str = request.form.get("file_order", "")
    if file_order_str:
        ordem = [name.strip() for name in file_order_str.split(",") if name.strip()]
        index_map = {name: i for i, name in enumerate(ordem)}
        arquivos_ordenados = sorted(
            arquivos_originais,
            key=lambda f: index_map.get(f.filename, len(ordem))
        )
    else:
        arquivos_ordenados = list(arquivos_originais)

    output = io.BytesIO()
    merged = pikepdf.new()

    for arquivo in arquivos_ordenados:
        pdf_content = arquivo.read()

        if not pdf_content:
            continue

        try:
            src = pikepdf.open(io.BytesIO(pdf_content))
            merged.pages.extend(src.pages)
            src.close()
        except Exception as e:
            continue

    merged.save(output)
    merged.close()
    output.seek(0)

    return send_file(output,
                     as_attachment=True,
                     download_name=f"{nome}.pdf",
                     mimetype="application/pdf")


@manipulation_bp.route('/split_pdf', methods=['POST'])
def split_pdf():
    """
    Divide um PDF em múltiplos arquivos conforme intervalos fornecidos.

    Payload JSON:
    {
      "pdf_path": "timestamp_arquivo.pdf",
      "intervals": [
        {"start": 1, "end": 12},
        {"start": 13, "end": 20},
        {"start": 21, "end": 30}
      ]
    }

    Retorna um ZIP com um PDF por intervalo, nomeados parte_1_pags_1-12.pdf...
    """
    data = request.get_json(force=True, silent=True) or {}

    pdf_path_raw = (data.get("pdf_path") or "").strip()
    intervals    = data.get("intervals", [])

    if not pdf_path_raw:
        return jsonify({"error": "pdf_path nao fornecido"}), 400
    if not intervals:
        return jsonify({"error": "Nenhum intervalo fornecido"}), 400

    filename = secure_filename(pdf_path_raw.split("/")[-1])
    pdf_full_path = os.path.join(UPLOAD_FOLDER, filename)
    if not os.path.isfile(pdf_full_path):
        pdf_full_path = os.path.join(OCR_OUTPUT_FOLDER, filename)
    if not os.path.isfile(pdf_full_path):
        return jsonify({"error": f"Arquivo nao encontrado: {filename}"}), 404

    try:
        src   = fitz.open(pdf_full_path)
        total = src.page_count

        zip_buf = io.BytesIO()
        with ZipFile(zip_buf, "w", ZIP_DEFLATED) as zf:
            for i, interval in enumerate(intervals, start=1):
                start = int(interval.get("start", 1))
                end   = int(interval.get("end", total))
                start = max(1, min(start, total))
                end   = max(start, min(end, total))

                part = fitz.open()
                part.insert_pdf(src, from_page=start - 1, to_page=end - 1)
                part_buf = io.BytesIO()
                part.save(part_buf)
                part.close()
                part_buf.seek(0)
                zf.writestr(f"parte_{i}_pags_{start}-{end}.pdf", part_buf.read())

        src.close()
        zip_buf.seek(0)

        return send_file(
            zip_buf,
            mimetype="application/zip",
            as_attachment=True,
            download_name="pdf_dividido.zip"
        )

    except Exception as e:
        return jsonify({"error": f"Falha ao dividir PDF: {e}"}), 500
