"""
Rotas de OCR (Reconhecimento Óptico de Caracteres).
"""
import os
import time
import logging
import threading
import concurrent.futures

import fitz  # PyMuPDF
from PIL import Image

from core.ocr_preprocess import (
    prepare_for_ocr, run_best_config, score_words, DEFAULT_MIN_CONFIDENCE,
)

try:
    import pytesseract
except Exception:
    pytesseract = None

from flask import (
    Blueprint, render_template, request, jsonify, send_from_directory,
    current_app,
)

from core.config import UPLOAD_FOLDER, OCR_OUTPUT_FOLDER

logger = logging.getLogger(__name__)

ocr_bp = Blueprint('ocr', __name__)


@ocr_bp.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Recurso não encontrado"}), 404

@ocr_bp.errorhandler(400)
def bad_request(e):
    return jsonify({"error": "Requisição inválida"}), 400

@ocr_bp.errorhandler(500)
def internal_error(e):
    logger.error(f"Erro interno: {e}")
    return jsonify({"error": "Erro interno do servidor"}), 500


# Dicionário global para controlar progresso das conversões OCR
conversion_progress = {}

# Resolução de renderização: 300 dpi é o ponto onde o Tesseract ganha mais precisão
OCR_DPI = 300

# Texto mínimo (caracteres) para considerar o reconhecimento de uma página válido
MIN_TEXT_CHARS = 30

# Texto nativo já cobre a página -> não mexe (mantém o texto original, perfeito)
DENSE_TEXT_CHARS = 2500

# Praticamente sem texto nativo -> OCR (texto em curvas ou página em branco)
SCARSE_TEXT_CHARS = 30

# Fração da página ocupada por imagem: acima disso a página é digitalizada
IMAGE_COVERAGE_MIN = 0.40

# Tentativas em ordem: bloco único (padrão), segmentação automática, texto esparsó.
# Só passa para a próxima quando a anterior sai ruim.
OCR_CONFIGS = (
    r'--oem 3 --psm 6 -l por+eng'
    r' -c preserve_interword_spaces=1'
    r' -c tessedit_char_blacklist=|',
    r'--oem 3 --psm 3 -l por+eng'
    r' -c preserve_interword_spaces=1'
    r' -c tessedit_char_blacklist=|',
    r'--oem 3 --psm 11 -l por+eng'
    r' -c preserve_interword_spaces=1'
    r' -c tessedit_char_blacklist=|',
)

# Página normal leva 1-4s no Tesseract; o limite evita que uma página estranha
# trave a conversão inteira (o processo filho é morto e tentamos a próxima config)
OCR_TIMEOUT_SECONDS = 120


def _image_coverage(page):
    """Fração da página coberta por imagens (0.0 a 1.0)."""
    try:
        area = page.rect.width * page.rect.height
        if area <= 0:
            return 0.0
        coverage = 0.0
        for image in page.get_images(full=True):
            try:
                for rect in page.get_image_rects(image[0]):
                    coverage += (rect.width * rect.height) / area
            except Exception:
                continue
        return coverage
    except Exception:
        return 0.0


def _needs_ocr(native_chars, coverage):
    """Decide se a página precisa ganhar camada de OCR.

    - página digitalizada (imagem grande): OCRa quando o texto nativo não
      cobre a página (cabeçalho/carimbo nativo + conteúdo só na imagem)
    - página vetorial: só OCRa quando quase não tem texto (texto em curvas)

    Página com texto nativo denso é mantida como está: o texto original é
    perfeito, e re-OCRizá-la só piora (e duplica) o resultado.
    """
    if coverage >= IMAGE_COVERAGE_MIN:
        return native_chars < DENSE_TEXT_CHARS
    return native_chars < SCARSE_TEXT_CHARS


def _covered_by_native(x0, y0, x1, y1, native_boxes, threshold=0.6):
    """True se a maior parte da caixa já está coberta por texto nativo."""
    area = (x1 - x0) * (y1 - y0)
    if area <= 0:
        return False
    covered = 0.0
    for bx0, by0, bx1, by1 in native_boxes:
        ix = max(0.0, min(x1, bx1) - max(x0, bx0))
        iy = max(0.0, min(y1, by1) - max(y0, by0))
        covered += ix * iy
        if covered >= threshold * area:
            return True
    return covered >= threshold * area


def _stamp_words(target_page, data, source_page, pix_width):
    """Escreve o texto reconhecido como camada invisível sobre a página original.

    A página mantém exatamente o desenho original (cores, vetores, qualidade);
    o OCR só acrescenta texto pesquisável por cima. Palavras que já existem no
    texto nativo da página são ignoradas para não duplicar.
    """
    scale = target_page.rect.width / pix_width
    derot = target_page.derotation_matrix
    rotation = target_page.rotation
    native_boxes = [
        (w[0], w[1], w[2], w[3]) for w in source_page.get_text("words")
    ]

    stamped = 0
    for i, raw in enumerate(data['text']):
        word = raw.strip()
        if not word:
            continue
        try:
            if int(data['conf'][i]) < DEFAULT_MIN_CONFIDENCE:
                continue
        except (TypeError, ValueError):
            continue

        width = data['width'][i] * scale
        height = data['height'][i] * scale
        if width < 2 or height < 2:
            continue

        x0 = data['left'][i] * scale
        y0 = data['top'][i] * scale

        # Caixa no espaço da página (para comparar com o texto nativo)
        p1 = fitz.Point(x0, y0) * derot
        p2 = fitz.Point(x0 + width, y0 + height) * derot
        rx0, rx1 = sorted((p1.x, p2.x))
        ry0, ry1 = sorted((p1.y, p2.y))

        if native_boxes and _covered_by_native(rx0, ry0, rx1, ry1, native_boxes):
            continue

        # Âncora calculada no espaço da vista (texto deitado como o OCR leu)
        fontsize = max(height * 0.9, 4.0)
        anchor = fitz.Point(x0, y0 + height * 0.82) * derot
        try:
            target_page.insert_text(
                anchor, word,
                fontsize=fontsize, fontname="helv",
                render_mode=3,  # invisível (só para busca)
                rotate=rotation,  # fica deitado na vista, não na vertical
                overlay=True,
            )
            stamped += 1
        except Exception:
            continue
    return stamped


def _recognize_page(prepared, page_num=None):
    """Roda o Tesseract (parte pesada). Segura em thread: não usa PyMuPDF."""
    label = f"pagina {page_num + 1}" if page_num is not None else ''
    return run_best_config(
        lambda config: pytesseract.image_to_data(
            prepared, config=config, output_type=pytesseract.Output.DICT,
            timeout=OCR_TIMEOUT_SECONDS,
        ),
        OCR_CONFIGS,
        score_words,
        min_score=MIN_TEXT_CHARS,
        label=label,
    )


def pdf_to_ocr(input_pdf_path, output_pdf_path, conversion_id):
    """Converte um PDF em PDF pesquisável, sem reescrever as páginas.

    O texto reconhecido entra como camada invisível na própria página do
    documento de trabalho. Assim imagens, cores, vetores, textos nativos,
    formulários e assinaturas digitais permanecem intactos — os problemas
    antigos vinham de copiar a página (perdia a assinatura) ou trocar a
    página por uma imagem (ficava preto e branco e o arquivo explodia).

    Só o Tesseract roda em paralelo: o PyMuPDF não é seguro entre threads
    e o acesso concorrente derrubava o processo (access violation).
    """
    pdf_document = None
    executor = None
    try:
        print(f"Iniciando conversao OCR: {input_pdf_path}")
        pdf_document = fitz.open(input_pdf_path)
        total_pages = pdf_document.page_count

        conversion_progress[conversion_id] = {
            'current_page': 0,
            'total_pages': total_pages,
            'status': 'processing',
            'percentage': 0
        }

        if pytesseract is None:
            raise RuntimeError("pytesseract indisponivel: OCR nao configurado")

        max_workers = max(1, min(4, (os.cpu_count() or 2)))
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)

        # fila limitada: no máximo max_workers imagens aguardando o Tesseract
        pendentes = {}
        concluidas = 0

        def registrar(page_num, data, pix_width, native_chars):
            nonlocal concluidas
            if data:
                try:
                    page = pdf_document[page_num]
                    stamped = _stamp_words(page, data, page, pix_width)
                    print(f"Pagina {page_num + 1}: OCR com {stamped} palavras "
                          f"(texto nativo: {native_chars})")
                except Exception as e:
                    print(f"OCR falhou na pagina {page_num + 1}, "
                          f"mantendo original: {e}")
            concluidas += 1
            percentage = int((concluidas / total_pages) * 100)
            conversion_progress[conversion_id].update({
                'current_page': concluidas,
                'percentage': percentage,
                'status': 'processing' if concluidas < total_pages else 'merging'
            })
            print(f"Pagina {concluidas}/{total_pages} processada ({percentage}%)")

        def drenar(esperar_todos=False):
            while pendentes and (esperar_todos or len(pendentes) >= max_workers):
                pronto, _ = concurrent.futures.wait(
                    pendentes,
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )
                for futuro in pronto:
                    page_num, pix_width, native_chars = pendentes.pop(futuro)
                    try:
                        data = futuro.result()
                    except Exception as e:
                        print(f"OCR falhou na pagina {page_num + 1}, "
                              f"mantendo original: {e}")
                        data = None
                    registrar(page_num, data, pix_width, native_chars)

        for page_num in range(total_pages):
            page = pdf_document[page_num]
            try:
                native_chars = len(page.get_text().strip())
                precisa = _needs_ocr(native_chars, _image_coverage(page))
            except Exception as e:
                print(f"Pagina {page_num + 1}: erro ao analisar, "
                      f"mantendo original: {e}")
                registrar(page_num, None, None, 0)
                continue

            if not precisa:
                print(f"Pagina {page_num + 1}: mantida original "
                      f"(texto nativo: {native_chars})")
                registrar(page_num, None, None, native_chars)
                continue

            try:
                pix = page.get_pixmap(dpi=OCR_DPI)
                prepared = prepare_for_ocr(
                    Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                )
            except Exception as e:
                print(f"OCR falhou na pagina {page_num + 1}, mantendo original: {e}")
                registrar(page_num, None, None, native_chars)
                continue

            pendentes[executor.submit(_recognize_page, prepared, page_num)] = (
                page_num, pix.width, native_chars,
            )
            drenar()

        drenar(esperar_todos=True)
        executor.shutdown(wait=True)
        executor = None

        conversion_progress[conversion_id]['status'] = 'merging'
        pdf_document.save(output_pdf_path, deflate=True)
        pdf_document.close()
        pdf_document = None

        conversion_progress[conversion_id].update({
            'status': 'completed',
            'percentage': 100
        })
        print(f"Conversao finalizada: {output_pdf_path}")

    except Exception as e:
        conversion_progress[conversion_id] = {
            'status': 'error',
            'error': str(e)
        }
        print(f"Erro ao processar o PDF para OCR: {str(e)}")

    finally:
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
        if pdf_document is not None:
            pdf_document.close()


@ocr_bp.route('/convert_pdf_to_searchable', methods=['POST'])
def convert_pdf_to_searchable():
    """Inicia a conversao de um PDF para PDF pesquisavel (OCR) em thread separada."""
    try:
        if not request.is_json:
            return jsonify({"error": "Content-Type deve ser application/json"}), 400

        data = request.get_json()

        if not data or 'pdf_path' not in data:
            return jsonify({"error": "Campo 'pdf_path' e obrigatorio"}), 400

        pdf_path = data['pdf_path']
        if pdf_path.startswith('/uploads/'):
            pdf_filename = pdf_path.replace('/uploads/', '')
        else:
            pdf_filename = pdf_path

        full_pdf_path = os.path.join(UPLOAD_FOLDER, pdf_filename)
        if not os.path.exists(full_pdf_path):
            return jsonify({"error": f"Arquivo PDF nao encontrado: {pdf_filename}"}), 404

        conversion_id = f"conv_{int(time.time())}"
        ocr_output_filename = f"ocr_{pdf_filename}"
        ocr_output_path = os.path.join(OCR_OUTPUT_FOLDER, ocr_output_filename)

        threading.Thread(
            target=pdf_to_ocr,
            args=(full_pdf_path, ocr_output_path, conversion_id)
        ).start()

        return jsonify({
            "conversion_id": conversion_id,
            "ocr_pdf_path": f"/ocr_outputs/{ocr_output_filename}",
            "message": "Conversao iniciada com sucesso"
        }), 200

    except Exception as e:
        print(f"Erro na conversao para OCR: {str(e)}")
        return jsonify({"error": f"Erro interno: {str(e)}"}), 500


@ocr_bp.route('/conversion_progress/<conversion_id>', methods=['GET'])
def get_conversion_progress(conversion_id):
    """Verifica o progresso de uma conversao OCR em andamento."""
    if conversion_id not in conversion_progress:
        return jsonify({"error": "Conversao nao encontrada"}), 404
    progress = conversion_progress[conversion_id]
    return jsonify(progress), 200


@ocr_bp.route('/processar_ocr', methods=['GET'])
def processar_ocr():
    """Recebe o nome do arquivo convertido e renderiza o template do editor."""
    nome_do_arquivo = request.args.get('nome_do_arquivo')

    if not nome_do_arquivo:
        return render_template('index.html', pdf_url=None, erro="Nome do arquivo nao fornecido.")

    pdf_url_http = f"/servir_pdf/{nome_do_arquivo}"

    return render_template(
        'index.html',
        pdf_url=pdf_url_http,
        nome_arquivo_processado=nome_do_arquivo
    )


@ocr_bp.route('/servir_pdf/<nome_do_arquivo>')
def servir_pdf(nome_do_arquivo):
    """Serve o arquivo PDF da pasta OCR_OUTPUTS_FOLDER para o navegador."""
    try:
        caminho_completo = os.path.join(OCR_OUTPUT_FOLDER, nome_do_arquivo)
        if not os.path.exists(caminho_completo):
            return "Erro: Arquivo nao encontrado no servidor.", 404

        return send_from_directory(
            OCR_OUTPUT_FOLDER,
            nome_do_arquivo,
            mimetype='application/pdf',
            as_attachment=False
        )
    except Exception as e:
        logger.error(f"Erro ao servir o PDF: {e}")
        return "Erro interno ao servir o arquivo.", 500
