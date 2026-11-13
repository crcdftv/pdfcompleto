import os
import io
import re
import sys
import base64
import socket
import logging
import tempfile
import traceback
from datetime import datetime
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS

# Importações de pyhanko
from pyhanko.sign.pkcs11 import open_pkcs11_session, PKCS11Signer
from pyhanko.sign.signers import PdfSigner, PdfSignatureMetadata
from pyhanko.sign.fields import SigFieldSpec
from pyhanko.stamp import TextStampStyle
from pyhanko.sign.general import SigningError

# --- INÍCIO DA SEÇÃO DE CONFIGURAÇÃO DE CAMINHO DO DLL ---
# Determina o caminho base para recursos quando rodando como executável
if getattr(sys, 'frozen', False):
    # Se estiver rodando como executável (PyInstaller ou cx_Freeze), usa o caminho do executável.
    # Em cx_Freeze, sys.executable é o próprio executável.
    # Em PyInstaller, sys._MEIPASS é o diretório temporário onde os arquivos são extraídos.
    base_path = os.path.dirname(sys.executable) if sys.platform == "win32" else sys._MEIPASS
else:
    # Se estiver rodando como script Python normal, usa o diretório atual do script.
    base_path = os.path.dirname(os.path.abspath(__file__))

LIB_FILENAME = "aetpkss1.dll"
# Caminho completo para o DLL. Ele será procurado na mesma pasta do executável após o empacotamento.
LIB_PATH = os.path.join(base_path, LIB_FILENAME)
# --- FIM DA SEÇÃO DE CONFIGURAÇÃO DE CAMINHO DO DLL ---

# 🔧 CONFIGURAÇÕES DO TOKEN E LOG
SLOT_NO = 0  # Slot do token, geralmente 0 para o primeiro token detectado.

# Configuração do log para arquivo e terminal
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("assinador_local.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)

app = Flask(__name__)
# Configura CORS para permitir requisições de origens específicas.
# Se você tiver um frontend em um endereço diferente, adicione-o aqui.
# No exemplo original, você tinha "http://172.17.11.220:5000", "http://localhost:5000"
# Se for deixar completamente aberto para teste, use CORS(app, resources={r"/*": {"origins": "*"}})
# Mas em produção, restrinja as origens.
CORS(app, resources={r"/*": {"origins": ["http://172.17.11.220:5000", "http://localhost:5000", "*"]}})

# Garante que a pasta 'signed' exista para arquivos de saída, se necessário
SIGNED_FOLDER = os.path.join(os.getcwd(), "signed")
os.makedirs(SIGNED_FOLDER, exist_ok=True)

# 🔐 FUNÇÃO DE ASSINATURA DO PDF
def assinar_pdf(input_pdf_path, output_pdf_path, pin, x, y, width, height):
    try:
        logging.info("🔐 Iniciando assinatura do PDF...")
        logging.debug(f"Input PDF: {input_pdf_path}, Output PDF: {output_pdf_path}")
        logging.debug(f"PIN: {'*' * len(pin)}, Coords: x={x}, y={y}, w={width}, h={height}")
        logging.debug(f"Tentando carregar DLL PKCS#11 de: {LIB_PATH}")

        # Define as coordenadas da caixa de assinatura no PDF
        # Note que pyhanko usa (left, bottom, right, top)
        box = (x, y + height, x + width, y)
        sig_field = SigFieldSpec(sig_field_name="Assinatura1", box=box)
        signature_meta = PdfSignatureMetadata(field_name="Assinatura1")
        appearance = TextStampStyle() # Pode ser customizado para selos visíveis

        # Abre a sessão PKCS#11 e inicializa o signer
        with open_pkcs11_session(lib_location=LIB_PATH, user_pin=pin, slot_no=SLOT_NO) as sess:
            signer = PKCS11Signer(session=sess)
            pdf_signer = PdfSigner(
                signature_meta=signature_meta,
                signer=signer,
                appearance=appearance,
                new_field_spec=sig_field,
                existing_fields_only=False # Cria o campo se não existir
            )
            # Abre os arquivos de entrada e saída e realiza a assinatura
            with open(input_pdf_path, 'rb') as doc_input, open(output_pdf_path, 'wb') as doc_output:
                pdf_signer.sign_pdf(doc_input, output=doc_output)

        logging.info("✅ PDF assinado com sucesso.")
        return output_pdf_path

    except SigningError as e:
        logging.error(f"❌ Erro de assinatura (PyHanko/PKCS#11): {e}")
        traceback.print_exc()
        raise # Re-lança o erro para ser capturado pelo endpoint
    except Exception as e:
        logging.error(f"❌ Erro geral durante a assinatura: {e}")
        traceback.print_exc()
        raise # Re-lança o erro para ser capturado pelo endpoint

# 🔄 ENDPOINT PARA TESTE DE STATUS DO SERVIÇO
@app.route("/ping")
def ping():
    logging.info("Recebida requisição /ping")
    return "pong", 200

# 📥 ENDPOINT PRINCIPAL PARA ASSINATURA DE PDF
@app.route('/assinar_pdf_local', methods=['POST'])
def assinar_pdf_endpoint():
    data = request.get_json()
    logging.debug(f"📥 Requisição de assinatura recebida. Chaves presentes: {data.keys()}")

    # Validação dos parâmetros de entrada
    required_fields = [
        'pdf_content_base64', 'original_filename', 'pin',
        'signature_x', 'signature_y', 'signature_width', 'signature_height'
    ]
    # Verifica se todos os campos necessários estão presentes e não são None
    if not all(field in data and data[field] is not None for field in required_fields):
        missing_params = [field for field in required_fields if field not in data or data[field] is None]
        logging.warning(f"Parâmetros incompletos na requisição: {', '.join(missing_params)}")
        return jsonify({"error": f"Parâmetros incompletos. Faltando: {', '.join(missing_params)}"}), 400

    # Inicializa variáveis para garantir que temp files sejam removidos no finally
    temp_input_path = None
    temp_output_path = None

    try:
        # Decodifica o conteúdo do PDF de base64 para bytes
        pdf_bytes = base64.b64decode(data['pdf_content_base64'])

        # Cria um arquivo temporário para o PDF de entrada
        temp_input_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        temp_input_file.write(pdf_bytes)
        temp_input_file.close()
        temp_input_path = temp_input_file.name
        logging.debug(f"PDF temporário de entrada criado: {temp_input_path}")

        # Gera um nome seguro e único para o PDF de saída
        safe_base = re.sub(r'[^\w\-_\.]', '_', os.path.splitext(data['original_filename'])[0])
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        output_filename = f"signed_{safe_base}_{timestamp}.pdf"
        # O arquivo assinado também é criado em um diretório temporário para ser retornado
        temp_output_path = os.path.join(tempfile.gettempdir(), output_filename)
        logging.debug(f"PDF temporário de saída esperado: {temp_output_path}")

        # Chama a função de assinatura principal
        assinar_pdf(
            input_pdf_path=temp_input_path,
            output_pdf_path=temp_output_path,
            pin=data['pin'],
            x=data['signature_x'],
            y=data['signature_y'],
            width=data['signature_width'],
            height=data['signature_height']
        )

        # Verifica se o arquivo assinado foi realmente criado
        if not os.path.exists(temp_output_path):
            raise Exception(f"O arquivo assinado não foi encontrado no caminho esperado: {temp_output_path}")

        # Lê o PDF assinado e o envia como resposta
        with open(temp_output_path, 'rb') as f_signed:
            signed_pdf_bytes = f_signed.read()
        logging.info("PDF assinado lido para retorno.")

        return send_file(
            io.BytesIO(signed_pdf_bytes),
            mimetype='application/pdf',
            as_attachment=False, # Envia o PDF para ser exibido no navegador, não baixado
            download_name=output_filename
        )

    except Exception as e:
        logging.error(f"Erro no serviço de assinatura durante o processamento da requisição: {e}", exc_info=True)
        return jsonify({"error": "Erro no serviço de assinatura", "details": str(e)}), 500
    finally:
        # Limpa os arquivos temporários
        if temp_input_path and os.path.exists(temp_input_path):
            os.remove(temp_input_path)
            logging.debug(f"Arquivo temporário de entrada removido: {temp_input_path}")
        if temp_output_path and os.path.exists(temp_output_path):
            os.remove(temp_output_path)
            logging.debug(f"Arquivo temporário de saída removido: {temp_output_path}")

# 🔍 ENDPOINT PARA LISTAR TOKENS PKCS#11 DISPONÍVEIS
@app.route('/list_tokens', methods=['GET'])
def list_tokens():
    try:
        import pkcs11 as p11
        lib = p11.lib(LIB_PATH)
        slots = lib.get_slots(token_present=True)
        tokens = []
        for slot in slots:
            try:
                token = slot.get_token()
                tokens.append({
                    "label":  token.label.strip(),
                    "serial": token.serial.strip(),
                    "slot":   slot.slot_id
                })
            except Exception as e:
                logging.warning(f"Slot sem token válido: {e}")
        logging.info(f"Tokens encontrados: {tokens}")
        return jsonify({"success": True, "tokens": tokens}), 200
    except Exception as e:
        logging.error(f"Erro ao listar tokens: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "tokens": [], "error": str(e)}), 500


# --- INÍCIO DO BLOCO TRY/EXCEPT GLOBAL ---
if __name__ == '__main__':
    try:
        # Tenta obter o IP da máquina para exibição, útil em ambientes de rede
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except socket.error:
            ip = "127.0.0.1" # Fallback para localhost se não conseguir obter o IP

        PORT = 15002 # Porta atual
        print(f"🔐 Servidor de assinatura disponível em: http://{ip}:{PORT}")
        logging.info(f"Servidor de assinatura iniciado em: http://{ip}:{PORT}")

        # Para produção, use debug=False. Para desenvolvimento, debug=True é útil.
        # O host '0.0.0.0' permite que o servidor seja acessível de outras máquinas na rede.
        app.run(host='0.0.0.0', port=PORT, debug=False)

    except Exception as e:
        # Captura qualquer exceção não tratada na inicialização do Flask
        error_message = f"❌ Ocorreu um erro crítico na inicialização do servidor: {e}"
        logging.critical(error_message)
        # Imprime o traceback completo para o console/stderr.log
        traceback.print_exc()
        # Adiciona um input() para manter a janela do console aberta no Windows
        # Isso é útil para ver o erro diretamente se o .bat não for usado ou não capturar tudo
        if sys.platform == "win32":
            input("Pressione Enter para fechar...")
# --- FIM DO BLOCO TRY/EXCEPT GLOBAL ---