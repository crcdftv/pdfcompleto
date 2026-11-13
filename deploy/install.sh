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
#   OCR_MAX_WORKERS=2      # paginas em paralelo no OCR (menor = menos RAM)
#   MEMORY_MAX=            # limite de RAM do servico (ex.: 3G); vazio = sem limite
#
# Depois:  sudo bash deploy/update.sh   (para atualizar o codigo)
# =====================================================================
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/crcdftv/pdfcompleto.git}"
INSTALL_DIR="${INSTALL_DIR:-/opt/pdfcompleto}"
DATA_DIR="${DATA_DIR:-/var/lib/pdfcompleto}"
APP_PORT="${APP_PORT:-5000}"
SERVER_NAME="${SERVER_NAME:-_}"
OCR_MAX_WORKERS="${OCR_MAX_WORKERS:-2}"
MEMORY_MAX="${MEMORY_MAX:-}"
APP_USER="pdfcompleto"
ENV_FILE="${ENV_FILE:-/etc/pdfcompleto.env}"

log()  { echo -e "\n\033[1;36m==> $*\033[0m"; }
erro() { echo -e "\033[1;31mERRO: $*\033[0m" >&2; exit 1; }

[[ $EUID -eq 0 ]] || erro "rode como root (sudo bash deploy/install.sh)"
command -v apt-get >/dev/null || erro "script preparado para Ubuntu/Debian (apt)"

# ---------------------------------------------------------------- 1. sistema
log "1/8 Instalando pacotes do sistema"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
    python3 python3-venv python3-pip \
    tesseract-ocr tesseract-ocr-por tesseract-ocr-eng \
    poppler-utils \
    nginx git curl ca-certificates

log "2/8 Verificando o Tesseract"
tesseract --version | head -1 || erro "Tesseract nao instalado"
tesseract --list-langs 2>/dev/null | grep -q '^por$' || erro "idioma 'por' do Tesseract ausente"

# ---------------------------------------------------------------- 3. usuario
log "3/8 Criando usuario do sistema ($APP_USER)"
id -u "$APP_USER" >/dev/null 2>&1 || \
    useradd --system --create-home --home-dir /home/$APP_USER --shell /usr/sbin/nologin "$APP_USER"

# ---------------------------------------------------------------- 4. codigo
log "4/8 Baixando o codigo"
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "repositorio ja existe, atualizando..."
    git -C "$INSTALL_DIR" pull --ff-only || echo "aviso: git pull falhou, seguindo com a versao local"
else
    rmdir "$INSTALL_DIR" 2>/dev/null || true
    git clone "$REPO_URL" "$INSTALL_DIR" || erro "git clone falhou. Se o repo e privado, use REPO_URL com token:
    export REPO_URL='https://USUARIO:TOKEN@github.com/SEU_USUARIO/pdfcompleto.git'"
fi
chown -R "$APP_USER:$APP_USER" "$INSTALL_DIR"

# ---------------------------------------------------------------- 5. python
log "5/8 Criando ambiente virtual e instalando dependencias"
cd "$INSTALL_DIR"
[ -d .venv ] || sudo -u "$APP_USER" python3 -m venv .venv
sudo -u "$APP_USER" "$INSTALL_DIR/.venv/bin/pip" install -q --upgrade pip wheel
sudo -u "$APP_USER" "$INSTALL_DIR/.venv/bin/pip" install -q -r requirements.txt

# ---------------------------------------------------------------- 6. dados
log "6/8 Preparando pasta de dados ($DATA_DIR)"
mkdir -p "$DATA_DIR"/{uploads,ocr_outputs,signed,compressed,.flask_session}
chown -R "$APP_USER:$APP_USER" "$DATA_DIR"
chmod 750 "$DATA_DIR"

# ---------------------------------------------------------------- 7. ambiente
log "7/8 Gerando configuracao ($ENV_FILE)"
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

# ---------------------------------------------------------------- 8. servico
log "8/8 Configurando systemd + nginx"

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

  HTTPS (recomendado em producao):
    certbot --nginx -d SEU_DOMINIO

  Para atualizar o codigo:
    sudo bash deploy/update.sh

EOF
