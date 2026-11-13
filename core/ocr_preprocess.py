"""
Pré-processamento de imagem e execução do Tesseract com fallback de configuração.

Compartilhado pelos três fluxos de OCR (PDF pesquisável, Word e Excel) para
manter a mesma rotina de melhoria de qualidade: normalização de contraste,
correção de inclinação (deskew) e nova tentativa com outros modos de
segmentação quando o reconhecimento sai ruim.
"""
import logging

from PIL import Image, ImageEnhance, ImageOps

logger = logging.getLogger(__name__)

# Ângulo mínimo (graus) para justificar a correção de inclinação
# (abaixo disso o ganho é irrelevante e o risco de falso positivo é real)
MIN_SKEW_DEGREES = 1.0
# Limite de inclinação corrigida: acima disso é quase certamente um falso positivo
MAX_SKEW_DEGREES = 8.0

# Pontuação mínima (caracteres reconhecidos) para aceitar o resultado
DEFAULT_MIN_CHARS = 30

# Palavras abaixo desta confiança entram como ruído na camada de busca
DEFAULT_MIN_CONFIDENCE = 40


def score_words(data, min_confidence=DEFAULT_MIN_CONFIDENCE):
    """Caracteres reconhecidos acima do corte de confiança (saída image_to_data)."""
    total = 0
    for raw, conf in zip(data['text'], data['conf']):
        try:
            ok = int(conf) >= min_confidence
        except (TypeError, ValueError):
            ok = False
        text = raw.strip()
        if ok and text:
            total += len(text)
    return total


def _detect_skew(gray):
    """Ângulo (graus) da inclinação das linhas de texto. 0.0 = sem evidência.

    Usa a transformada de Hough sobre as arestas do texto: linhas de texto são
    segmentos longos e (quase) horizontais, então o pico de ângulos é estável
    mesmo em páginas inteiras de texto — ao contrário de medir o retângulo
    envolvente, que fica ambíguo em páginas quase quadradas.
    """
    import math

    import cv2
    import numpy as np

    arr = np.asarray(gray)
    mask = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]

    # Corta a borda: cópias digitalizadas costumam ter moldura escura que
    # contaminaria a medição.
    h, w = mask.shape
    inner = mask[int(h * 0.03):int(h * 0.97), int(w * 0.03):int(w * 0.97)]
    if inner.size == 0:
        return 0.0

    # Reduz para acelerar o Hough em páginas de alta resolução
    ih, iw = inner.shape
    if iw > 1500:
        scale = 1500.0 / iw
        inner = cv2.resize(inner, (int(iw * scale), int(ih * scale)),
                           interpolation=cv2.INTER_AREA)

    edges = cv2.Canny(inner, 60, 160)
    min_length = max(40, int(inner.shape[1] * 0.05))
    lines = cv2.HoughLinesP(edges, 1, np.pi / 720, threshold=60,
                            minLineLength=min_length, maxLineGap=6)
    if lines is None:
        return 0.0

    angles, weights = [], []
    for x1, y1, x2, y2 in lines[:, 0]:
        dx, dy = x2 - x1, y2 - y1
        angle = math.degrees(math.atan2(dy, dx))
        if angle > 90:
            angle -= 180
        elif angle < -90:
            angle += 180
        if abs(angle) <= MAX_SKEW_DEGREES + 7:  # descarta diagonais/marcas
            angles.append(angle)
            weights.append(math.hypot(dx, dy))

    if len(angles) < 8:
        return 0.0

    # Mediana ponderada pelo comprimento: linhas de texto pesam mais que
    # rabiscos e carimbos
    order = np.argsort(angles)
    ordered = np.array(angles, dtype=float)[order]
    cum = np.cumsum(np.array(weights, dtype=float)[order])
    idx = int(np.searchsorted(cum, cum[-1] / 2.0))
    return float(ordered[min(idx, len(ordered) - 1)])


def _deskew(gray):
    """Corrige a inclinação do texto digitalizado. Devolve (imagem, ângulo)."""
    try:
        import cv2  # noqa: F401
    except Exception:
        return gray, 0.0

    try:
        if gray.mode != 'L':
            gray = gray.convert('L')
        angle = _detect_skew(gray)
        if not (MIN_SKEW_DEGREES <= abs(angle) <= MAX_SKEW_DEGREES):
            return gray, 0.0

        rotated = gray.rotate(angle, resample=Image.BICUBIC, fillcolor=255)

        # Só mantém se a medição pós-rotação melhorou de verdade
        # (evita girar página reta por causa de carimbo/assinatura torto)
        residual = abs(_detect_skew(rotated))
        if residual > max(MIN_SKEW_DEGREES, 0.5 * abs(angle)):
            return gray, 0.0
        return rotated, angle
    except Exception:
        logger.debug('[OCR] Deskew ignorado por falha', exc_info=True)
        return gray, 0.0


def prepare_for_ocr(img, *, deskew=True, sharpen=1.5, cutoff=0.5):
    """Normaliza a página renderizada para o Tesseract.

    - escala de cinza
    - correção de inclinação quando o texto está torto
    - autocontraste (melhor que o fator fixo de contraste: não satura
      claros/escuros e melhora digitalizações escuras ou apagadas)
    - nitidez moderada (excesso de nitidez cria halos que confundem o OCR;
      filtro de mediana não entrou: apagava traços finos e piorava o resultado)
    """
    gray = img.convert('L')
    if deskew:
        gray, angle = _deskew(gray)
        if angle:
            logger.debug('[OCR] Deskew de %.2f graus aplicado', angle)
    gray = ImageOps.autocontrast(gray, cutoff=cutoff)
    if sharpen != 1.0:
        gray = ImageEnhance.Sharpness(gray).enhance(sharpen)
    return gray.convert('RGB')


def run_best_config(run, configs, score_of, min_score=DEFAULT_MIN_CHARS, label=''):
    """Executa `run(config)` até o resultado atingir `min_score`.

    `run(config)` devolve o resultado bruto; `score_of(result)` devolve um número
    (quanto maior, melhor). A configuração seguinte só roda quando a anterior
    não bateu o mínimo — assim não há custo extra nos casos normais. Página com
    pouco texto (capa, título isolado) para cedo quando uma nova tentativa não
    traz ganho; se todas derem zero, tenta a última (modo de texto esparsó).
    Se nenhuma atingir `min_score`, devolve a melhor obtida.
    """
    best_result, best_score = None, -1

    for config in configs:
        try:
            result = run(config)
            score = score_of(result)
        except Exception:
            logger.exception('[OCR] Falha%s na configuração: %s', f' {label}' if label else '', config)
            continue

        if score > best_score:
            best_result, best_score = result, score
            if best_score >= min_score:
                return best_result
        elif best_result is not None and best_score > 0:
            # Tentativa diferente sem ganho e já existe texto: a página não tem
            # mais o que oferecer. Zero em todas as tentativas tenta a última
            # configuração (caso típico de página só com um título isolado).
            break

    if best_result is None:
        raise RuntimeError(f'OCR não produziu resultado em {len(configs)} tentativas')
    return best_result
