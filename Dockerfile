# PDFCompleto - imagem de producao (Linux)
#
# Build:  docker build -t pdfcompleto .
# Run:    docker run -d -p 5000:5000 -v pdfcompleto_dados:/data \
#             -e SECRET_KEY=$(openssl rand -hex 32) pdfcompleto
#
# Requisitos de sistema installados aqui:
#   - Tesseract OCR + portugues/ingles  (motor do OCR)
#   - Poppler                            (pdf2image / thumbnails)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PDFCOMPLETO_DATA_DIR=/data \
    TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata

RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-por \
        tesseract-ocr-eng \
        poppler-utils \
        libglib2.0-0 \
        libgomp1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# dependencias primeiro (cache do Docker)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /data/uploads /data/ocr_outputs /data/signed /data/compressed /data/.flask_session \
    && useradd --system --create-home --uid 10001 pdfcompleto \
    && chown -R pdfcompleto:pdfcompleto /app /data
USER pdfcompleto

VOLUME ["/data"]
EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:5000/health.json || exit 1

# 1 worker x 4 threads: o OCR usa o Tesseract (processo externo), nao o GIL
# keep-alive 65s: o front consulta o progresso do OCR a cada 1s e o default
# do gunicorn (2s) fecha a conexao ociosa no meio do poll.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "4", \
     "--timeout", "3600", "--graceful-timeout", "60", "--keep-alive", "65", \
     "app:app"]
