import os
import sys
import PyKCS11 # Utilizado para interações diretas com o token, se necessário
from datetime import datetime
import traceback

from pyhanko.sign.pkcs11 import open_pkcs11_session, PKCS11Signer
from pyhanko.sign.signers import PdfSigner, PdfSignatureMetadata
from pyhanko.sign.fields import SigFieldSpec
from pyhanko.stamp import TextStampStyle
from pyhanko.sign.general import SigningError


LIB_PATH = "C:\\Windows\\System32\\aetpkss1.dll"  # Caminho típico do SafeSign no Windows
SLOT_NO = 0  # Altere este valor caso o seu token esteja em outro slot

def assinar_pdf(input_pdf_path, output_pdf_path=None, pin=None, x=0, y=0, width=0, height=0):
    print("🔐 Iniciando assinatura do PDF...")
    print(f"📄 Arquivo de entrada: {input_pdf_path} → {output_pdf_path}")
    print(f"🧭 Coordenadas: x={x}, y={y}, width={width}, height={height}")
    print(f"🔑 PIN informado: {'*' * len(pin) if pin else 'Nenhum PIN fornecido'}") # Melhorar a exibição do PIN

    try:
        # Obter o nome do arquivo original a partir do caminho de entrada
        original_filename = os.path.basename(input_pdf_path)

        if output_pdf_path is None:
            # CRIA UM NOME DE ARQUIVO DE SAÍDA TEMPORÁRIO PARA O PDF ASSINADO
            name_without_ext = os.path.splitext(original_filename)[0]
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            signed_filename_temp = f"signed_temp_{name_without_ext}_{timestamp}.pdf"

            # NOVO DESTINO: PASTA 'signed'
            SIGNED_FOLDER = os.path.join(os.getcwd(), "signed")
            os.makedirs(SIGNED_FOLDER, exist_ok=True)
            output_pdf_path = os.path.join(SIGNED_FOLDER, signed_filename_temp) # Atribuir ao output_pdf_path

            print(f"DEBUG (app_assinador.py): PDF temporário de saída esperado em: {output_pdf_path}")

        print(f"📁 Arquivo de saída: {output_pdf_path}")
        dir_path = os.path.dirname(output_pdf_path)
        print(f"🔍 Diretório de saída: {dir_path}")
        print(f"🔧 Diretório existe? {os.path.isdir(dir_path)}")
        print(f"🛡️ Permissão de escrita? {os.access(dir_path, os.W_OK)}")

        if not os.path.isdir(dir_path):
            # Tentar criar o diretório se não existir
            os.makedirs(dir_path, exist_ok=True)
            print(f"Diretório de saída criado: {dir_path}")

        if not os.access(dir_path, os.W_OK):
            raise PermissionError(f"Sem permissão de escrita no diretório: {dir_path}")

        with open_pkcs11_session(lib_location=LIB_PATH, user_pin=pin, slot_no=SLOT_NO) as sess:
            signer = PKCS11Signer(session=sess)

            # A box é definida como (left, bottom, right, top)
            # Para definir a posição a partir do canto inferior esquerdo com x, y, width, height:
            # x_left = x
            # y_bottom = y
            # x_right = x + width
            # y_top = y + height
            box = (x, y, x + width, y + height) # Corrigida a ordem da box

            sig_field = SigFieldSpec(sig_field_name="Assinatura1", box=box)

            signature_meta = PdfSignatureMetadata(field_name="Assinatura1")
            appearance = TextStampStyle()

            pdf_signer = PdfSigner(
                signature_meta=signature_meta,
                signer=signer,
                appearance=appearance,
                new_field_spec=sig_field,
                existing_fields_only=False
            )

            with open(input_pdf_path, 'rb') as doc_input, open(output_pdf_path, 'wb') as doc_output:
                pdf_signer.sign_pdf(doc_input, output=doc_output)

        print("✅ PDF assinado com sucesso.")
        return output_pdf_path

    except SigningError as e:
        print(f"❌ Erro de assinatura: {e}")
        traceback.print_exc()
        raise
    except Exception as e:
        print(f"❌ Erro geral durante assinatura: {e}")
        traceback.print_exc()
        raise

