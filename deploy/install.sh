#!/usr/bin/env bash
# =====================================================================
# PDFCompleto - instalador automatico (Ubuntu / Debian)
#
#   sudo bash deploy/install.sh
#
# Variaveis de ambiente opcionais:
#   REPO_URL=https://github.com/SEU_USUARIO/pdfcompleto.git
#   INSTALL_DIR=/opt/pdfcompleto
#   DATA_DIR=/var/lib/pdfcompleto
#   APP_PORT=5000
#   SERVER_NAME=pdf.seudominio.com.br
#   PYTHON_VERSION=3.12        # versao do Python (3.11-3.13 tem wheels)
#   OCR_MAX_WORKERS=2          # paginas em paralelo no OCR (menor = menos RAM)
#   MEMORY_MAX=                # limite de RAM do servico (ex.: 3G); vazio = sem limite
#
# Depois:  sudo bash deploy/update.sh   (para atualizar o codigo)
# =====================================================================
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/crcdftv/pdfcompleto.git}"
INSTALL_DIR="${INSTALL_DIR:-/opt/pdfcompleto}"
DATA_DIR="${DATA_DIR:-/var/lib/pdfcompleto}"
APP_PORT="${APP_PORT:-5000}"
SERVER_NAME="${SERVER_NAME:-_}"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"
OCR_MAX_WORKERS="${OCR_MAX_WORKERS:-2}"
MEMORY_MAX="${MEMORY_MAX:-}"
APP_USER="pdfcompleto"
ENV_FILE="${ENV_FILE:-/etc/pdfcompleto.env}"
UV_DIR="/opt/python"

log()  { echo -e "\n\033[1;36m==> $*\033[0m"; }
erro() { echo -e "\033[1;31mERRO: $*\033[0m" >&2; exit 1; }

[[ $EUID -eq 0 ]] || erro "rode como root (sudo bash deploy/install.sh)"
command -v apt-get >/dev/null || erro "script preparado para Ubuntu/Debian (apt)"

# ---------------------------------------------------------------- 1. sistema
log "1/9 Instalando pacotes do sistema"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
    python3 python3-venv python3-pip \
    tesseract-ocr tesseract-ocr-por tesseract-ocr-eng \
    poppler-utils \
    nginx git curl ca-certificates ca-certificates \
    build-essential pkg-config \
    libxml2-dev libxslt1-dev zlib1g-dev libjpeg-dev libffi-dev libssl-dev

# ---------------------------------------------------------------- 2. python
# Ubuntu 26.04 vem com Python 3.14, para o qual varios pacotes fixados
# (numpy, pandas, lxml, pikepdf) NAO tem wheel pre-compilado: todos tentam
# compilar do zero e falham. Por isso o instalador garante um Python 3.12
# (a mesma versao validada no Dockerfile).
log "2/9 Selecionando o Python (alvo: $PYTHON_VERSION)"
PYTHON_BIN=""

# a) ja existe no sistema?
for v in "$PYTHON_VERSION" 3.13 3.12 3.11; do
    if command -v "python$v" >/dev/null 2>&1; then
        PYTHON_BIN="python$v"
        break
    fi
done

# b) instalar via apt (python3.12/python3.13 podem estar no universe)
if [ -z "$PYTHON_BIN" ]; then
    for v in "$PYTHON_VERSION" 3.13 3.12; do
        if apt-get install -y -qq "python$v" "python$v-venv" "python$v-dev" >/dev/null 2>&1 \
           && command -v "python$v" >/dev/null 2>&1; then
            PYTHON_BIN="python$v"
            break
        fi
    done
fi

# c) ultimo recurso: uv instala um Python "standalone" em /opt/python
if [ -z "$PYTHON_BIN" ]; then
    echo "Python $PYTHON_VERSION nao encontrado no apt; usando uv"
    curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh >/dev/null 2>&1 \
        || erro "falha ao instalar uv (https://astral.sh/uv/install.sh)"
    export UV_PYTHON_INSTALL_DIR="$UV_DIR"
    uv python install "$PYTHON_VERSION" >/dev/null 2>&1 \
        || erro "uv nao conseguiu instalar o Python $PYTHON_VERSION"
    chmod -R a+rX "$UV_DIR"
    PYTHON_BIN="$(uv python find "$PYTHON_VERSION" 2>/dev/null || true)"
    [ -n "$PYTHON_BIN" ] || erro "uv nao localizei o Python $PYTHON_VERSION"
fi

echo "    Python: $PYTHON_BIN ($("$PYTHON_BIN" --version 2>&1))"

# ---------------------------------------------------------------- 3. tesseract
log "3/9 Verificando o Tesseract"
tesseract --version | head -1 || erro "Tesseract nao instalado"
tesseract --list-langs 2>/dev/null | grep -q '^por$' || erro "idioma 'por' do Tesseract ausente"

# ---------------------------------------------------------------- 4. usuario
log "4/9 Criando usuario do sistema ($APP_USER)"
id -u "$APP_USER" >/dev/null 2>&1 || \
    useradd --system --create-home --home-dir /home/$APP_USER --shell /usr/sbin/nologin "$APP_USER"

# ---------------------------------------------------------------- 5. codigo
log "5/9 Baixando o codigo"
mkdir -p "$INSTALL_DIR"
chown "$APP_USER:$APP_USER" "$INSTALL_DIR"
# git recusa repositorio com dono diferente (safe.directory)
git config --global --add safe.directory "$INSTALL_DIR" || true
sudo -u "$APP_USER" git config --global --add safe.directory "$INSTALL_DIR" || true

if [ -d "$INSTALL_DIR/.git" ]; then
    echo "repositorio ja existe, atualizando..."
    sudo -u "$APP_USER" git -C "$INSTALL_DIR" pull --ff-only \
        || echo "aviso: git pull falhou, seguindo com a versao local"
else
    # apaga restos de uma instalacao anterior sem .git
    find "$INSTALL_DIR" -mindepth 1 -maxdepth 1 ! -name '.venv' -exec rm -rf {} + 2>/dev/null || true
    sudo -u "$APP_USER" git clone "$REPO_URL" "$INSTALL_DIR" || erro "git clone falhou. Se o repo e privado, use REPO_URL com token:
    export REPO_URL='https://USUARIO:TOKEN@github.com/SEU_USUARIO/pdfcompleto.git'"
fi

# ---------------------------------------------------------------- 6. python/venv
log "6/9 Criando ambiente virtual e instalando dependencias"
cd "$INSTALL_DIR"

# recria o venv se a versao do Python mudou (ex.: 3.14 -> 3.12)
VENV_MARKER="$INSTALL_DIR/.venv-python-version"
if [ -d "$INSTALL_DIR/.venv" ]; then
    ATUAL="$(cat "$VENV_MARKER" 2>/dev/null || echo '')"
    if [ "$ATUAL" != "$PYTHON_VERSION" ]; then
        if [ -n "$ATUAL" ]; then
            echo "    venv criado com Python $ATUAL, recriando com $PYTHON_VERSION"
        else
            echo "    venv existente sem versao registrada, recriando com $PYTHON_VERSION"
        fi
        rm -rf "$INSTALL_DIR/.venv"
    fi
fi

if [ ! -d "$INSTALL_DIR/.venv" ]; then
    if command -v uv >/dev/null 2>&1 && [ -x "$PYTHON_BIN" ]; then
        # python veio do uv: --seed coloca o pip dentro do venv
        UV_PYTHON_INSTALL_DIR="$UV_DIR" uv venv --seed --python "$PYTHON_BIN" "$INSTALL_DIR/.venv"
    else
        "$PYTHON_BIN" -m venv "$INSTALL_DIR/.venv"
    fi
    echo "$PYTHON_VERSION" > "$VENV_MARKER"
fi

"$INSTALL_DIR/.venv/bin/python" -m pip install -q --upgrade pip wheel \
    || "$INSTALL_DIR/.venv/bin/python" -m pip install -q --upgrade pip
"$INSTALL_DIR/.venv/bin/python" -m pip install -q -r requirements.txt \
    || erro "falha ao instalar as dependencias Python (veja o log acima)"

chown -R "$APP_USER:$APP_USER" "$INSTALL_DIR"

# ---------------------------------------------------------------- 7. dados
log "7/9 Preparando pasta de dados ($DATA_DIR)"
mkdir -p "$DATA_DIR"/{uploads,ocr_outputs,signed,compressed,logs,.flask_session}
chown -R "$APP_USER:$APP_USER" "$DATA_DIR"
chmod 750 "$DATA_DIR"

# ---------------------------------------------------------------- 8. ambiente
log "8/9 Gerando configuracao ($ENV_FILE)"
mkdir -p "$(dirname "$ENV_FILE")"
if [ ! -f "$ENV_FILE" ]; then
    SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    cat > "$ENV_FILE" <<EOF
# PDFCompleto - configuracao (nao versionar, nao compartilhar)
SECRET_KEY=$SECRET
PDFCOMPLETO_DATA_DIR=$DATA_DIR
TESSERACT_CMD=/usr/bin/tesseract
TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata
OCR_MAX_WORKERS=$OCR_MAX_WORKERS
# TOKEN_PIN=             # somente se a assinatura por token for usada
EOF
    chmod 640 "$ENV_FILE"
    chown root:"$APP_USER" "$ENV_FILE"
    echo "arquivo criado com um SECRET_KEY novo"
else
    echo "$ENV_FILE ja existe, mantido como esta"
    grep -q '^OCR_MAX_WORKERS=' "$ENV_FILE" || echo "OCR_MAX_WORKERS=$OCR_MAX_WORKERS" >> "$ENV_FILE"
fi

# ---------------------------------------------------------------- 9. servico
log "9/9 Configurando systemd + nginx"

MEMORY_LINE=""
[ -n "$MEMORY_MAX" ] && MEMORY_LINE="MemoryMax=$MEMORY_MAX"

cat > /etc/systemd/system/pdfcompleto.service <<EOF
[Unit]
Description=PDFCompleto (editor de PDF com OCR)
After=network.target

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$INSTALL_DIR/.venv/bin/gunicorn \\
    --bind 127.0.0.1:$APP_PORT \\
    --workers 1 --threads 4 \\
    --timeout 3600 --graceful-timeout 60 \\
    --keep-alive 65 \\
    app:app
Restart=always
RestartSec=5
$MEMORY_LINE
KillSignal=SIGTERM
TimeoutStopSec=90

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable pdfcompleto >/dev/null
systemctl restart pdfcompleto
sleep 5
systemctl --no-pager --lines=8 status pdfcompleto || true

mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled
cat > /etc/nginx/sites-available/pdfcompleto <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name $SERVER_NAME;

    # PDFs grandes (o maior de teste tinha 286 MB)
    client_max_body_size 512m;
    client_body_timeout 300s;

    # OCR de documentos longos pode demorar
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
    proxy_request_buffering off;

    location / {
        proxy_pass http://127.0.0.1:$APP_PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

ln -sf /etc/nginx/sites-available/pdfcompleto /etc/nginx/sites-enabled/pdfcompleto
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

# ---------------------------------------------------------------- pronto
log "Instalacao concluida"
cat <<EOF

  Aplicacao:  http://127.0.0.1:$APP_PORT
  Health:     curl http://127.0.0.1:$APP_PORT/health.json
  Logs:       journalctl -u pdfcompleto -f
  Nginx:      /etc/nginx/sites-available/pdfcompleto
  Dados:      $DATA_DIR
  Env:        $ENV_FILE
  Python:     $("$INSTALL_DIR/.venv/bin/python" --version 2>&1)

  HTTPS (recomendado em producao):
    certbot --nginx -d SEU_DOMINIO

  Para atualizar o codigo:
    sudo bash deploy/update.sh

EOF
