import sys
import os
import re
import threading
import datetime
import io

# Módulos PyQt6
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QLabel, QGroupBox, QProgressBar,
    QFileDialog, QMessageBox, QSizePolicy
)
from PyQt6.QtGui import QPixmap, QImage, QPainter, QColor, QFont, QPen
from PyQt6.QtCore import Qt, QTimer, QCoreApplication, QRectF, QPointF, QEvent  # QEvent importado

# Módulos PyMuPDF e Pillow (para manipulação de PDF e imagens)
import fitz  # PyMuPDF
import traceback
import io
from PIL import Image

# Módulos para PKCS#11 e criptografia
import PyKCS11
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import UnsupportedAlgorithm, InvalidSignature, AlreadyFinalized

# Módulos pypdf para manipulação de PDF
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject, ArrayObject, IndirectObject, NumberObject, \
    TextStringObject


SIGNATURE_BACKGROUND_IMAGE = "crc.png"  # Coloque a imagem na mesma pasta do .exe
# --- Configuração do caminho da DLL/SO PKCS#11 ---
PKCS11_LIB_PATH = 'C:\\Windows\\System32\\aetpkss1.dll'  # <--- AJUSTE AQUI SE A DLL FOR DIFERENTE!

from datetime import datetime, timedelta
# --- Funções de Lógica PKCS#11 e Extração de Certificado ---

def get_pkcs11_session(pkcs11_lib_path, pin_str):
    """Inicializa a sessão PKCS#11 e faz login."""
    pkcs11_lib = PyKCS11.PyKCS11Lib()
    print(f"\n--- Iniciando sessão PKCS#11 ---")
    print(f"Tentando carregar a biblioteca PKCS#11 em: {pkcs11_lib_path}")
    pkcs11_lib.load(pkcs11_lib_path)
    print("Biblioteca PKCS#11 carregada com sucesso.")

    print("Buscando slots com tokens presentes...")
    slots = pkcs11_lib.getSlotList(tokenPresent=True)
    if not slots:
        raise RuntimeError("Nenhum token USB encontrado.")

    print(f"{len(slots)} slot(s) com token(s) encontrado(s). Usando o primeiro slot: {slots[0]}")

    session = pkcs11_lib.openSession(slots[0])
    print("Sessão PKCS#11 aberta com sucesso.")
    print(f"Realizando login com o PIN '********'...")
    session.login(pin_str)
    print("Login PKCS#11 realizado com sucesso.")
    return session, pkcs11_lib


def get_certificate_and_private_key_obj(session):
    """
    Encontra o certificado de assinatura pessoal e a chave privada correspondente.
    Retorna o certificado X.509 e o objeto da chave privada do token.
    """
    print("\n--- Buscando Certificados no Token ---")
    certs = session.findObjects([(PyKCS11.CKA_CLASS, PyKCS11.CKO_CERTIFICATE)])

    if not certs:
        raise RuntimeError("Nenhum certificado encontrado no token.")

    cert_x509_obj = None
    private_key_obj = None

    print(f"Encontrados {len(certs)} certificado(s). Iterando para encontrar o certificado de assinatura...")
    for i, c_obj in enumerate(certs):
        print(f"\nVerificando certificado {i + 1}...")
        cert_der_as_tuple = session.getAttributeValue(c_obj, [PyKCS11.CKA_VALUE])[0]
        if isinstance(cert_der_as_tuple, tuple):
            cert_der_bytes = bytes(cert_der_as_tuple)
        else:
            cert_der_bytes = cert_der_as_tuple

        current_cert_x509 = x509.load_der_x509_certificate(cert_der_bytes, default_backend())

        try:
            basic_constraints = current_cert_x509.extensions.get_extension_for_class(x509.BasicConstraints)
            if basic_constraints.value.ca:
                print("  - É um certificado CA. Ignorando.")
                continue
        except x509.ExtensionNotFound:
            pass

        try:
            key_usage = current_cert_x509.extensions.get_extension_for_class(x509.KeyUsage)
            if key_usage.value.digital_signature:
                cert_id_attrs = session.getAttributeValue(c_obj, [PyKCS11.CKA_ID])
                cert_id = cert_id_attrs[0] if cert_id_attrs else None

                if cert_id:
                    private_keys = session.findObjects([
                        (PyKCS11.CKA_CLASS, PyKCS11.CKO_PRIVATE_KEY),
                        (PyKCS11.CKA_ID, cert_id)
                    ])
                    if private_keys:
                        private_key_obj = private_keys[0]
                        cert_x509_obj = current_cert_x509
                        print("\n--- CERTIFICADO DE ASSINATURA ENCONTRADO ---")
                        return cert_x509_obj, private_key_obj
                    else:
                        print("  - Chave privada correspondente não encontrada para este certificado.")
                else:
                    print("  - ID do certificado não encontrado para tentar parear com chave privada.")
            else:
                print("  - Este certificado não possui uso de chave para assinatura digital.")
        except x509.ExtensionNotFound:
            print("  - Extensão 'KeyUsage' não encontrada. Pode não ser um certificado de assinatura.")
        except Exception as e:
            print(f"  - Erro ao processar o certificado: {e}")
            import traceback
            traceback.print_exc()

    raise RuntimeError(
        "Nenhum certificado de assinatura pessoal com chave privada correspondente foi encontrado no token.")


def get_document_id_from_cert(cert_x509_obj):
    """Extrai CPF/CNPJ do certificado."""
    subject_cn_attr = cert_x509_obj.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
    subject_cn = None
    if subject_cn_attr:
        subject_cn = subject_cn_attr[0].value

    extracted_doc_id = None
    if subject_cn:
        match = re.search(r':(\d{11})$', subject_cn)
        if match:
            extracted_doc_id = match.group(1)
        else:
            match = re.search(r':(\d{14})$', subject_cn)
            if match:
                extracted_doc_id = match.group(1)

    return extracted_doc_id

def clean_cert_name(cert_name):
    """Remove CPF/CNPJ do nome que vem no COMMON_NAME do certificado ICP-Brasil."""
    if cert_name and ':' in cert_name:
        return cert_name.split(':')[0].strip()
    return cert_name

def apply_drawn_signature_to_pdf(input_pdf_path, output_pdf_path,
                                 cert_name, cert_doc_id, drawn_coords,
                                 page_number, signature_reason="Assinado Digitalmente"):
    import fitz
    import datetime
    from PIL import Image, ImageDraw, ImageFont
    import io

    x, y, width, height = drawn_coords
    doc = fitz.open(input_pdf_path)
    page = doc[page_number]

    page_height = page.rect.height
    adjusted_y = page_height - (y + height)

    assinatura_texto = (
        f"{signature_reason}\n"
        f"{cert_name}\n"
        f"Data: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
    )

    scale_factor = 4
    img_w = int(width * scale_factor)
    img_h = int(height * scale_factor)

    img = Image.new("RGBA", (img_w, img_h), (255, 255, 255, 0))

    # Imagem de fundo
    bg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), SIGNATURE_BACKGROUND_IMAGE)
    if os.path.exists(bg_path):
        try:
            bg = Image.open(bg_path).convert("RGBA")
            bg = bg.resize((img_w, img_h), Image.LANCZOS)
            r, g, b, a = bg.split()
            a = a.point(lambda p: min(p, 150))  # era 100
            bg.putalpha(a)
            img.paste(bg, (0, 0), bg)
        except Exception as e:
            print(f"[AVISO] Imagem de fundo não carregada no PDF: {e}")

    draw = ImageDraw.Draw(img)

    font_size = int(img_h / 5)
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except:
        font = ImageFont.load_default()

    while font_size > 5:
        bbox = draw.multiline_textbbox((0, 0), assinatura_texto, font=font, spacing=4)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        if text_w < (img_w * 0.9) and text_h < (img_h * 0.9):
            break
        font_size -= 1
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except:
            font = ImageFont.load_default()
            break

    text_x = (img_w - text_w) / 2
    text_y = (img_h - text_h) / 2

    draw.multiline_text((text_x, text_y), assinatura_texto, fill="black", font=font, align="center", spacing=4)

    img_bytes = io.BytesIO()
    img.save(img_bytes, format="PNG")
    img_bytes.seek(0)

    rect = fitz.Rect(x, adjusted_y, x + width, adjusted_y + height)
    page.insert_image(rect, stream=img_bytes.read(), keep_proportion=False, overlay=True)

    doc.save(output_pdf_path)
    doc.close()


def sign_pdf_logic(pkcs11_lib, pkcs11_session, cert_x509_obj, private_key_obj,
                   input_pdf_path, output_pdf_path,
                   signature_reason, signature_location, signature_contact_info,
                   page_num, x, y, width, height,
                   progress_callback=None, completion_callback=None, error_callback=None):
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import (
        DictionaryObject, NameObject, DecodedStreamObject,
        ArrayObject, NumberObject, TextStringObject
    )
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.backends import default_backend
    from asn1crypto import x509 as asn1_x509
    from asn1crypto import algos, cms, core
    import datetime
    import io

    try:
        if progress_callback: progress_callback("Lendo documento...", 10)

        reader = PdfReader(input_pdf_path)
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)

        # Configuração do Campo de Assinatura (AcroForm)
        signature_field_name = NameObject(f"/Signature_{datetime.datetime.now().strftime('%H%M%S')}")
        signature_dictionary = DictionaryObject()

        signature_field = DictionaryObject({
            NameObject("/FT"): NameObject("/Sig"),
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/Rect"): ArrayObject([
                NumberObject(x),
                NumberObject(y),
                NumberObject(x + width),
                NumberObject(y + height)
            ]),
            NameObject("/F"): NumberObject(4),
            NameObject("/P"): writer.pages[page_num].indirect_reference,
            NameObject("/T"): signature_field_name,
            NameObject("/V"): signature_dictionary,
        })

        if "/AcroForm" not in writer._root_object:
            writer._root_object[NameObject("/AcroForm")] = DictionaryObject()
        if NameObject("/Fields") not in writer._root_object[NameObject("/AcroForm")]:
            writer._root_object[NameObject("/AcroForm")][NameObject("/Fields")] = ArrayObject()
        writer._root_object[NameObject("/AcroForm")][NameObject("/Fields")].append(signature_field)

        # Dados do Signatário
        from cryptography.x509.oid import NameOID
        signer_name = cert_x509_obj.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
        signer_name_clean = signer_name.split(':')[0]  # Remove CPF/CNPJ do texto visual se preferir
        current_time = datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')

        # --- APARÊNCIA VISUAL (VETORIAL) ---
        # Criamos um fluxo de aparência nativo (sem imagens)
        ap_stream = DecodedStreamObject()

        # Operadores de PDF: q=save state, BT=Begin Text, Tf=Font, Td=Move, Tj=Show Text, ET=End, Q=restore
        # Ajustamos as coordenadas (2, height-15) para o texto caber no retângulo desenhado
        ap_content = (
            f"q 0 0 {width} {height} re W n "
            f"BT /Helv 10 Tf 2 {height - 12} Td (Assinado digitalmente por:) Tj "
            f"0 -12 Td ({signer_name_clean}) Tj "
            f"0 -12 Td (Data: {current_time}) Tj ET Q"
        ).encode('latin-1')

        ap_stream.set_data(ap_content)
        ap_stream.update({
            NameObject("/Subtype"): NameObject("/Form"),
            NameObject("/BBox"): ArrayObject(
                [NumberObject(0), NumberObject(0), NumberObject(width), NumberObject(height)]),
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Resources"): DictionaryObject({
                NameObject("/Font"): DictionaryObject({
                    NameObject("/Helv"): DictionaryObject({
                        NameObject("/Type"): NameObject("/Font"),
                        NameObject("/Subtype"): NameObject("/Type1"),
                        NameObject("/BaseFont"): NameObject("/Helvetica")
                    })
                })
            })
        })
        signature_field[NameObject("/AP")] = DictionaryObject({NameObject("/N"): writer._add_object(ap_stream)})

        # Metadados da Assinatura
        pdf_m_value = f"D:{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}-03'00'"
        signature_dictionary.update({
            NameObject("/Type"): NameObject("/Sig"),
            NameObject("/Filter"): NameObject("/Adobe.PPKLite"),
            NameObject("/SubFilter"): NameObject("/adbe.pkcs7.detached"),
            NameObject("/Reason"): TextStringObject(signature_reason),
            NameObject("/M"): TextStringObject(pdf_m_value),
            NameObject("/ByteRange"): ArrayObject([NumberObject(0)] * 4),
            NameObject("/Name"): TextStringObject(signer_name),
        })

        # Preparação do Hash e Placeholder
        dummy_len = 8192
        dummy_bytes = b"\x00" * dummy_len
        placeholder_stream = DecodedStreamObject()
        placeholder_stream.set_data(dummy_bytes)
        signature_dictionary[NameObject("/Contents")] = writer._add_object(placeholder_stream)

        buffer = io.BytesIO()
        writer.write(buffer)
        pdf_bytes = buffer.getvalue()

        contents_start = pdf_bytes.find(dummy_bytes)
        contents_end = contents_start + dummy_len
        byte_range = [0, contents_start, contents_end, len(pdf_bytes) - contents_end]
        signature_dictionary[NameObject("/ByteRange")] = ArrayObject([NumberObject(b) for b in byte_range])

        # Hashing
        hasher = hashes.Hash(hashes.SHA256(), backend=default_backend())
        hasher.update(pdf_bytes[:contents_start] + pdf_bytes[contents_end:])
        digest = hasher.finalize()

        # Assinatura PKCS7 (Digital)
        cert_der = cert_x509_obj.public_bytes(serialization.Encoding.DER)
        asn1_cert = asn1_x509.Certificate.load(cert_der)

        signed_attrs = cms.CMSAttributes([
            cms.CMSAttribute({'type': 'content_type', 'values': ['data']}),
            cms.CMSAttribute({'type': 'message_digest', 'values': [core.OctetString(digest)]}),
            cms.CMSAttribute({'type': 'signing_time',
                              'values': [core.GeneralizedTime(datetime.datetime.now(datetime.timezone.utc))]}),
        ])

        mech = PyKCS11.Mechanism(PyKCS11.CKM_SHA256_RSA_PKCS, None)
        raw_signature = bytes(pkcs11_session.sign(private_key_obj, signed_attrs.dump(), mech))

        signer_info = cms.SignerInfo({
            'version': 1,
            'sid': cms.SignerIdentifier(
                {'issuer_and_serial_number': {'issuer': asn1_cert.issuer, 'serial_number': asn1_cert.serial_number}}),
            'digest_algorithm': {'algorithm': 'sha256'},
            'signed_attrs': signed_attrs,
            'signature_algorithm': {'algorithm': 'rsassa_pkcs1v15'},
            'signature': core.OctetString(raw_signature),
        })

        signed_data = cms.SignedData({
            'version': 1,
            'digest_algorithms': [{'algorithm': 'sha256'}],
            'encap_content_info': {'content_type': 'data'},
            'certificates': [asn1_cert],
            'signer_infos': [signer_info],
        })

        pkcs7 = cms.ContentInfo({'content_type': 'signed_data', 'content': signed_data}).dump()
        padded_pkcs7 = pkcs7 + b"\x00" * (dummy_len - len(pkcs7))

        # Gravação Final
        final_pdf_content = pdf_bytes[:contents_start] + padded_pkcs7 + pdf_bytes[contents_end:]
        with open(output_pdf_path, "wb") as f:
            f.write(final_pdf_content)

        if completion_callback: completion_callback(output_pdf_path)

    except Exception as e:
        if error_callback: error_callback(str(e))




class AssinadorPDFApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Assinador de PDF com Visualização Interativa")
        screen = self.screen().availableGeometry()
        self.setFixedSize(screen.width(), screen.height())

        self.pdf_document = None
        self.current_page_number = 0
        self.total_pages = 0
        self.zoom_factor = 1.0
        self.original_pixmap = QPixmap()
        self.rectangles_by_page = {}  # Armazena as coordenadas de cada página

        self.start_pos_canvas = None
        self.current_rect_id = None
        self.drawn_rect_coords_pdf = None

        self.pkcs11_session = None
        self.cert_x509_obj = None
        self.private_key_obj = None

        self.cert_name = "N/A"
        self.cert_doc_id = "N/A"
        self.cert_issue_date = "N/A"
        self.cert_expiration_date = "N/A"

        self.input_pdf_path = ""
        self.output_pdf_path = ""
        self.token_pin = ""

        self.signature_reason = "Assinatura Digitalmente"
        self.signature_location = "Brasil"
        self.signature_contact_info = "Não Informado"
        self.showMaximized()

        self.init_ui()

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)

        top_controls_layout = QHBoxLayout()

        self.open_pdf_button = QPushButton("Abrir PDF")
        self.open_pdf_button.clicked.connect(self.load_pdf)
        top_controls_layout.addWidget(self.open_pdf_button)

        self.page_info_label = QLabel("Página: N/A de N/A")
        top_controls_layout.addWidget(self.page_info_label)

        self.prev_button = QPushButton("Página Anterior")
        self.prev_button.clicked.connect(self.show_previous_page)
        self.prev_button.setEnabled(False)
        top_controls_layout.addWidget(self.prev_button)

        self.next_button = QPushButton("Próxima Página")
        self.next_button.clicked.connect(self.show_next_page)
        self.next_button.setEnabled(False)
        top_controls_layout.addWidget(self.next_button)

        pin_layout = QHBoxLayout()
        pin_layout.addWidget(QLabel("PIN do Token:"))
        self.pin_entry = QLineEdit()
        self.pin_entry.setEchoMode(QLineEdit.EchoMode.Password)
        self.pin_entry.setFixedWidth(120)
        self.pin_entry.textChanged.connect(self.update_pin_value)
        pin_layout.addWidget(self.pin_entry)
        top_controls_layout.addLayout(pin_layout)

        self.sign_button = QPushButton("Assinar PDF")
        self.sign_button.clicked.connect(self.start_sign_process)
        self.sign_button.setEnabled(False)
        top_controls_layout.addWidget(self.sign_button)

        main_layout.addLayout(top_controls_layout)

        cert_info_group_box = QGroupBox("Informações do Certificado Carregado")
        cert_info_layout = QVBoxLayout(cert_info_group_box)

        self.cert_name_label = QLabel("Nome do Titular: N/A")
        self.cert_name_label.setStyleSheet("color: blue;")
        cert_info_layout.addWidget(self.cert_name_label)

        self.cert_doc_id_label = QLabel("CPF/CNPJ: N/A")
        self.cert_doc_id_label.setStyleSheet("color: blue;")
        cert_info_layout.addWidget(self.cert_doc_id_label)

        self.cert_issue_date_label = QLabel("Válido de: N/A")
        self.cert_issue_date_label.setStyleSheet("color: blue;")
        cert_info_layout.addWidget(self.cert_issue_date_label)

        self.cert_expiration_date_label = QLabel("Válido até: N/A")
        self.cert_expiration_date_label.setStyleSheet("color: blue;")
        cert_info_layout.addWidget(self.cert_expiration_date_label)


        main_layout.addWidget(cert_info_group_box)

        self.pdf_display_label = QLabel("Por favor, abra um arquivo PDF.")
        self.pdf_display_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pdf_display_label.setStyleSheet("background-color: gray; border: 1px solid #ccc; border-radius: 5px;")
        self.pdf_display_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.pdf_display_label.setMouseTracking(True)
        self.pdf_display_label.mousePressEvent = self.on_canvas_button_press
        self.pdf_display_label.mouseMoveEvent = self.on_canvas_mouse_drag
        self.pdf_display_label.mouseReleaseEvent = self.on_canvas_button_release

        main_layout.addWidget(self.pdf_display_label)

        bottom_controls_group_box = QGroupBox("Área da Assinatura Selecionada")
        bottom_controls_layout = QHBoxLayout(bottom_controls_group_box)

        coords_layout = QVBoxLayout()
        self.coords_label = QLabel("Coordenadas (X, Y, Largura, Altura): N/A")
        self.coords_label.setStyleSheet("color: red;")
        coords_layout.addWidget(self.coords_label)

        self.page_label = QLabel("Página da Assinatura: N/A")
        self.page_label.setStyleSheet("color: red;")
        coords_layout.addWidget(self.page_label)
        bottom_controls_layout.addLayout(coords_layout)

        self.save_signed_pdf_button = QPushButton("Salvar PDF Assinado")
        self.save_signed_pdf_button.clicked.connect(self.save_signed_pdf)
        self.save_signed_pdf_button.setEnabled(False)
        bottom_controls_layout.addWidget(self.save_signed_pdf_button)

        main_layout.addWidget(bottom_controls_group_box)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("Aguardando abertura de PDF...")
        main_layout.addWidget(self.status_label)

        self.update_cert_info_display()

    # --- Utility methods for GUI updates from threads ---
    def update_status(self, message):
        print(f"[DEBUG - NOVO] update_status: {message}")
        QCoreApplication.instance().postEvent(self, StatusUpdateEvent(message))

    def update_progress_value(self, value):
        print(f"[DEBUG - NOVO] update_progress_value: {value}%")
        QCoreApplication.instance().postEvent(self, ProgressUpdateEvent(value))

    def event(self, event):
        if event.type() == StatusUpdateEvent.event_type:
            print(f"[DEBUG - NOVO] event handler: Processando StatusUpdateEvent: {event.message}")
            self.status_label.setText(event.message)
            return True
        elif event.type() == ProgressUpdateEvent.event_type:
            print(f"[DEBUG - NOVO] event handler: Processando ProgressUpdateEvent: {event.value}%")
            self.progress_bar.setValue(event.value)
            return True
        elif event.type() == SignCompletionEvent.event_type:
            print(f"[DEBUG] event handler: Processando SignCompletionEvent: {event.path}")
            self.on_sign_completion(event.path)
            return True
        return super().event(event)

    # --- General GUI and PDF display methods ---

    def update_pin_value(self, text):
        self.token_pin = text

    def update_cert_info_display(self):
        print("[DEBUG - NOVO] update_cert_info_display: Atualizando labels do certificado.")
        self.cert_name_label.setText(f"Nome do Titular: {self.cert_name}")
        self.cert_doc_id_label.setText(f"CPF/CNPJ: {self.cert_doc_id}")
        self.cert_issue_date_label.setText(f"Válido de: {self.cert_issue_date}")
        self.cert_expiration_date_label.setText(f"Válido até: {self.cert_expiration_date}")


    def load_pdf(self):
        print("[DEBUG - NOVO] load_pdf: Iniciado.")
        file_dialog = QFileDialog(self)
        file_dialog.setWindowTitle("Selecionar PDF")
        file_dialog.setNameFilter("PDF files (*.pdf);;All files (*.*)")
        if file_dialog.exec():
            file_path = file_dialog.selectedFiles()[0]
            try:
                print(f"[DEBUG - NOVO] load_pdf: Abrindo PDF: {file_path}")
                self.pdf_document = fitz.open(file_path)
                self.total_pages = self.pdf_document.page_count
                self.current_page_number = 0
                self.input_pdf_path = file_path

                dir_name, file_name = os.path.split(file_path)
                name, ext = os.path.splitext(file_name)
                self.output_pdf_path = os.path.join(dir_name, f"{name}_assinado{ext}")

                self.display_page()
                self.update_status(f"PDF '{os.path.basename(file_path)}' carregado.")
                self.prev_button.setEnabled(True)
                self.next_button.setEnabled(True)
                self.sign_button.setEnabled(True)
                print("[DEBUG - NOVO] load_pdf: PDF carregado com sucesso.")

            except Exception as e:
                import traceback
                print(f"[DEBUG - NOVO] ERRO em load_pdf: {e}\n{traceback.format_exc()}")
                QMessageBox.critical(self, "Erro ao Carregar PDF", f"Não foi possível carregar o PDF: {e}")
                self.pdf_document = None
                self.total_pages = 0
                self.current_page_number = 0
                self.page_info_label.setText("Página: N/A de N/A")
                self.prev_button.setEnabled(False)
                self.next_button.setEnabled(False)
                self.sign_button.setEnabled(False)
                self.update_status("Erro ao carregar PDF.")

    def display_page(self):
        print(f"[DEBUG - NOVO] display_page: Exibindo página {self.current_page_number + 1} de {self.total_pages}.")

        if not self.pdf_document:
            print("[DEBUG - NOVO] display_page: Nenhum documento PDF para exibir.")
            self.original_pixmap = QPixmap()
            self.pdf_display_label.clear()
            return

        if self.current_page_number < 0:
            self.current_page_number = 0
        elif self.current_page_number >= self.total_pages:
            self.current_page_number = self.total_pages - 1

        try:
            page = self.pdf_document.load_page(self.current_page_number)

            label_width = self.pdf_display_label.width()
            label_height = self.pdf_display_label.height()

            if page.rect.width > 0 and page.rect.height > 0 and label_width > 0 and label_height > 0:
                scale_x = label_width / page.rect.width
                scale_y = label_height / page.rect.height
                self.zoom_factor = max(min(scale_x, scale_y), 0.1)
                print(f"[DEBUG - NOVO] display_page: Zoom factor calculado: {self.zoom_factor}")
            else:
                self.zoom_factor = 1.0
                print("[DEBUG - NOVO] display_page: Dimensões inválidas, usando zoom padrão de 1.0.")

            matrix = fitz.Matrix(self.zoom_factor, self.zoom_factor)
            dl = page.get_displaylist()
            pix = dl.get_pixmap(matrix=matrix)

            img_format = QImage.Format.Format_RGBA8888 if pix.alpha else QImage.Format.Format_RGB888
            qimage = QImage(pix.samples_ptr, pix.width, pix.height, pix.stride, img_format)

            self.original_pixmap = QPixmap.fromImage(qimage)
            if self.original_pixmap.isNull():
                print("WARNING: QPixmap.fromImage(qimage) resultou em um QPixmap nulo.")
                self.pdf_display_label.setText("Erro ao renderizar a página do PDF.")
                self.original_pixmap = QPixmap()
                return

            self.pdf_display_label.setPixmap(self.original_pixmap)

            self.page_info_label.setText(f"Página: {self.current_page_number + 1} de {self.total_pages}")
            self.page_label.setText(str(self.current_page_number))

            # 🟢 Só desenha o retângulo se houver e ainda não tiver sido assinado
            rect = self.rectangles_by_page.get(self.current_page_number)
            if rect:
                print(f"[DEBUG - NOVO] display_page: Retângulo salvo encontrado, redesenhando.")
                self.draw_rectangle_on_canvas(rect, QColor("red"))
                self.update_coords_display(rect)
            else:
                self.coords_label.setText("Coordenadas (X, Y, Largura, Altura): N/A")

            print("[DEBUG - NOVO] display_page: Página exibida com sucesso.")

        except Exception as e:
            import traceback
            print(f"[DEBUG - NOVO] ERRO em display_page: {e}\n{traceback.format_exc()}")
            QMessageBox.critical(self, "Erro de Renderização", f"Não foi possível exibir a página do PDF: {e}")
            self.pdf_display_label.setText("Erro ao renderizar a página do PDF.")

    def resizeEvent(self, event):
        print("[DEBUG - NOVO] resizeEvent: Janela redimensionada.")
        if self.pdf_document:
            self.display_page()
        super().resizeEvent(event)

    def show_next_page(self):
        print("[DEBUG - NOVO] show_next_page: Próxima página.")
        if self.pdf_document and self.current_page_number < self.total_pages - 1:
            self.current_page_number += 1
            self.drawn_rect_coords_pdf = None
            self.display_page()
            self.coords_label.setText("Coordenadas (X, Y, Largura, Altura): N/A")
            self.save_signed_pdf_button.setEnabled(False)


    def show_previous_page(self):
        print("[DEBUG - NOVO] show_previous_page: Página anterior.")
        if self.pdf_document and self.current_page_number > 0:
            self.current_page_number -= 1
            self.drawn_rect_coords_pdf = None
            self.display_page()
            self.coords_label.setText("Coordenadas (X, Y, Largura, Altura): N/A")
            self.save_signed_pdf_button.setEnabled(False)


    # --- Canvas drawing logic (using QPainter on QPixmap) ---

    def draw_rectangle_on_canvas(self, pdf_coords, color=QColor("blue")):
        try:
            if self.original_pixmap.isNull():
                return

            temp_pixmap = self.original_pixmap.copy()
            painter = QPainter(temp_pixmap)
            painter.setPen(QPen(color, 2))

            image_height = self.original_pixmap.height()

            pdf_x, pdf_y, pdf_w, pdf_h = pdf_coords

            img_x = pdf_x * self.zoom_factor
            img_y = image_height - (pdf_y + pdf_h) * self.zoom_factor
            img_w = pdf_w * self.zoom_factor
            img_h = pdf_h * self.zoom_factor

            # Desenha imagem de fundo no preview
            bg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), SIGNATURE_BACKGROUND_IMAGE)
            if os.path.exists(bg_path):
                try:
                    bg = Image.open(bg_path).convert("RGBA")
                    bg = bg.resize((int(img_w), int(img_h)), Image.LANCZOS)
                    r, g, b, a = bg.split()
                    a = a.point(lambda p: min(p, 100))
                    bg.putalpha(a)
                    bg_bytes = io.BytesIO()
                    bg.save(bg_bytes, format="PNG")
                    bg_qimage = QImage.fromData(bg_bytes.getvalue())
                    bg_pixmap = QPixmap.fromImage(bg_qimage)
                    painter.drawPixmap(int(img_x), int(img_y), bg_pixmap)
                except Exception as e:
                    print(f"[AVISO] Preview: imagem de fundo não carregada: {e}")

            painter.drawRect(int(img_x), int(img_y), int(img_w), int(img_h))

            if self.cert_name != "N/A":
                painter.setFont(QFont("Helvetica", 8))
                painter.setPen(QPen(QColor("green")))
                text = (
                    f"Assinado Digitalmente\n"
                    f"Nome: {self.cert_name}\n"
                    f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
                )
                text_rect = QRectF(img_x, img_y, img_w, img_h)
                painter.drawText(
                    text_rect,
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                    text
                )

            painter.end()
            self.pdf_display_label.setPixmap(temp_pixmap)

        except Exception as e:
            import traceback
            self.update_status(f"Erro ao desenhar retângulo: {e}")
            print(f"ERRO: draw_rectangle_on_canvas: {e}\n{traceback.format_exc()}")

    def on_canvas_button_press(self, event):
        print("[DEBUG - NOVO] on_canvas_button_press: Botão do mouse pressionado no canvas.")
        try:
            if not self.pdf_document:
                self.update_status("Por favor, abra um PDF para começar a desenhar a área de assinatura.")
                print("[DEBUG - NOVO] on_canvas_button_press: PDF não carregado.")
                return
            if not self.cert_x509_obj:
                self.update_status(
                    "Por favor, clique em 'Assinar PDF' para carregar o certificado antes de desenhar a área de assinatura.")
                print("[DEBUG - NOVO] on_canvas_button_press: Certificado não carregado.")
                return

            self.start_pos_canvas = event.pos()
            self.drawn_rect_coords_pdf = None
            self.display_page()
            self.save_signed_pdf_button.setEnabled(False)
            print(f"[DEBUG - NOVO] on_canvas_button_press: Posição inicial do desenho: {self.start_pos_canvas}.")
        except Exception as e:
            import traceback
            self.update_status(f"Erro ao iniciar desenho: {e}")
            print(f"ERRO: on_canvas_button_press: {e}\n{traceback.format_exc()}")

    def on_canvas_mouse_drag(self, event):
        # print("[DEBUG - NOVO] on_canvas_mouse_drag: Mouse arrastado no canvas.") # Pode ser muito verboso
        try:
            if not self.pdf_document or self.original_pixmap.isNull():
                return
            if not self.cert_x509_obj or not self.start_pos_canvas:
                return

            label_width = self.pdf_display_label.width()
            label_height = self.pdf_display_label.height()
            image_width = self.original_pixmap.width()
            image_height = self.original_pixmap.height()

            x_offset = (label_width - image_width) / 2
            y_offset = (label_height - image_height) / 2

            start_x = self.start_pos_canvas.x() - x_offset
            start_y = self.start_pos_canvas.y() - y_offset
            end_x = event.pos().x() - x_offset
            end_y = event.pos().y() - y_offset

            start = QPointF(start_x, start_y)
            end = QPointF(end_x, end_y)
            rect = QRectF(start, end).normalized()

            temp_pixmap = self.original_pixmap.copy()
            painter = QPainter(temp_pixmap)
            painter.setPen(QPen(QColor("blue"), 2))
            painter.drawRect(rect)
            painter.end()

            self.pdf_display_label.setPixmap(temp_pixmap)

        except Exception as e:
            import traceback
            self.update_status(f"Erro ao arrastar mouse: {e}")
            print(f"ERRO: on_canvas_mouse_drag: {e}\n{traceback.format_exc()}")

    def on_canvas_button_release(self, event):
        print("[DEBUG - NOVO] on_canvas_button_release: Botão do mouse liberado no canvas.")
        try:
            if not self.pdf_document or self.original_pixmap.isNull():
                self.update_status("PDF não carregado ou erro na renderização da página. Não é possível desenhar.")
                print("[DEBUG - NOVO] on_canvas_button_release: PDF não carregado ou pixmap nulo.")
                return
            if not self.cert_x509_obj or not self.start_pos_canvas:
                print("[DEBUG - NOVO] on_canvas_button_release: Certificado ou start_pos_canvas nulo.")
                return

            label_size = self.pdf_display_label.size()
            image_width = self.original_pixmap.width()
            image_height = self.original_pixmap.height()
            x_offset = (label_size.width() - image_width) / 2
            y_offset = (label_size.height() - image_height) / 2

            start_x = self.start_pos_canvas.x() - x_offset
            start_y = self.start_pos_canvas.y() - y_offset
            end_x = event.pos().x() - x_offset
            end_y = event.pos().y() - y_offset

            rect_on_img = QRectF(QPointF(start_x, start_y), QPointF(end_x, end_y)).normalized()

            if rect_on_img.width() < 1 or rect_on_img.height() < 1:
                self.update_status("Nenhum retângulo válido desenhado. Por favor, tente novamente.")
                print("[DEBUG - NOVO] on_canvas_button_release: Retângulo muito pequeno.")
                return

            # Conversão para coordenadas PDF
            pdf_x1 = rect_on_img.left() / self.zoom_factor
            pdf_x2 = rect_on_img.right() / self.zoom_factor
            pdf_y1 = (image_height - rect_on_img.bottom()) / self.zoom_factor
            pdf_y2 = (image_height - rect_on_img.top()) / self.zoom_factor

            x = round(pdf_x1)
            y = round(pdf_y1)
            width = round(pdf_x2 - pdf_x1)
            height = round(pdf_y2 - pdf_y1)

            # Armazena retângulo no dicionário por página
            rect_coords = (x, y, width, height)
            self.rectangles_by_page[self.current_page_number] = rect_coords
            print(f"[DEBUG - NOVO] on_canvas_button_release: Retângulo salvo: {rect_coords}")

            self.update_coords_display(rect_coords)
            self.update_status("Retângulo de assinatura desenhado. Pronto para salvar.")
            self.draw_rectangle_on_canvas(rect_coords, QColor("green"))
            self.save_signed_pdf_button.setEnabled(True)
            self.start_pos_canvas = None

        except Exception as e:
            import traceback
            self.update_status(f"Erro ao finalizar desenho: {e}")
            print(f"ERRO: on_canvas_button_release: {e}\n{traceback.format_exc()}")

    def update_coords_display(self, coords):
        print(f"[DEBUG - NOVO] update_coords_display: Coordenadas atualizadas para {coords}.")
        self.coords_label.setText(
            f"Coordenadas (X, Y, Largura, Altura): X: {coords[0]}, Y: {coords[1]}, Largura: {coords[2]}, Altura: {coords[3]}")

    # --- PKCS#11 and Signing Process ---

    def start_sign_process(self):
        print("[DEBUG - NOVO] start_sign_process: Iniciando processo de assinatura.")
        if not self.pdf_document:
            QMessageBox.warning(self, "PDF Não Carregado", "Por favor, selecione um PDF primeiro.")
            print("[DEBUG - NOVO] start_sign_process: PDF não carregado, abortando.")
            return

        self.sign_button.setEnabled(False)
        self.save_signed_pdf_button.setEnabled(False)
        self.pin_entry.setEnabled(False)
        self.update_status("Conectando ao token e carregando certificado...")
        self.progress_bar.setValue(0)

        self.token_pin = self.pin_entry.text()
        if not self.token_pin:
            QMessageBox.warning(self, "PIN Vazio", "Por favor, digite o PIN do seu token.")
            self.sign_button.setEnabled(True)
            self.pin_entry.setEnabled(True)
            self.update_status("Aguardando PIN...")
            print("[DEBUG - NOVO] start_sign_process: PIN vazio, abortando.")
            return

        threading.Thread(target=self._run_cert_loading_threaded, args=(PKCS11_LIB_PATH, self.token_pin)).start()
        print("[DEBUG - NOVO] start_sign_process: Thread de carregamento de certificado iniciada.")


    def _run_cert_loading_threaded(self, pkcs11_lib_path, pin):
        print(f"[DEBUG] _run_cert_loading_threaded: Iniciado para {pkcs11_lib_path}.")
        session = None
        try:
            self.update_progress_value(10)
            self.update_status("Conectando ao token...")
            session, pkcs11_lib = get_pkcs11_session(pkcs11_lib_path, pin)
            self.pkcs11_session = session
            self.pkcs11_lib = pkcs11_lib

            self.update_progress_value(40)
            self.update_status("Buscando certificado...")
            self.cert_x509_obj, self.private_key_obj = get_certificate_and_private_key_obj(session)

            subject_cn_attrs = self.cert_x509_obj.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
            self.cert_name = clean_cert_name(subject_cn_attrs[0].value if subject_cn_attrs else "N/A")
            self.cert_doc_id = get_document_id_from_cert(self.cert_x509_obj)
            self.cert_issue_date = self.cert_x509_obj.not_valid_before_utc.strftime('%d/%m/%Y %H:%M:%S')
            self.cert_expiration_date = self.cert_x509_obj.not_valid_after_utc.strftime('%d/%m/%Y %H:%M:%S')

            QTimer.singleShot(0, self.update_cert_info_display)
            self.update_progress_value(100)
            self.update_status("Certificado carregado! Desenhe a área da assinatura.")
            print("[DEBUG] _run_cert_loading_threaded: Certificado carregado com sucesso, agendando QMessageBox.")
            # Este QMessageBox funciona porque é o primeiro agendado após o carregamento
            QTimer.singleShot(0, lambda: QMessageBox.information(self, "Certificado Carregado",
                                                                 "Certificado digital carregado com sucesso!\nAgora, desenhe a área da assinatura no PDF."))

        except PyKCS11.PyKCS11Error as e:
            error_msg = f"ERRO PKCS#11: {e}\nCódigo de erro (hex): {hex(e.value)}\nVerifique PIN, token e DLL."
            print(f"[DEBUG] _run_cert_loading_threaded: {error_msg}")
            self.on_process_error(error_msg)
        except RuntimeError as e:
            error_msg = f"ERRO de Execução: {e}"
            print(f"[DEBUG] _run_cert_loading_threaded: {error_msg}")
            self.on_process_error(error_msg)
        except Exception as e:
            import traceback
            error_msg = f"ERRO INESPERADO: {e}\n{traceback.format_exc()}"
            print(f"[DEBUG] _run_cert_loading_threaded: {error_msg}")
            self.on_process_error(error_msg)
        finally:
            print("[DEBUG] _run_cert_loading_threaded: Finalizando thread, reativando botões na thread principal.")
            QTimer.singleShot(0, lambda: self.sign_button.setEnabled(True))
            QTimer.singleShot(0, lambda: self.pin_entry.setEnabled(True))

    def save_signed_pdf(self):
        print("[DEBUG - NOVO] save_signed_pdf: Iniciado.")
        if not self.pdf_document:
            QMessageBox.warning(self, "PDF Não Carregado", "Por favor, carregue um PDF primeiro.")
            print("[DEBUG - NOVO] save_signed_pdf: PDF não carregado, abortando.")
            return
        if not self.cert_x509_obj or not self.private_key_obj:
            QMessageBox.warning(self, "Certificado Não Carregado",
                                 "Por favor, carregue o certificado digital antes de assinar.")
            print("[DEBUG - NOVO] save_signed_pdf: Certificado não carregado, abortando.")
            return
        coords = self.rectangles_by_page.get(self.current_page_number)
        if not coords:
            QMessageBox.warning(self, "Área de Assinatura Não Definida",
                                "Por favor, desenhe a área onde a assinatura será inserida no PDF.")
            print("[DEBUG - NOVO] save_signed_pdf: Área de assinatura não definida nesta página, abortando.")
            return
        if not self.pkcs11_session:
            QMessageBox.warning(self, "Sessão PKCS#11 Inativa",
                                "A sessão com o token não está ativa. Tente carregar o certificado novamente.")
            print("[DEBUG - NOVO] save_signed_pdf: Sessão PKCS#11 inativa, abortando.")
            return

        self.sign_button.setEnabled(False)
        self.save_signed_pdf_button.setEnabled(False)
        self.pin_entry.setEnabled(False)
        self.update_status("Salvando PDF assinado...")
        self.progress_bar.setValue(0)

        x, y, width, height = coords
        page_num = self.current_page_number

        file_dialog = QFileDialog(self)
        file_dialog.setWindowTitle("Salvar PDF Assinado Como")
        file_dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        file_dialog.setDefaultSuffix("pdf")
        file_dialog.setNameFilter("PDF files (*.pdf);;All files (*.*)")
        file_dialog.setDirectory(os.path.dirname(self.output_pdf_path))
        file_dialog.selectFile(os.path.basename(self.output_pdf_path))

        if file_dialog.exec():
            output_file_path = file_dialog.selectedFiles()[0]
            print(
                f"[DEBUG - NOVO] save_signed_pdf: Iniciando thread de aplicação de assinatura visual para '{output_file_path}'.")
            threading.Thread(
                target=self._run_apply_visible_signature_threaded,
                args=(self.input_pdf_path, output_file_path,
                      self.cert_name, self.cert_doc_id,
                      coords,  # já é uma tupla (x, y, w, h)
                      self.current_page_number)
            ).start()
        else:
            self.on_process_error("Operação de salvar cancelada.")
            print("[DEBUG - NOVO] save_signed_pdf: Diálogo de salvar cancelado.")

    def _run_apply_visible_signature_threaded(self, input_pdf, output_pdf, cert_name, cert_doc_id, coords, page_num):
        print(f"[DEBUG] _run_apply_visible_signature_threaded iniciada para: {output_pdf}")
        try:
            self.update_status("Aplicando assinatura visual...")
            self.update_progress_value(25)

            temp_pdf = output_pdf.replace(".pdf", "_temp_visual.pdf")

            apply_drawn_signature_to_pdf(
                input_pdf, temp_pdf,
                cert_name, cert_doc_id,
                coords, page_num
            )
            print("[DEBUG] Assinatura visual aplicada.")

            self.update_status("Conectando ao token para assinatura digital...")
            self.update_progress_value(40)

            # Encerra sessão anterior se ainda estiver ativa
            if self.pkcs11_session:
                try:
                    self.pkcs11_session.logout()
                    self.pkcs11_session.closeSession()
                    self.pkcs11_session = None
                    print("[DEBUG] Sessão anterior encerrada.")
                except Exception as e:
                    print(f"[DEBUG] Aviso ao encerrar sessão anterior: {e}")

            # Abre nova sessão PKCS#11 nesta thread com o mesmo PIN já salvo
            sign_session, sign_lib = get_pkcs11_session(PKCS11_LIB_PATH, self.token_pin)
            cert_x509, private_key = get_certificate_and_private_key_obj(sign_session)

            x, y, w, h = coords
            sign_pdf_logic(
                pkcs11_lib=sign_lib,
                pkcs11_session=sign_session,
                cert_x509_obj=cert_x509,
                private_key_obj=private_key,
                input_pdf_path=temp_pdf,
                output_pdf_path=output_pdf,
                signature_reason=self.signature_reason,
                signature_location=self.signature_location,
                signature_contact_info=self.signature_contact_info,
                page_num=page_num,
                x=x, y=y, width=w, height=h,
                progress_callback=lambda msg, val: (self.update_status(msg), self.update_progress_value(val)),
                completion_callback=None,  # vamos chamar manualmente abaixo
                error_callback=self.on_process_error
            )

            print("[DEBUG] sign_pdf_logic concluída.")

            # Remove arquivo temporário
            if os.path.exists(temp_pdf):
                os.remove(temp_pdf)
                print("[DEBUG] Arquivo temporário removido.")

            # Encerra sessão de assinatura
            try:
                sign_session.logout()
                sign_session.closeSession()
                print("[DEBUG] Sessão de assinatura encerrada.")
            except Exception as e:
                print(f"[DEBUG] Erro ao encerrar sessão de assinatura: {e}")

            # Dispara conclusão de forma thread-safe
            print("[DEBUG] Disparando completion via evento...")
            QCoreApplication.instance().postEvent(self, SignCompletionEvent(output_pdf))

        except Exception as e:
            import traceback
            self.on_process_error(f"Erro ao aplicar assinatura: {e}\n{traceback.format_exc()}")
            print(f"[DEBUG] Erro em _run_apply_visible_signature_threaded: {e}")

    def _run_signing_threaded(self, session, cert_x509, private_key_obj,
                             input_pdf, output_pdf,
                             reason, location, contact, page_num, x, y, width, height):
        print(f"[DEBUG - NOVO] _run_signing_threaded: Iniciada para {output_pdf}.")
        try:
            sign_pdf_logic(session, cert_x509, private_key_obj,
                           input_pdf, output_pdf,
                           reason, location, contact,
                           page_num, x, y, width, height,
                           progress_callback=lambda msg, val: (
                           self.update_status(msg), self.update_progress_value(val)),
                           completion_callback=self.on_sign_completion,
                           error_callback=self.on_process_error)
            print("[DEBUG - NOVO] _run_signing_threaded: sign_pdf_logic chamada com sucesso.")

        except PyKCS11.PyKCS11Error as e:
            error_msg = f"ERRO PyKCS11 durante a assinatura: {e}\nCódigo de erro (hex): {hex(e.value)}\nVerifique o PIN, token e DLL."
            print(f"[DEBUG - NOVO] _run_signing_threaded: {error_msg}")
            self.on_process_error(error_msg)
        except (UnsupportedAlgorithm, InvalidSignature, AlreadyFinalized) as e:
            error_msg = f"ERRO de Criptografia durante a assinatura: {e}\nOcorreu um erro ao processar o certificado ou assinar os dados. Tente atualizar 'cryptography'."
            print(f"[DEBUG - NOVO] _run_signing_threaded: {error_msg}")
            self.on_process_error(error_msg)
        except FileNotFoundError as e:
            error_msg = f"ERRO de Arquivo durante a assinatura: {e}\nVerifique se o arquivo '{input_pdf}' existe e está no diretório correto."
            print(f"[DEBUG - NOVO] _run_signing_threaded: {error_msg}")
            self.on_process_error(error_msg)
        except RuntimeError as e:
            error_msg = f"ERRO de Execução durante a assinatura: {e}"
            print(f"[DEBUG - NOVO] _run_signing_threaded: {error_msg}")
            self.on_process_error(error_msg)
        except Exception as e:
            import traceback
            error_msg = f"ERRO INESPERADO durante a assinatura: {e}\n{traceback.format_exc()}"
            print(f"[DEBUG - NOVO] _run_signing_threaded: {error_msg}")
            self.on_process_error(error_msg)
        finally:
            if session:
                try:
                    session.logout()
                    session.closeSession()
                    print("\n[DEBUG - NOVO] Sessão PKCS#11 encerrada após processo de assinatura.")
                except Exception as e:
                    print(f"[DEBUG - NOVO] Erro ao encerrar a sessão PKCS#11 na thread de assinatura: {e}")
            print("[DEBUG - NOVO] _run_signing_threaded: Finalizando thread, reativando botões na thread principal.")
            QTimer.singleShot(0, lambda: self.sign_button.setEnabled(True))
            QTimer.singleShot(0, lambda: self.save_signed_pdf_button.setEnabled(True))
            QTimer.singleShot(0, lambda: self.pin_entry.setEnabled(True))

    def debug_and_show_completion(self, output_path):
        print(f"[DEBUG - EXTREMO] QTimer.singleShot DISPAROU e chamou debug_and_show_completion com: {output_path}")
        try:
            self.on_sign_completion(output_path)
            print("[DEBUG - NOVO] debug_and_show_completion: on_sign_completion executada sem erros conhecidos.")
        except Exception as e:
            import traceback
            print(f"[DEBUG - EXTREMO] ERRO INESPERADO DENTRO DE debug_and_show_completion: {e}\n{traceback.format_exc()}")
            QMessageBox.critical(self, "Erro Fatal de Exibição",
                                 f"Um erro ocorreu ao tentar exibir a mensagem de sucesso: {e}\nPor favor, verifique o console.")

    def on_sign_completion(self, output_path):
        print(f"[DEBUG] on_sign_completion chamado com: {output_path}")
        try:
            self.update_status(f"PDF assinado com sucesso! Salvo em: {output_path}")
            self.progress_bar.setValue(100)
            print("[DEBUG - NOVO] on_sign_completion: Status e progresso atualizados. Preparando QMessageBox.")

            # Tenta forçar a janela principal para frente
            QApplication.instance().processEvents()
            self.activateWindow()
            self.raise_()
            QApplication.instance().processEvents()
            print("[DEBUG - NOVO] on_sign_completion: Tentando ativar e levantar a janela principal.")

            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("PDF Assinado com Sucesso")
            msg_box.setText(f"O PDF foi assinado com sucesso e salvo em:\n\n{output_path}")
            msg_box.setIcon(QMessageBox.Icon.Information)
            msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg_box.setModal(True)
            print("[DEBUG - NOVO] on_sign_completion: QMessageBox criada. Chamando .exec().")

            msg_box.exec()  # Chamada bloqueante para exibir diálogo
            print("[DEBUG - NOVO] on_sign_completion: .exec() da QMessageBox retornou.")

            self.sign_button.setEnabled(True)
            self.save_signed_pdf_button.setEnabled(True)
            self.pin_entry.setEnabled(True)
            print("[DEBUG - NOVO] on_sign_completion: Botões reativados.")

            # ✅ Reabrir o PDF assinado e atualizar o canvas
            try:
                self.pdf_document = fitz.open(output_path)
                self.input_pdf_path = output_path
                self.output_pdf_path = output_path

                # Limpa retângulo da página atual (não precisa desenhar sobre assinatura)
                self.rectangles_by_page.pop(self.current_page_number, None)
                self.display_page()

                print("[DEBUG - NOVO] on_sign_completion: PDF assinado reaberto e exibido no canvas.")
            except Exception as e:
                print(f"[DEBUG - NOVO] Falha ao recarregar PDF assinado: {e}")

        except Exception as e:
            import traceback
            print(f"[DEBUG - EXTREMO] ERRO INESPERADO DENTRO DE on_sign_completion: {e}\n{traceback.format_exc()}")
            QMessageBox.critical(self, "Erro Interno",
                                 f"Um erro ocorreu ao finalizar o processo e exibir a mensagem de sucesso: {e}\nVerifique o console para mais detalhes.")

    def on_process_error(self, error_message):
        print(f"[DEBUG - NOVO] on_process_error: Erro recebido: {error_message}")
        self.update_status(f"Erro: {error_message}")
        self.progress_bar.setValue(0)
        try:
            QMessageBox.critical(self, "Erro de Processo", error_message)
            print("[DEBUG - NOVO] on_process_error: QMessageBox de erro exibida.")
        except Exception as e:
            print(f"[DEBUG - EXTREMO] ERRO ao exibir QMessageBox de erro: {e}\n{traceback.format_exc()}")
            print(f"ERRO CRÍTICO (QMessageBox falhou): {error_message}")

        self.sign_button.setEnabled(True)
        self.save_signed_pdf_button.setEnabled(True)
        self.pin_entry.setEnabled(True)

        self.pkcs11_session = None
        self.cert_x509_obj = None
        self.private_key_obj = None
        self.cert_name = "N/A"
        self.cert_doc_id = "N/A"
        self.cert_issue_date = "N/A"
        self.cert_expiration_date = "N/A"
        self.update_cert_info_display()

        self.drawn_rect_coords_pdf = None
        if self.pdf_document:
            self.display_page()
        else:
            self.pdf_display_label.clear()
        print("[DEBUG - NOVO] on_process_error: Estado da UI resetado.")


# Custom event classes for thread-safe GUI updates.
class StatusUpdateEvent(QEvent):
    event_type = QEvent.Type(QEvent.Type.User + 1)

    def __init__(self, message):
        super().__init__(StatusUpdateEvent.event_type)
        self.message = message


class ProgressUpdateEvent(QEvent):
    event_type = QEvent.Type(QEvent.Type.User + 2)

    def __init__(self, value):
        super().__init__(ProgressUpdateEvent.event_type)
        self.value = value


class SignCompletionEvent(QEvent):
    event_type = QEvent.Type(QEvent.Type.User + 3)

    def __init__(self, path):
        super().__init__(SignCompletionEvent.event_type)
        self.path = path

def flatten_page_visualmente(doc, page_number, zoom=2.0):
    """
    Rende a página como imagem com a assinatura e substitui o conteúdo por essa imagem.
    Ideal para garantir visualização em PDFs OCR.
    """
    import fitz
    import io
    from PIL import Image

    page = doc[page_number]
    mat = fitz.Matrix(zoom, zoom)  # aumento de resolução
    pix = page.get_pixmap(matrix=mat)

    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

    # Salva imagem temporária em memória
    img_bytes = io.BytesIO()
    img.save(img_bytes, format="PNG")
    img_bytes.seek(0)

    # Apaga o conteúdo da página e insere imagem rasterizada
    page.clean_contents()
    rect = fitz.Rect(0, 0, page.rect.width, page.rect.height)
    page.insert_image(rect, stream=img_bytes.read(), overlay=False)

    print("[DEBUG] Página achatada com sucesso.")



if __name__ == "__main__":
    print("[DEBUG - NOVO] Iniciando aplicação Qt.")
    app = QApplication(sys.argv)
    window = AssinadorPDFApp()
    window.show()
    print("[DEBUG - NOVO] Aplicação Qt em execução.")
    sys.exit(app.exec())
    print("[DEBUG - NOVO] Aplicação Qt encerrada.")