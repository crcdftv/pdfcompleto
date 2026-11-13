import sys
import os
import time
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QFileDialog, QMessageBox, QTabWidget
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import QUrl, QStandardPaths, QObject, QTimer, pyqtSlot
from PyQt6.QtWebEngineCore import QWebEngineDownloadRequest, QWebEngineProfile

# 🚨 IMPORTANTE: URL DO SEU SERVIDOR FLASK
FLASK_SERVER_URL = "http://172.17.11.123:5000"
PDF_EDITOR_URL = QUrl(FLASK_SERVER_URL)


# =======================================================
# 📌 CLASSE 1: Tab do Navegador (QWebEngineView customizado)
# =======================================================
class BrowserTab(QWebEngineView):
    def __init__(self, parent_window, is_main=False):
        super().__init__(QWebEngineProfile.defaultProfile())
        self.parent_window = parent_window
        self.is_main = is_main

    def createWindow(self, type):
        new_view = self.parent_window.add_new_tab()
        return new_view


# =======================================================
# 📌 CLASSE 2: Janela Principal (Gerencia Abas e Lógica de Download/JS)
# =======================================================
class WebBrowserWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Unificador de PDFs")
        self.setGeometry(100, 100, 1000, 700)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.setCentralWidget(self.tabs)
        self.showMaximized()
        QWebEngineProfile.defaultProfile().downloadRequested.connect(self.download_requested)
        self.ocr_downloads_pending = {}
        self.add_new_tab(QUrl(FLASK_SERVER_URL), is_main=True)

    def add_new_tab(self, url=None, is_main=False):
        view = BrowserTab(self, is_main=is_main)
        if url: view.setUrl(url)
        view.urlChanged.connect(lambda u, v=view: self.update_tab_title(v, u))
        view.titleChanged.connect(lambda t, v=view: self.update_tab_title(v, v.url()))
        view.loadFinished.connect(self.on_tab_load_finished)
        i = self.tabs.addTab(view, "Nova Aba")
        self.tabs.setCurrentIndex(i)
        return view

    def update_tab_title(self, view, url):
        title = view.title() if view.title() and view.title() != url.host() else url.host()
        self.tabs.setTabText(self.tabs.indexOf(view), title or "Nova Aba")

    @pyqtSlot(bool)
    def on_tab_load_finished(self, ok):
        """
        Executa a injeção JS após o carregamento da página HTML do editor.
        """
        view = self.tabs.currentWidget()
        if not ok or not isinstance(view, BrowserTab):
            return

        current_url_str = view.url().toString()

        # Verifica se o carregamento foi da URL de destino do editor
        if current_url_str == PDF_EDITOR_URL.toString() and current_url_str in self.ocr_downloads_pending:
            full_path = self.ocr_downloads_pending.pop(current_url_str)

            # Monta a string JS (usando barras para ser seguro no JavaScript)
            js_safe_path = full_path.replace(os.path.sep, os.altsep if os.altsep else '/')

            # 🚨 O JS injetado chama handleOcrCompleted, que deve ter a lógica de redirecionamento para /processar_ocr
            js_code = f"""
            if (typeof handleOcrCompleted === 'function') {{ 
                handleOcrCompleted('{js_safe_path}'); 
            }} else {{ 
                console.error('handleOcrCompleted JS function not found!');
                alert('JS Error: handleOcrCompleted not found. PDF path: {js_safe_path}'); 
            }}
            """

            # Usa um pequeno delay para garantir que todos os recursos JS/CSS do editor carregaram
            QTimer.singleShot(200, lambda: view.page().runJavaScript(js_code, self._js_callback))

            QMessageBox.information(self, "Processamento JS",
                                    f"O arquivo '{os.path.basename(full_path)}' foi baixado. JS injetado.")

    def _js_callback(self, result):
        if result is not None:
            print(f"JS Execution Result: {result}")

    def on_download_state_changed(self, download: QWebEngineDownloadRequest, state):
        """
        Salva o PDF temporariamente, REDIRECIONA a aba, e INJETA o JS após um pequeno delay.
        """
        DownloadState = QWebEngineDownloadRequest.DownloadState

        state_map = {
            DownloadState.DownloadCompleted: "Concluído",
            DownloadState.DownloadInterrupted: "INTERROMPIDO/FALHA"
        }
        state_name = state_map.get(state, "Em progresso")
        filename = os.path.basename(download.downloadFileName())

        print(f"[{time.strftime('%H:%M:%S')}] Estado do Download '{filename}': {state_name}")

        if state == DownloadState.DownloadCompleted:
            if "ocr_outputs" in download.url().toString():

                full_path = os.path.join(download.downloadDirectory(), filename)
                current_view = self.tabs.currentWidget()

                if current_view and isinstance(current_view, BrowserTab):
                    print(
                        f"PDF OCR '{filename}' salvo. Forçando redirecionamento para o editor: {PDF_EDITOR_URL.toString()}")

                    # 1. FORÇA O REDIRECIONAMENTO DA ABA PARA A PÁGINA HTML DO EDITOR.
                    current_view.setUrl(PDF_EDITOR_URL)

                    # 2. Prepara a injeção JS para ser executada APÓS o redirecionamento
                    js_safe_path = full_path.replace(os.path.sep, os.altsep if os.altsep else '/')

                    # A injeção JS deve ser executada após o carregamento da página do editor
                    # Como não usamos loadFinished, usamos QTimer para um pequeno atraso

                    # 🚨 Prepara o código JS
                    js_code = f"""
                    try {{
                        if (typeof handleOcrCompleted === 'function') {{ 
                            handleOcrCompleted('{js_safe_path}'); 
                        }} else {{ 
                            console.error('handleOcrCompleted JS function not found! Verifique se o script carregou.');
                        }}
                    }} catch (e) {{
                        console.error('Erro na execução do JS:', e.message);
                    }}
                    """

                    # 🚨 EXECUTA A INJEÇÃO COM DELAY DE 500ms (MEIO SEGUNDO)
                    # Isso dá tempo para a nova URL começar a carregar
                    QTimer.singleShot(500, lambda: current_view.page().runJavaScript(js_code, self._js_callback))

                    QMessageBox.information(self, "Processamento JS",
                                            f"O arquivo '{os.path.basename(full_path)}' foi baixado. JS injetado com atraso.")

            try:
                download.stateChanged.disconnect()
            except TypeError:
                pass

        if state == DownloadState.DownloadInterrupted:
            # ... (Lógica de interrupção permanece) ...
            try:
                download.stateChanged.disconnect()
            except TypeError:
                pass

    def download_requested(self, download: QWebEngineDownloadRequest):
        download_url_str = download.url().toString()
        print("-" * 50)
        print(f"SINAL DE DOWNLOAD INTERCEPTADO. URL: {download_url_str}")

        if download_url_str.startswith("file:///"):
            download.cancel()
            return

        DownloadState = QWebEngineDownloadRequest.DownloadState
        if download.state() != DownloadState.DownloadRequested:
            return

        is_ocr_output = "ocr_outputs" in download_url_str
        suggested_filename = download.downloadFileName() or f"arquivo_baixado_{int(time.time())}.pdf"

        download.stateChanged.connect(lambda state: self.on_download_state_changed(download, state))

        if is_ocr_output:
            default_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.TempLocation)
            download.setDownloadDirectory(default_dir)
            download.setDownloadFileName(suggested_filename)
            download.accept()
            print(f"Download OCR temporário aceito e iniciado para processamento JS.")

        else:
            default_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
            default_path = os.path.join(default_dir, suggested_filename)

            save_path, _ = QFileDialog.getSaveFileName(
                self, "Salvar Arquivo", default_path, "Todos os Arquivos (*)"
            )

            if save_path:
                download.setDownloadDirectory(os.path.dirname(save_path))
                download.setDownloadFileName(os.path.basename(save_path))
                download.accept()
                QMessageBox.information(self, "Download Iniciado",
                                        f"O download de '{os.path.basename(save_path)}' foi iniciado.")
            else:
                download.cancel()
                print("Download cancelado pelo usuário.")

        print("-" * 50)


# =======================================================
# 📌 INICIALIZAÇÃO DA APLICAÇÃO
# =======================================================
if __name__ == "__main__":
    try:
        app = QApplication(sys.argv)
        window = WebBrowserWindow()
        sys.exit(app.exec())
    except Exception as e:
        print(f"ERRO DE EXECUÇÃO CRÍTICO: {e}")
        print("Verifique se as bibliotecas PyQt6 e PyQt6-WebEngine estão instaladas e atualizadas.")