"""
OCR de páginas para texto editável.

Usado pela conversão PDF -> Word nas páginas que não possuem camada de
texto (digitalizadas ou com o texto convertido em curvas). Devolve os
parágrafos reconhecidos, prontos para virarem texto editável no DOCX.
"""
import logging
import os

from PIL import Image

from core.ocr_preprocess import prepare_for_ocr, run_best_config

logger = logging.getLogger(__name__)

# Resolução do render: 300 dpi dá ao Tesseract detalhe suficiente para
# fontes pequenas e digitalizações com ruído (~2x o tempo de 200 dpi).
OCR_DPI = 300

# Ignora o ruído do OCR abaixo desta confiança
MIN_CONFIDENCE = 40

# Páginas com menos que isto de texto são tratadas como digitalizadas
MIN_TEXT_CHARS = 50

# Pontuação mínima (caracteres reconhecidos) para aceitar uma tentativa
MIN_OCR_CHARS = 30

# Ordem das tentativas: segmentação automática, bloco único, texto esparsó.
# A seguinte só roda quando a anterior reconhece pouco texto.
TESSERACT_CONFIGS = (
    '--oem 3 --psm 3 -l por+eng -c preserve_interword_spaces=1',
    '--oem 3 --psm 6 -l por+eng -c preserve_interword_spaces=1',
    '--oem 3 --psm 11 -l por+eng -c preserve_interword_spaces=1',
)

DEFAULT_MARGIN = (72.0, 72.0, 72.0, 72.0)


def _pytesseract():
    """Importa o pytesseract já apontando para os caminhos do projeto."""
    import pytesseract
    from core.config import get_tesseract_cmd, get_tessdata_prefix

    pytesseract.pytesseract.tesseract_cmd = get_tesseract_cmd()
    os.environ.setdefault('TESSDATA_PREFIX', get_tessdata_prefix())
    return pytesseract


def needs_ocr(page, min_chars=MIN_TEXT_CHARS):
    """True se a página não tem texto suficiente para virar Word editável."""
    try:
        return len(page.get_text().strip()) < min_chars
    except Exception:
        return True


def page_margin(pdf2docx_page):
    """Margens (esq, dir, topo, base) em pontos, com fallback padrão."""
    margin = getattr(pdf2docx_page, 'margin', None)
    try:
        if margin and len(margin) == 4 and all(float(v) > 0 for v in margin):
            return tuple(float(v) for v in margin)
    except (TypeError, ValueError):
        pass
    return DEFAULT_MARGIN


def _score_data(data):
    """Caracteres reconhecidos acima do corte de confiança."""
    return sum(
        len(raw.strip())
        for raw, conf in zip(data['text'], data['conf'])
        if int(conf) >= MIN_CONFIDENCE and raw.strip()
    )


def ocr_page(doc, page_index):
    """Roda OCR na página e devolve a lista de parágrafos reconhecidos."""
    try:
        pt = _pytesseract()
        page = doc[page_index]

        pix = page.get_pixmap(dpi=OCR_DPI)
        img = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
        img = prepare_for_ocr(img)

        data = run_best_config(
            lambda config: pt.image_to_data(img, config=config, output_type=pt.Output.DICT),
            TESSERACT_CONFIGS,
            _score_data,
            min_score=MIN_OCR_CHARS,
            label=f'pagina {page_index + 1}',
        )

        paragraphs = _to_paragraphs(data)
        if not paragraphs:
            logger.info('[OCR] Nada reconhecido na pagina %d', page_index + 1)
        return paragraphs

    except Exception:
        logger.exception('[OCR] Falha na pagina %d', page_index + 1)
        return []


def _to_paragraphs(data):
    """Agrupa as palavras do Tesseract em parágrafos legíveis."""
    blocks, order = {}, []

    for i, raw_text in enumerate(data['text']):
        if int(data['conf'][i]) < MIN_CONFIDENCE:
            continue
        text = raw_text.strip()
        if not text:
            continue

        key = (data['block_num'][i], data['par_num'][i])
        if key not in blocks:
            blocks[key] = {}
            order.append(key)

        line_key = data['line_num'][i]
        blocks[key].setdefault(line_key, []).append((data['left'][i], text))

    paragraphs = []
    for key in order:
        lines = blocks[key]

        pieces = []
        for line_num in sorted(lines):
            piece = ''
            for _, word in sorted(lines[line_num]):
                # Mantém as palavras hifenizadas no fim da linha unidas
                piece += word if piece.endswith('-') else ((' ' if piece else '') + word)
            pieces.append(piece)

        paragraph = ''
        for piece in pieces:
            paragraph += piece if paragraph.endswith('-') else ((' ' if paragraph else '') + piece)

        paragraph = paragraph.strip()
        if len(paragraph) >= 2:
            paragraphs.append(paragraph)

    return paragraphs
