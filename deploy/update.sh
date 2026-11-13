#!/usr/bin/env bash
# =====================================================================
# PDFCompleto - atualiza o codigo e reinicia o servico
#
#   sudo bash deploy/update.sh
#
# Requer que o install.sh ja tenha sido executado na mesma maquina.
# =====================================================================
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/pdfcompleto}"
APP_USER="pdfcompleto"
APP_PORT="${APP_PORT:-5000}"

log()  { echo -e "\n\033[1;36m==> $*\033[0m"; }
erro() { echo -e "\033[1;31mERRO: $*\033[0m" >&2; exit 1; }

[[ $EUID -eq 0 ]] || erro "rode como root (sudo bash deploy/update.sh)"
[ -d "$INSTALL_DIR/.git" ] || erro "repositorio nao encontrado em $INSTALL_DIR"

log "Atualizando o codigo"
sudo -u "$APP_USER" git -C "$INSTALL_DIR" pull --ff-only

log "Atualizando dependencias"
sudo -u "$APP_USER" "$INSTALL_DIR/.venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"

log "Reiniciando o servico"
systemctl restart pdfcompleto
sleep 5
systemctl --no-pager --lines=5 status pdfcompleto || true

log "Pronto"
echo "  Health: curl http://127.0.0.1:$APP_PORT/health.json"
echo "  Logs:   journalctl -u pdfcompleto -f"
