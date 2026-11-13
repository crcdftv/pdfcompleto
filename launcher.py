"""
launcher.py – ponto de entrada do executável cx_Freeze.

Responsabilidades:
  1. Ajusta sys.path para que o Flask encontre templates/ e static/
     dentro do diretório do executável (não do diretório de trabalho).
  2. Sobe o servidor Flask numa thread daemon.
  3. Aguarda o servidor ficar disponível (máx. 10 s).
  4. Abre o browser na URL local.
  5. Mantém o processo vivo até o usuário fechar a janela/processo.
"""

import sys
import os
import threading
import time
import webbrowser
import socket

# ── 1. Resolve o diretório base do executável ─────────────────────────────────
# Quando empacotado pelo cx_Freeze, sys.frozen == True e
# o executável fica em build/exe.win-xxx/; __file__ não é confiável.
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Garante que o Python encontre app.py e os módulos do projeto
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# ── 2. Cria pastas de dados necessárias (se não existirem) ───────────────────
for folder in ("uploads", "compressed", "ocr_outputs", "signed", ".flask_session"):
    os.makedirs(os.path.join(BASE_DIR, folder), exist_ok=True)

# ── 3. Porta disponível ───────────────────────────────────────────────────────
def _porta_livre(preferida: int = 5001) -> int:
    """Retorna a porta preferida se livre, senão encontra uma aleatória."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(("127.0.0.1", preferida)) != 0:
            return preferida
    # porta ocupada → deixa o SO escolher
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]

# Verifica se a porta foi passada via variável de ambiente (usado pelo run_gui.py)
porta_env = os.getenv("PDFCOMPLETO_PORT")
if porta_env:
    try:
        porta_preferida = int(porta_env)
        # Confere se a porta está livre; se não, busca uma livre
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", porta_preferida)) == 0:
                # Porta ocupada, busca uma livre usando a preferida
                PORT = _porta_livre(porta_preferida)
            else:
                PORT = porta_preferida
    except ValueError:
        # Valor inválido na variável de ambiente, usa padrão
        PORT = _porta_livre(5001)
else:
    PORT = _porta_livre(5001)

URL = f"http://127.0.0.1:{PORT}"

# ── 4. Importa e configura o app Flask ───────────────────────────────────────
# Precisa ser feito DEPOIS de ajustar sys.path
os.chdir(BASE_DIR)          # garante que caminhos relativos no app.py funcionem

from app import app          # importa o objeto Flask do seu app.py

# ── 5. Sobe o Flask em thread daemon ─────────────────────────────────────────
def _run_flask():
    app.run(
        host="127.0.0.1",
        port=PORT,
        debug=False,         # NUNCA True num executável
        use_reloader=False,  # reloader é incompatível com cx_Freeze
        threaded=True,
    )

flask_thread = threading.Thread(target=_run_flask, daemon=True)
flask_thread.start()

# ── 6. Aguarda o servidor responder (máx 10 s) ───────────────────────────────
def _servidor_pronto(url: str, tentativas: int = 20, intervalo: float = 0.5) -> bool:
    import urllib.request
    for _ in range(tentativas):
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:
            time.sleep(intervalo)
    return False

if os.getenv('NO_BROWSER') != '1':
    if _servidor_pronto(URL):
        webbrowser.open(URL)
    else:
        # Se demorou demais, abre mesmo assim – o browser vai aguardar/recarregar
        webbrowser.open(URL)

# ── 7. Mantém o processo vivo ─────────────────────────────────────────────────
# Como usamos base="Win32GUI" (sem console), precisamos manter o processo ativo.
# A thread Flask é daemon, então basta não deixar o processo principal terminar.
try:
    while True:
        time.sleep(60)
except KeyboardInterrupt:
    pass