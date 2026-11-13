"""
gui_desktop.py – Interface desktop que encapsula o sistema Flask existente.

Inicia o servidor Flask EM THREAD dentro do mesmo processo e exibe a
interface web dentro de uma janela nativa PyQt6 (QWebEngineView).

Comportamento single-instance: se o programa já está rodando, envia o
caminho do PDF para a instância existente e fecha a nova janela.
"""

import sys
import os
import re
import time
import signal
import socket
import threading
import traceback
import logging
import tempfile

# ── Log de erros para debugar quando crashar ──────────────────
LOG_PATH = os.path.join(os.path.expanduser("~"), "pdfcompleto_desktop.log")
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("gui_desktop")


def _excepthook(exc_type, exc_value, exc_tb):
    msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logger.error("Exceção não tratada:\n%s", msg)
    print(msg)
sys.excepthook = _excepthook


def _base_dir():
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        internal = os.path.join(exe_dir, "_internal")
        return internal if os.path.isdir(internal) else exe_dir
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = _base_dir()
os.chdir(BASE_DIR)

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


# ── Cria todas as pastas necessárias ANTES de importar app.py ──
REQUIRED_DIRS = [
    "uploads", "ocr_outputs", "signed", "compressed",
    ".flask_session", "static", "templates",
]
for d in REQUIRED_DIRS:
    os.makedirs(os.path.join(BASE_DIR, d), exist_ok=True)


# ──────────────────────────────────────────────────────────────
# Configurações
# ──────────────────────────────────────────────────────────────
FLASK_HOST = "127.0.0.1"
FLASK_PORT = 5000
FLASK_URL = f"http://{FLASK_HOST}:{FLASK_PORT}"
STARTUP_TIMEOUT = 20
WINDOW_TITLE = "PDFCompleto - Editor de PDFs"

# Arquivo de sinal para single-instance (comunicação entre processos)
SIGNAL_FILE = os.path.join(tempfile.gettempdir(), "pdfcompleto_open_requests.txt")
# Arquivo PID para detectar instância ativa
PID_FILE = os.path.join(tempfile.gettempdir(), "pdfcompleto_desktop.pid")


# ──────────────────────────────────────────────────────────────
# Imports PyQt6
# ──────────────────────────────────────────────────────────────
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget,
    QMessageBox, QStatusBar, QLabel
)
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt, QUrl, QTimer
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineProfile


# ──────────────────────────────────────────────────────────────
# Utilitários
# ──────────────────────────────────────────────────────────────
def _is_port_in_use(port, host="127.0.0.1"):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0


def _wait_for_flask(url, timeout=STARTUP_TIMEOUT):
    import urllib.request, urllib.error
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.3)
    return False


def _is_instance_running():
    """Verifica se já existe uma instância rodando."""
    if not os.path.isfile(PID_FILE):
        return False
    try:
        with open(PID_FILE, "r") as f:
            pid = int(f.read().strip())
        # Verifica se o processo ainda existe no Windows
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    except Exception:
        return False


def _write_pid():
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def _remove_pid():
    try:
        os.remove(PID_FILE)
    except Exception:
        pass


def _send_file_to_running_instance(file_path):
    """Escreve o caminho do PDF no arquivo de sinal para a instância ativa."""
    try:
        with open(SIGNAL_FILE, "a", encoding="utf-8") as f:
            f.write(file_path + "\n")
        logger.info("Sinal enviado para instância existente: %s", file_path)
        return True
    except Exception as e:
        logger.error("Erro ao enviar sinal: %s", e)
        return False


# ──────────────────────────────────────────────────────────────
# Inicia Flask em thread daemon
# ──────────────────────────────────────────────────────────────
_flask_thread = None

def _run_flask():
    try:
        logger.info("Importando app.py...")
        from app import app
        logger.info("Flask app importado. Iniciando servidor na porta %d...", FLASK_PORT)
        app.run(host=FLASK_HOST, port=FLASK_PORT, debug=False, use_reloader=False, threaded=True)
    except Exception as e:
        logger.error("Erro ao iniciar Flask: %s\n%s", e, traceback.format_exc())
        raise


def start_flask_thread():
    global _flask_thread
    if _is_port_in_use(FLASK_PORT):
        logger.info("Porta %d já em uso. Assume Flask já rodando.", FLASK_PORT)
        return True
    _flask_thread = threading.Thread(target=_run_flask, daemon=True, name="FlaskThread")
    _flask_thread.start()
    logger.info("Thread Flask iniciada. Aguardando resposta...")
    return True


# ──────────────────────────────────────────────────────────────
# Aba do navegador
# ──────────────────────────────────────────────────────────────
class BrowserTab(QWebEngineView):
    def __init__(self, main_window):
        super().__init__(QWebEngineProfile.defaultProfile())
        self.main_window = main_window

    def createWindow(self, _type):
        return self.main_window.add_new_tab()


# ──────────────────────────────────────────────────────────────
# Janela Principal
# ──────────────────────────────────────────────────────────────
class PDFDesktopApp(QMainWindow):
    def __init__(self, open_file=None):
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.setMinimumSize(1024, 700)
        self.showMaximized()

        icon_path = os.path.join(BASE_DIR, "signature.ico")
        if os.path.isfile(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self._open_file = open_file

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.setCornerWidget(self._create_new_tab_button())
        self.setCentralWidget(self.tabs)

        from PyQt6.QtGui import QShortcut, QKeySequence
        QShortcut(QKeySequence("Ctrl+T"), self, activated=lambda: self.add_new_tab())

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_label = QLabel("Iniciando servidor...")
        self.status_bar.addWidget(self.status_label)

        self.add_new_tab(QUrl("about:blank"), "Aguardando...")

        # Timer para monitorar novos PDFs de outras instâncias
        self._signal_timer = QTimer(self)
        self._signal_timer.timeout.connect(self._check_signal_file)
        self._signal_timer.start(1000)

        QTimer.singleShot(100, self._init_flask_and_connect)

    # ── Monitoramento de sinais ──────────────────────────────
    def _check_signal_file(self):
        """Verifica se outra instância enviou um PDF para abrir."""
        if not os.path.isfile(SIGNAL_FILE):
            return
        try:
            with open(SIGNAL_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if not lines:
                return
            # Limpa o arquivo imediatamente
            open(SIGNAL_FILE, "w").close()
            for line in lines:
                path = line.strip()
                if path and os.path.isfile(path):
                    logger.info("Recebido PDF de outra instância: %s", path)
                    self._open_pdf_from_signal(path)
        except Exception as e:
            logger.error("Erro ao ler sinal: %s", e)

    def _open_pdf_from_signal(self, file_path):
        """Abre um PDF recebido de outra instância em nova aba."""
        tab = self.add_new_tab()
        self._load_pdf_in_browser(tab, file_path)

    # ── Flask ─────────────────────────────────────────────
    def _init_flask_and_connect(self):
        self.status_label.setText("Iniciando servidor...")
        QApplication.processEvents()
        try:
            start_flask_thread()
        except Exception as e:
            self.status_label.setText(f"Erro ao iniciar Flask: {e}")
            logger.error("Falha ao iniciar Flask: %s", e)
            QMessageBox.critical(self, "Erro", f"Falha ao iniciar o servidor:\n{e}")
            return
        QTimer.singleShot(500, self._try_connect)

    def _try_connect(self):
        if _wait_for_flask(FLASK_URL):
            self.status_label.setText("Conectado ao servidor.")
            current = self.tabs.currentWidget()
            if current and isinstance(current, BrowserTab):
                if self._open_file:
                    self._load_pdf_in_browser(current, self._open_file)
                    self._open_file = None
                else:
                    current.setUrl(QUrl(FLASK_URL))
                current.urlChanged.connect(lambda u, v=current: self._on_url_changed(v, u))
                current.titleChanged.connect(lambda t, v=current: self._on_title_changed(v, t))
        else:
            self.status_label.setText("Tentando novamente...")
            QTimer.singleShot(1000, self._try_connect_again)

    def _try_connect_again(self):
        if _wait_for_flask(FLASK_URL, timeout=30):
            self.status_label.setText("Conectado ao servidor.")
            current = self.tabs.currentWidget()
            if current and isinstance(current, BrowserTab):
                if self._open_file:
                    self._load_pdf_in_browser(current, self._open_file)
                    self._open_file = None
                else:
                    current.setUrl(QUrl(FLASK_URL))
                current.urlChanged.connect(lambda u, v=current: self._on_url_changed(v, u))
                current.titleChanged.connect(lambda t, v=current: self._on_title_changed(v, t))
        else:
            self.status_label.setText("Falha ao conectar ao servidor.")
            QMessageBox.warning(
                self, "Timeout",
                f"O servidor Flask não respondeu.\nVerifique o log em:\n{LOG_PATH}"
            )

    def _load_pdf_in_browser(self, view, file_path):
        """Navega para /open?path= — o Flask copia o PDF e redireciona para auto-load."""
        import urllib.parse
        open_url = f"{FLASK_URL}/open?path={urllib.parse.quote(file_path)}"
        logger.info("Navegando para: %s", open_url)
        view.setUrl(QUrl(open_url))

    # ── Botão Nova Aba ────────────────────────────────────
    def _create_new_tab_button(self):
        from PyQt6.QtWidgets import QPushButton
        btn = QPushButton("+")
        btn.setFixedSize(28, 28)
        btn.setToolTip("Nova Aba (Ctrl+T)")
        btn.clicked.connect(lambda: self.add_new_tab())
        return btn

    # ── Tabs ──────────────────────────────────────────────
    def add_new_tab(self, url=None, title="Nova Aba"):
        view = BrowserTab(self)
        if url and url.toString() != "about:blank":
            view.setUrl(url)
        else:
            view.setUrl(QUrl(FLASK_URL))
        view.urlChanged.connect(lambda u, v=view: self._on_url_changed(v, u))
        view.titleChanged.connect(lambda t, v=view: self._on_title_changed(v, t))
        i = self.tabs.addTab(view, title)
        self.tabs.setCurrentIndex(i)
        return view

    def _close_tab(self, index):
        if self.tabs.count() <= 1:
            return
        widget = self.tabs.widget(index)
        self.tabs.removeTab(index)
        if widget:
            widget.deleteLater()

    def _on_url_changed(self, view, url):
        idx = self.tabs.indexOf(view)
        if idx >= 0:
            self.tabs.setTabText(idx, url.host() or "Nova Aba")

    def _on_title_changed(self, view, title):
        idx = self.tabs.indexOf(view)
        if idx >= 0:
            display = title if title and title != view.url().host() else view.url().host()
            self.tabs.setTabText(idx, display or "Nova Aba")

    # ── Fechar ────────────────────────────────────────────
    def closeEvent(self, event):
        self._signal_timer.stop()
        _remove_pid()
        logger.info("Janela fechada. Encerrando aplicação.")
        event.accept()


# ──────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────
def main():
    logger.info("=" * 60)
    logger.info("PDFCompleto Desktop iniciando...")
    logger.info("BASE_DIR: %s", BASE_DIR)
    logger.info("Python: %s", sys.executable)
    logger.info("Frozen: %s", getattr(sys, "frozen", False))
    logger.info("Args: %s", sys.argv)

    signal.signal(signal.SIGINT, signal.SIG_DFL)

    # Verifica se recebeu um caminho de PDF como argumento
    open_file = None
    for arg in sys.argv[1:]:
        if arg.lower().endswith('.pdf'):
            candidate = os.path.abspath(arg)
            if os.path.isfile(candidate):
                open_file = candidate
                logger.info("Arquivo PDF para abrir: %s", open_file)
                break

    # ── Single instance: se já rodando, envia sinal e fecha ──
    if _is_instance_running():
        logger.info("Instância já rodando (Flask na porta %d).", FLASK_PORT)
        if open_file:
            _send_file_to_running_instance(open_file)
            logger.info("PDF enviado para instância existente. Saindo.")
        else:
            logger.info("Sem PDF para abrir. Saindo.")
        return

    # ── Primeira instância: inicia normalmente ──
    _write_pid()
    logger.info("Primeira instância. Criando PID file.")

    app = QApplication(sys.argv)
    app.setApplicationName("PDFCompleto")
    app.setOrganizationName("PDFCompleto")

    window = PDFDesktopApp(open_file=open_file)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
