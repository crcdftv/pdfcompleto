"""
Rotas de edição de PDF (redação, merge, applying edits).
"""
import os
import io
import logging

import fitz  # PyMuPDF
import pikepdf
from flask import Blueprint, request, jsonify, send_file, session
from werkzeug.utils import secure_filename

from core.config import UPLOAD_FOLDER, OCR_OUTPUT_FOLDER

logger = logging.getLogger(__name__)

editing_bp = Blueprint('editing', __name__)


@editing_bp.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Recurso não encontrado"}), 404

@editing_bp.errorhandler(400)
def bad_request(e):
    return jsonify({"error": "Requisição inválida"}), 400

@editing_bp.errorhandler(500)
def internal_error(e):
    logger.error(f"Erro interno: {e}")
    return jsonify({"error": "Erro interno do servidor"}), 500


def _normalize_redaction(raw):
    """Normaliza uma tarja do frontend para o formato usado na sessão."""
    if not isinstance(raw, dict):
        raise ValueError("Tarja inválida")

    page = raw.get("page") or raw.get("page_num") or 1
    x_pct = raw.get("xPercent", raw.get("x"))
    y_pct = raw.get("yPercent", raw.get("y"))
    width_pct = raw.get("widthPercent", raw.get("w"))
    height_pct = raw.get("heightPercent", raw.get("h"))

    if any(value is None for value in (x_pct, y_pct, width_pct, height_pct)):
        raise ValueError("Coordenadas de tarja incompletas")

    try:
        page = int(page)
        x_pct, y_pct, width_pct, height_pct = map(
            float, (x_pct, y_pct, width_pct, height_pct)
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("Coordenadas de tarja inválidas/incompletas") from exc

    if page < 1:
        raise ValueError("Número de página inválido")

    return {
        "page": page,
        "xPercent": x_pct,
        "yPercent": y_pct,
        "widthPercent": width_pct,
        "heightPercent": height_pct,
    }


@editing_bp.route('/init_redaction', methods=['POST'])
def init_redaction():
    data = request.get_json(force=True, silent=True) or {}
    web_path = (data.get('web_path') or '').replace('\\', '/').strip()

    if not web_path.startswith('/uploads/'):
        return jsonify({"error": "web_path inválido"}), 400

    filename = web_path.replace('/uploads/', '')
    abs_path = os.path.abspath(os.path.join(UPLOAD_FOLDER, filename))

    if not os.path.isfile(abs_path):
        return jsonify({"error": f"Arquivo não encontrado: {abs_path}"}), 404

    session['original_pdf_path'] = abs_path
    session['redactions'] = []
    session.modified = True

    return jsonify({
        "ok": True,
        "message": "Sessão de redação iniciada",
        "file": web_path
    }), 200


@editing_bp.route('/__session_debug')
def __session_debug():
    return jsonify({
        "original_pdf_path": session.get('original_pdf_path'),
        "has_bytes": 'original_pdf_bytes' in session,
        "redactions_len": len(session.get('redactions') or [])
    })


@editing_bp.route('/undo_last_redaction', methods=['POST'])
def undo_last_redaction():
    """Desfaz a última tarja e mantém a sessão sincronizada com o frontend.

    O frontend pode enviar a lista restante de tarjas. Isso evita que o
    histórico da sessão fique dessincronizado depois que o PDF é salvo.
    """
    data = request.get_json(silent=True) or {}
    requested_redactions = data.get("redactions")

    try:
        if requested_redactions is None:
            # Compatibilidade com clientes antigos: usa o histórico da sessão.
            redactions = list(session.get('redactions') or [])
            if not redactions:
                return jsonify({"error": "Nenhuma tarja para desfazer"}), 400
            redactions.pop()
        else:
            if not isinstance(requested_redactions, list):
                return jsonify({"error": "Lista de tarjas inválida"}), 400
            redactions = [
                _normalize_redaction(redaction)
                for redaction in requested_redactions
            ]

        orig_path = session.get('original_pdf_path')
        if orig_path and os.path.isfile(orig_path):
            doc = fitz.open(orig_path)
        elif session.get('original_pdf_bytes'):
            doc = fitz.open(stream=session['original_pdf_bytes'], filetype="pdf")
        else:
            return jsonify({"error": "Nenhum PDF carregado na sessão"}), 400

        try:
            for redaction in redactions:
                page_idx = redaction["page"] - 1
                if page_idx < 0 or page_idx >= doc.page_count:
                    continue
                page = doc.load_page(page_idx)

                x0 = redaction["xPercent"] * page.rect.width
                y0 = redaction["yPercent"] * page.rect.height
                x1 = x0 + redaction["widthPercent"] * page.rect.width
                y1 = y0 + redaction["heightPercent"] * page.rect.height

                rect = fitz.Rect(x0, y0, x1, y1) & page.rect
                if not rect.is_empty:
                    page.add_redact_annot(rect, fill=(0, 0, 0))
                    page.apply_redactions()

            buf = io.BytesIO()
            doc.save(buf)
        finally:
            doc.close()

        # Só confirma a alteração na sessão depois de gerar o PDF com sucesso.
        session['redactions'] = redactions
        session.modified = True

        buf.seek(0)
        return send_file(buf, mimetype='application/pdf',
                         as_attachment=False, download_name='preview.pdf')

    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        logger.exception("Erro ao desfazer tarja")
        return jsonify({"error": "Erro ao desfazer tarja"}), 500


@editing_bp.route('/apply_redaction_session', methods=['POST'])
def apply_redaction_session():
    """Sincroniza as tarjas do frontend com o histórico da sessão."""
    data = request.get_json(force=True, silent=True) or {}

    try:
        if "redactions" in data:
            raw_redactions = data["redactions"]
            if not isinstance(raw_redactions, list):
                raise ValueError("Lista de tarjas inválida")
            redactions = [
                _normalize_redaction(redaction)
                for redaction in raw_redactions
            ]
            session['redactions'] = redactions
        else:
            # Compatibilidade com clientes antigos: adiciona uma tarja.
            redaction = _normalize_redaction(data)
            if 'redactions' not in session or session.get('redactions') is None:
                session['redactions'] = []
            session['redactions'].append(redaction)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    session.modified = True
    return jsonify({"ok": True, "redactions_len": len(session['redactions'])}), 200


@editing_bp.route('/init_merged_session', methods=['POST'])
def init_merged_session():
    try:
        data = request.get_json(force=True, silent=True) or {}
        files = data.get('files', [])

        if not files:
            return jsonify({"error": "Nenhum arquivo enviado"}), 400

        merged = pikepdf.new()

        for fname in files:
            safe = secure_filename(os.path.basename(fname))
            path = os.path.join(UPLOAD_FOLDER, safe)
            if not os.path.isfile(path):
                path = os.path.join(OCR_OUTPUT_FOLDER, safe)
            if not os.path.isfile(path):
                merged.close()
                return jsonify({"error": f"Arquivo não encontrado: {safe}"}), 404

            src = pikepdf.open(path)
            merged.pages.extend(src.pages)
            src.close()

        buf = io.BytesIO()
        total_pages = len(merged.pages)
        merged.save(buf)
        merged.close()
        buf.seek(0)

        session['original_pdf_bytes'] = buf.read()
        session['original_pdf_path']  = None
        session['redactions']         = []
        session.modified = True

        return jsonify({"ok": True, "pages": total_pages}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@editing_bp.route('/apply_edits', methods=['POST'])
def apply_edits():
    """
    Aplica tarjas e retorna o PDF final (merged ou simples).
    Preserva assinaturas digitais quando nao ha reordenacao de paginas.
    """
    try:
        orig_path = session.get('original_pdf_path')
        if orig_path and os.path.isfile(orig_path):
            doc = fitz.open(orig_path)
        elif session.get('original_pdf_bytes'):
            doc = fitz.open(stream=session['original_pdf_bytes'], filetype="pdf")
        else:
            return jsonify({"error": "Nenhum PDF carregado na sessão"}), 400

        data = request.get_json(force=True, silent=True) or {}
        page_order = data.get('page_order', list(range(1, doc.page_count + 1)))
        page_rotations = data.get('page_rotations', {})
        edits = data.get('edits', {})

        try:
            tarjas = [
                _normalize_redaction(redaction)
                for redaction in edits.get('tarjas', [])
            ]
        except ValueError as exc:
            doc.close()
            return jsonify({"error": str(exc)}), 400

        default_order = list(range(1, doc.page_count + 1))
        needs_reorder = page_order != default_order

        if needs_reorder:
            new_doc = fitz.open()
            for page_num in page_order:
                if 1 <= page_num <= doc.page_count:
                    new_doc.insert_pdf(doc, from_page=page_num-1, to_page=page_num-1)
            doc.close()
            doc = new_doc

        for page_id_str, angle in page_rotations.items():
            try:
                idx = int(page_id_str) - 1
                if 0 <= idx < doc.page_count:
                    page = doc.load_page(idx)
                    page.set_rotation((page.rotation + int(angle)) % 360)
            except Exception:
                pass

        for redaction in tarjas:
            page_idx = redaction["page"] - 1
            if page_idx < 0 or page_idx >= doc.page_count:
                continue
            page = doc.load_page(page_idx)

            x0 = redaction["xPercent"] * page.rect.width
            y0 = redaction["yPercent"] * page.rect.height
            x1 = x0 + redaction["widthPercent"] * page.rect.width
            y1 = y0 + redaction["heightPercent"] * page.rect.height

            rect = fitz.Rect(x0, y0, x1, y1) & page.rect
            if not rect.is_empty:
                page.add_redact_annot(rect, fill=(0, 0, 0))
                page.apply_redactions()

        texts = edits.get('texts', [])
        for t in texts:
            page_idx = int(t.get('page', 1)) - 1
            if page_idx < 0 or page_idx >= doc.page_count:
                continue
            p = doc.load_page(page_idx)

            tx = float(t.get('x', 0)) * p.rect.width
            ty = float(t.get('y', 0)) * p.rect.height
            content = t.get('content', '')
            font_size = float(t.get('fontSize', 16))
            bold = t.get('bold', False)
            italic = t.get('italic', False)
            color = t.get('color', '#000000')

            if content:
                pw = p.rect.width
                rect = fitz.Rect(tx, ty, tx + pw, ty + font_size * 1.3)

                font_map = {
                    (False, False): "Helvetica",
                    (True, False):  "Helvetica-Bold",
                    (False, True):  "Helvetica-Oblique",
                    (True, True):   "Helvetica-BoldOblique",
                }
                font_name = font_map.get((bold, italic), "Helvetica")

                r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)

                annot = p.add_freetext_annot(rect, content, fontsize=font_size)
                annot.set_font(fontname=font_name)
                annot.set_colors(fill=None, stroke=(r/255, g/255, b/255))
                annot.update()

        buf = io.BytesIO()
        doc.save(buf)
        doc.close()
        buf.seek(0)

        # Mantém o histórico sincronizado para permitir desfazer mesmo
        # depois que o PDF já foi salvo.
        session['redactions'] = tarjas
        session.modified = True

        return send_file(buf, mimetype='application/pdf',
                         as_attachment=True,
                         download_name='documento_editado.pdf')

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@editing_bp.route('/get-pdf-page-dimensions', methods=['POST'])
def get_pdf_page_dimensions():
    """
    Retorna as dimensões (largura e altura) de uma página específica de um PDF em pontos (pt).
    """
    data = request.get_json()
    pdf_filename_with_path = data.get("filename")
    page_num = data.get("page_num", 0)

    if not pdf_filename_with_path:
        return jsonify({"error": "Caminho do PDF não fornecido."}), 400

    input_pdf_full_path = None
    if pdf_filename_with_path.startswith('/ocr_outputs/'):
        pdf_name_only = pdf_filename_with_path.replace('/ocr_outputs/', '')
        input_pdf_full_path = os.path.join(OCR_OUTPUT_FOLDER, pdf_name_only)
    elif pdf_filename_with_path.startswith('/uploads/'):
        pdf_name_only = pdf_filename_with_path.replace('/uploads/', '')
        input_pdf_full_path = os.path.join(UPLOAD_FOLDER, pdf_name_only)
    else:
        temp_path_ocr = os.path.join(OCR_OUTPUT_FOLDER, pdf_filename_with_path)
        temp_path_upload = os.path.join(UPLOAD_FOLDER, pdf_filename_with_path)
        if os.path.exists(temp_path_ocr):
            input_pdf_full_path = temp_path_ocr
        elif os.path.exists(temp_path_upload):
            input_pdf_full_path = temp_path_upload

    if not input_pdf_full_path or not os.path.exists(input_pdf_full_path):
        return jsonify({"error": f"Arquivo '{pdf_filename_with_path}' não encontrado no servidor."}), 404

    try:
        doc = fitz.open(input_pdf_full_path)
        if page_num < 0 or page_num >= doc.page_count:
            doc.close()
            return jsonify({"error": f"Número de página inválido: {page_num}. O PDF tem {doc.page_count} páginas."}), 400

        page = doc.load_page(page_num)
        width_pt = page.rect.width
        height_pt = page.rect.height
        doc.close()

        return jsonify({"success": True, "width_pt": width_pt, "height_pt": height_pt}), 200

    except Exception as e:
        return jsonify({"success": False, "error": f"Ocorreu um erro interno ao obter dimensões do PDF: {e}"}), 500
