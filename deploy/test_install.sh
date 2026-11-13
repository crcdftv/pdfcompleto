#!/usr/bin/env bash
# Testa o install.sh num ambiente simulado (stubs), para validar os
# arquivos systemd/nginx gerados sem precisar de root de verdade.
set -euo pipefail

# A raiz do repo pode vir de REPO_ROOT (quando o script e via stdin, ex.:
#   Get-Content test_install.sh -Raw | docker exec -i ... bash -s
# ) ou ser deduzida do proprio arquivo.
if [ -n "${REPO_ROOT:-}" ]; then
    RAIZ="$REPO_ROOT"
else
    RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
fi
[ -f "$RAIZ/deploy/install.sh" ] || { echo "ERRO: deploy/install.sh nao encontrado em $RAIZ"; exit 1; }
TESTE="$(mktemp -d)"
STUBS="$TESTE/bin"
mkdir -p "$STUBS"

cat > "$STUBS/apt-get" <<'EOF'
#!/bin/sh
echo "[stub apt-get] $*"
exit 0
EOF
cat > "$STUBS/systemctl" <<'EOF'
#!/bin/sh
echo "[stub systemctl] $*"
exit 0
EOF
cat > "$STUBS/nginx" <<'EOF'
#!/bin/sh
echo "[stub nginx] $*"
exit 0
EOF
cat > "$STUBS/useradd" <<'EOF'
#!/bin/sh
echo "[stub useradd] $*"
exit 0
EOF
cat > "$STUBS/id" <<'EOF'
#!/bin/sh
exit 0
EOF
cat > "$STUBS/sudo" <<'EOF'
#!/bin/sh
# remove -u <user> e executa o comando de verdade
if [ "$1" = "-u" ]; then shift 2; fi
exec "$@"
EOF
cat > "$STUBS/tesseract" <<'EOF'
#!/bin/sh
if [ "$1" = "--version" ]; then echo "tesseract 5.5.0 (stub)"; exit 0; fi
if [ "$1" = "--list-langs" ]; then echo "List of available languages:"; echo "eng"; echo "por"; exit 0; fi
exit 0
EOF
cat > "$STUBS/git" <<'EOF'
#!/bin/sh
# git clone: copia o repo de origem sem usar a rede
if [ "$1" = "clone" ]; then
    origem="$2"; destino="$3"
    mkdir -p "$destino"
    cp -r "$origem/." "$destino/" 2>/dev/null || true
    rm -rf "$destino/.git"
    echo "[stub git] clone $origem -> $destino"
    exit 0
fi
echo "[stub git] $*"
exit 0
EOF

chmod +x "$STUBS"/*

export PATH="$STUBS:$PATH"
export INSTALL_DIR="$TESTE/opt/pdfcompleto"
export DATA_DIR="$TESTE/var/lib/pdfcompleto"
export ENV_FILE="$TESTE/etc/pdfcompleto.env"
export SERVER_NAME="pdf.exemplo.com.br"
export APP_PORT="5000"
export OCR_MAX_WORKERS="2"
export MEMORY_MAX="3G"

# pip stub: evita baixar as 52 dependencias de verdade
mkdir -p "$INSTALL_DIR/.venv/bin"
cat > "$INSTALL_DIR/.venv/bin/pip" <<'EOF'
#!/bin/sh
echo "[stub pip] $*"
exit 0
EOF
chmod +x "$INSTALL_DIR/.venv/bin/pip"
# venv ja existe -> o install.sh nao tenta criar
mkdir -p "$INSTALL_DIR/deploy"
cp "$RAIZ/deploy/install.sh" "$INSTALL_DIR/deploy/install.sh"

echo "=== executando install.sh (simulado) ==="
bash "$INSTALL_DIR/deploy/install.sh"

echo
echo "=================== $ENV_FILE ==================="
cat "$ENV_FILE" 2>/dev/null || echo "(nao gerado)"

echo
echo "=================== unit systemd ==================="
cat /etc/systemd/system/pdfcompleto.service 2>/dev/null || echo "(nao gerado)"

echo
echo "=================== nginx ==================="
cat /etc/nginx/sites-available/pdfcompleto 2>/dev/null || echo "(nao gerado)"

echo
echo "=================== permissoes ==================="
ls -ld "$ENV_FILE" "$DATA_DIR" 2>/dev/null || true
ls -l "$DATA_DIR" 2>/dev/null || true

rm -rf "$TESTE"
