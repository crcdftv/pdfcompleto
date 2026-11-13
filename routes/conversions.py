"""
Rotas de conversão de PDF (Word, imagem, etc).
"""
import os
import io
import time
import logging
import tempfile
import threading

import fitz  # PyMuPDF
from PIL import Image, UnidentifiedImageError
from pdf2docx import Converter
from flask import Blueprint, request, jsonify, send_file, abort
from zipfile import ZipFile, ZIP_DEFLATED

from core.config import UPLOAD_FOLDER
from core import ocr_text

logger = logging.getLogger(__name__)

conversions_bp = Blueprint('conversions', __name__)

# Tempo máximo sem atualização de progresso antes de marcar o job como travado
WORD_TIMEOUT_SECONDS = 15 * 60

# Idade máxima dos jobs antes da limpeza automática
JOB_MAX_AGE_SECONDS = 60 * 60        # processando: 1 hora
JOB_DONE_MAX_AGE_SECONDS = 15 * 60   # concluído/erro: 15 minutos

# Dicionário global de jobs de conversão para Word
convert_progress = {}

# Dicionário global de jobs de conversão PDF -> imagem
img_progress = {}


def limpar_conversions():
    """Remove jobs de conversão (Word/imagem) expirados e arquivos temporários órfãos."""
    agora = time.time()
    for store in (convert_progress, img_progress):
        for job_id in list(store.keys()):
            job = store.get(job_id)
            if not job:
                continue
            status = job.get('status', 'processing')
            ultima = job.get('_last_activity', job.get('created_at', agora))
            limite = JOB_DONE_MAX_AGE_SECONDS if status in ('done', 'error') else JOB_MAX_AGE_SECONDS
            if agora - ultima > limite:
                if store is convert_progress:
                    try:
                        docx = job.get('docx_path')
                        if docx and os.path.exists(docx):
                            os.unlink(docx)
                    except Exception:
                        pass
                del store[job_id]
                logger.info('[Conversions] Job expirado removido: %s', job_id)


@conversions_bp.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Recurso não encontrado"}), 404

@conversions_bp.errorhandler(400)
def bad_request(e):
    return jsonify({"error": "Requisição inválida"}), 400

@conversions_bp.errorhandler(500)
def internal_error(e):
    logger.error(f"Erro interno: {e}")
    return jsonify({"error": "Erro interno do servidor"}), 500


@conversions_bp.route("/convert-to-word", methods=["POST"])
def convert_to_word():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Dados JSON não fornecidos"}), 400

        filename = data.get("filename")
        if not filename:
            return jsonify({"error": "Nome do arquivo não fornecido"}), 400

        from werkzeug.utils import secure_filename
        secure_name = secure_filename(filename.replace('\\', '/').split('/')[-1])
        if not secure_name:
            return jsonify({"error": "Nome de arquivo inválido"}), 400

        if not secure_name.lower().endswith('.pdf'):
            return jsonify({"error": "Arquivo deve ter extensão .pdf"}), 400

        pdf_path = os.path.join(UPLOAD_FOLDER, secure_name)
        if not os.path.exists(pdf_path):
            return jsonify({"error": "Arquivo PDF não encontrado"}), 404

        try:
            with open(pdf_path, 'rb') as f:
                header = f.read(4)
                if header != b'%PDF':
                    return jsonify({"error": "Arquivo não é um PDF válido"}), 400
        except Exception as e:
            return jsonify({"error": "Erro ao verificar arquivo PDF"}), 500

        docx_filename = secure_name.rsplit(".", 1)[0] + ".docx"

        temp_docx_path = None
        with tempfile.NamedTemporaryFile(suffix='.docx', delete=False) as temp_file:
            temp_docx_path = temp_file.name

        job_id = f'word_{int(time.time() * 1000)}'
        convert_progress[job_id] = {
            'pct': 0, 'status': 'processing', 'msg': 'Iniciando...',
            'docx_path': temp_docx_path, 'docx_filename': docx_filename,
            'created_at': time.time(), '_last_activity': time.time(),
        }

        threading.Thread(
            target=_convert_word_worker,
            args=(job_id, pdf_path, temp_docx_path),
            daemon=True,
        ).start()

        return jsonify({'job_id': job_id}), 202

    except FileNotFoundError:
        return jsonify({"error": "Arquivo PDF não encontrado"}), 404


def _doc_has_content(docx_file):
    """True se o documento já tem parágrafos ou tabelas (não só seções)."""
    return any(
        child.tag.endswith('}p') or child.tag.endswith('}tbl')
        for child in docx_file.element.body
    )


def _append_ocr_page(docx_file, pdf_page, pdf2docx_page, paragraphs):
    """Cria uma seção nova e escreve o texto reconhecido por OCR."""
    from docx.shared import Pt
    from docx.enum.section import WD_SECTION

    if not paragraphs:
        return False

    if _doc_has_content(docx_file):
        section = docx_file.add_section(WD_SECTION.NEW_PAGE)
    else:
        section = docx_file.sections[0]

    section.page_width = Pt(pdf_page.rect.width)
    section.page_height = Pt(pdf_page.rect.height)

    left, right, top, bottom = ocr_text.page_margin(pdf2docx_page)
    section.left_margin = Pt(left)
    section.right_margin = Pt(right)
    section.top_margin = Pt(top)
    section.bottom_margin = Pt(bottom)

    for text in paragraphs:
        docx_file.add_paragraph(text)
    return True


def _append_image_page(docx_file, pdf_page, pdf2docx_page, index):
    """Fallback: embute a página renderizada quando o OCR não reconheceu texto.

    Evita que a página suma silenciosamente do DOCX.
    """
    from docx.shared import Pt
    from docx.enum.section import WD_SECTION

    try:
        left, right, top, bottom = ocr_text.page_margin(pdf2docx_page)

        if _doc_has_content(docx_file):
            section = docx_file.add_section(WD_SECTION.NEW_PAGE)
        else:
            section = docx_file.sections[0]

        section.page_width = Pt(pdf_page.rect.width)
        section.page_height = Pt(pdf_page.rect.height)
        section.left_margin = Pt(left)
        section.right_margin = Pt(right)
        section.top_margin = Pt(top)
        section.bottom_margin = Pt(bottom)

        pix = pdf_page.get_pixmap(dpi=150)
        width_pt = max(pdf_page.rect.width - left - right, 72.0)
        docx_file.add_picture(io.BytesIO(pix.tobytes('png')), width=Pt(width_pt))
        return True

    except Exception:
        logger.exception('[Convert-Word] fallback de imagem falhou na pagina %d', index + 1)
        return False


def _write_page(docx_file, pdf_doc, page, index, total, ocr_pages, pct, upd):
    """Escreve uma página no DOCX.

    Sem camada de texto (ou se o pdf2docx falhar) usa OCR para gerar texto
    editável; caso contrário mantém a conversão de layout do pdf2docx.
    """
    if index in ocr_pages or not page.finalized:
        upd(pct, f'OCR da página {index + 1}/{total}...')
        if _append_ocr_page(docx_file, pdf_doc[index], page,
                            ocr_text.ocr_page(pdf_doc, index)):
            return

    if not page.finalized:
        # OCR não reconheceu nada: mantém a página como imagem em vez de sumi-la
        logger.warning('[Convert-Word] Nada reconhecido na pagina %d; usando imagem',
                       index + 1)
        _append_image_page(docx_file, pdf_doc[index], page, index)
        return

    upd(pct, f'Criando documento ({index + 1}/{total} páginas)...')
    try:
        page.make_docx(docx_file)
    except Exception:
        logger.exception('[Convert-Word] pdf2docx falhou na pagina %d', index + 1)
        upd(pct, f'OCR da página {index + 1}/{total}...')
        _append_ocr_page(docx_file, pdf_doc[index], page,
                         ocr_text.ocr_page(pdf_doc, index))


def _convert_word_worker(job_id, pdf_path, docx_path):
    """Converte PDF para DOCX em thread, atualizando progresso por página.

    Páginas sem camada de texto (digitalizadas ou com texto em curvas) são
    reconhecidas por OCR para gerar texto editável em vez de só imagens.
    """
    job = convert_progress.get(job_id)
    cv = None
    pdf_doc = None

    def upd(pct, msg=''):
        job.update({'pct': pct, 'msg': msg, '_last_activity': time.time()})

    try:
        upd(2, 'Abrindo documento...')

        pdf_doc = fitz.open(pdf_path)
        ocr_pages = {i for i, page in enumerate(pdf_doc) if ocr_text.needs_ocr(page)}

        # Fases 1-3: abrir, analisar e interpretar páginas (processo único,
        # sem multi_processing — evita travamentos no Windows).
        upd(5, 'Analisando páginas...')
        cv = Converter(pdf_path)
        settings = dict(cv.default_settings)
        settings.update({'multi_processing': False, 'debug': False, 'ignore_page_error': True})
        cv.parse(start=0, end=None, **settings)

        total = len(cv.pages)
        if not total:
            raise RuntimeError('Nenhuma página pôde ser convertida')

        from docx import Document
        docx_file = Document()
        upd(15, f'Criando documento (0/{total} páginas)...')

        for i, page in enumerate(cv.pages):
            _write_page(docx_file, pdf_doc, page, i, total, ocr_pages,
                        15 + int((i / total) * 75), upd)

        upd(93, 'Salvando arquivo Word...')
        docx_file.save(docx_path)

        if not os.path.exists(docx_path) or os.path.getsize(docx_path) == 0:
            raise RuntimeError('Arquivo DOCX não foi criado corretamente')

        upd(100, 'Concluído!')
        job['status'] = 'done'

    except Exception as e:
        logger.exception('[Convert-Word] Falha no worker')
        job.update({'status': 'error', 'msg': str(e), 'pct': 0})
    finally:
        for resource in (cv, pdf_doc):
            try:
                if resource is not None:
                    resource.close()
            except Exception:
                pass
        if job and job.get('status') == 'error':
            try:
                if os.path.exists(docx_path):
                    os.unlink(docx_path)
            except Exception:
                pass


def _word_job_stuck_or_done(job):
    """Verifica se o job passou do timeout (sem atualizações) e o marca como erro."""
    if job.get('status') == 'processing':
        elapsed = time.time() - job.get('_last_activity', time.time())
        if elapsed > WORD_TIMEOUT_SECONDS:
            job.update({
                'status': 'error',
                'msg': f'Conversão travou (sem progresso por {int(WORD_TIMEOUT_SECONDS / 60)} min). Tente novamente.',
            })
    return job


@conversions_bp.route("/convert-to-word/progress/<job_id>", methods=["GET"])
def convert_word_progress(job_id):
    """Polling de progresso da conversão para Word."""
    job = convert_progress.get(job_id)
    if not job:
        return jsonify({'error': 'Job não encontrado'}), 404
    _word_job_stuck_or_done(job)
    return jsonify({
        'pct': job.get('pct', 0),
        'status': job.get('status', 'processing'),
        'msg': job.get('msg', ''),
    })


@conversions_bp.route("/convert-to-word/download/<job_id>", methods=["GET"])
def convert_word_download(job_id):
    """Download do DOCX convertido."""
    job = convert_progress.get(job_id)
    if not job:
        return jsonify({'error': 'Job não encontrado'}), 404
    _word_job_stuck_or_done(job)

    if job.get('status') != 'done':
        return jsonify({'error': 'Conversão ainda não concluída'}), 425

    docx_path = job.get('docx_path')
    if not docx_path or not os.path.isfile(docx_path):
        return jsonify({'error': 'Arquivo DOCX não encontrado'}), 500

    docx_filename = job.get('docx_filename', 'documento.docx')
    del convert_progress[job_id]

    def _cleanup():
        try:
            if os.path.exists(docx_path):
                os.unlink(docx_path)
        except Exception:
            pass

    response = send_file(
        docx_path,
        as_attachment=True,
        download_name=docx_filename,
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        conditional=False,
    )
    response.call_on_close(_cleanup)
    return response


@conversions_bp.route("/convert_pdf_to_image", methods=["POST"])
def convert_pdf_to_image():
    if "pdf" not in request.files:
        return jsonify({"error": "Nenhum PDF enviado."}), 400

    pdf_file = request.files["pdf"]
    image_format = (request.form.get("format") or "png").lower()
    if image_format == "jpeg":
        image_format = "jpg"

    dpi = int(request.form.get("dpi", 200))
    zoom = dpi / 72.0

    pdf_bytes = pdf_file.read()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total = doc.page_count
    doc.close()

    if total == 0:
        return jsonify({"error": "O PDF não contém páginas para converter"}), 400

    job_id = f'img_{int(time.time() * 1000)}'
    img_progress[job_id] = {
        'pct': 0, 'status': 'processing', 'msg': 'Iniciando...',
        'pdf_bytes': pdf_bytes, 'image_format': image_format, 'zoom': zoom,
        'total': total, '_last_activity': time.time(),
    }

    threading.Thread(target=_image_worker, args=(job_id,), daemon=True).start()
    return jsonify({'job_id': job_id}), 202


def _image_worker(job_id):
    """Renderiza cada página do PDF em imagem, atualizando o progresso."""
    job = img_progress.get(job_id)

    def upd(pct, msg=''):
        job.update({'pct': pct, 'msg': msg, '_last_activity': time.time()})

    try:
        pdf_bytes = job['pdf_bytes']
        image_format = job['image_format']
        zoom = job['zoom']
        total = job['total']

        with tempfile.TemporaryDirectory() as tempdir:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            image_paths = []
            for i, page in enumerate(doc):
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                img_path = os.path.join(tempdir, f"page_{i+1}.{image_format}")
                if image_format == "jpg":
                    pix.save(img_path, "jpg")
                else:
                    pix.save(img_path)
                image_paths.append(img_path)
                pct = int(((i + 1) / total) * 100)
                upd(pct, f'Renderizando página {i+1}/{total}...')
            doc.close()

            if len(image_paths) > 1:
                zip_buf = io.BytesIO()
                with ZipFile(zip_buf, "w", compression=ZIP_DEFLATED) as zf:
                    for path in image_paths:
                        zf.write(path, os.path.basename(path))
                zip_buf.seek(0)
                job['result'] = zip_buf
                job['filename'] = 'pdf_convertido_imagens.zip'
                job['mimetype'] = 'application/zip'
            else:
                buf = io.BytesIO()
                with open(image_paths[0], "rb") as f:
                    buf.write(f.read())
                buf.seek(0)
                job['result'] = buf
                job['mimetype'] = 'image/jpeg' if image_format == "jpg" else "image/png"
                job['filename'] = f'pdf_convertido.{image_format}'

            upd(100, 'Concluído!')
            job['status'] = 'done'

    except Exception as e:
        logger.exception('[Convert-Img] Falha no worker')
        job.update({'status': 'error', 'msg': str(e), 'pct': 0})


@conversions_bp.route("/convert_pdf_to_image/progress/<job_id>", methods=["GET"])
def convert_image_progress(job_id):
    """Polling de progresso da conversão PDF para imagem."""
    job = img_progress.get(job_id)
    if not job:
        return jsonify({'error': 'Job não encontrado'}), 404
    _word_job_stuck_or_done(job)
    return jsonify({
        'pct': job.get('pct', 0),
        'status': job.get('status', 'processing'),
        'msg': job.get('msg', ''),
    })


@conversions_bp.route("/convert_pdf_to_image/download/<job_id>", methods=["GET"])
def convert_image_download(job_id):
    """Download do resultado da conversão PDF para imagem."""
    job = img_progress.get(job_id)
    if not job:
        return jsonify({'error': 'Job não encontrado'}), 404
    _word_job_stuck_or_done(job)

    if job.get('status') != 'done':
        return jsonify({'error': 'Conversão ainda não concluída'}), 425

    result = job.get('result')
    if not result:
        return jsonify({'error': 'Resultado não disponível'}), 500

    filename = job.get('filename', 'pdf_convertido.zip')
    mimetype = job.get('mimetype', 'application/zip')
    del img_progress[job_id]

    return send_file(
        result,
        mimetype=mimetype,
        as_attachment=True,
        download_name=filename,
        conditional=False,
    )


@conversions_bp.route('/convert/image-to-pdf', methods=['POST'])
def image_to_pdf():
    try:
        uploaded_files = request.files.getlist('images')

        if not uploaded_files:
            return jsonify({'error': 'Nenhuma imagem enviada.'}), 400

        images = []
        for file in uploaded_files:
            try:
                file.seek(0)
                img = Image.open(file)
                img = img.convert("RGBA")
                background = Image.new("RGB", img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[3] if img.mode == 'RGBA' else None)
                images.append(background)

            except UnidentifiedImageError:
                return jsonify({'error': f'O arquivo "{file.filename}" não é uma imagem válida.'}), 400

        pdf_bytes = io.BytesIO()
        images[0].save(pdf_bytes, format="PDF", save_all=True, append_images=images[1:])
        pdf_bytes.seek(0)

        return send_file(
            pdf_bytes,
            as_attachment=True,
            download_name='resultado.pdf',
            mimetype='application/pdf'
        )

    except Exception as e:
        return jsonify({'error': str(e)}), 500
