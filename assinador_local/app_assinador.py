from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import os
import tempfile
import io
import base64
from datetime import datetime
import logging
import re
import socket
import sys

from signer import assinar_pdf

# Configura log para arquivo e terminal
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("assinador_local.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)

app = Flask(__name__)
CORS(app)  # Permite todas as origens da rede local

SIGNED_SERVICE_OUTPUT_FOLDER = 'signed_service_output_15000'
os.makedirs(SIGNED_SERVICE_OUTPUT_FOLDER, exist_ok=True)

@app.route('/assinar_pdf_local', methods=['POST'])
def assinar_pdf_endpoint():
    data = request.get_json()

    pdf_content_base64 = data.get("pdf_content_base64")
    original_filename = data.get("original_filename", "document.pdf")
    pin = data.get("pin")
    x = data.get("signature_x")
    y = data.get("signature_y")
    width = data.get("signature_width")
    height = data.get("signature_height")

    if not all([pdf_content_base64, pin, x is not None, y is not None, width is not None, height is not None]):
        missing_params = []
        if not pdf_content_base64: missing_params.append("pdf_content_base64")
        if not pin: missing_params.append("pin")
        if x is None: missing_params.append("x")
        if y is None: missing_params.append("y")
        if width is None: missing_params.append("width")
        if height is None: missing_params.append("height")
        return jsonify({"error": f"Parâmetros incompletos. Faltando: {', '.join(missing_params)}"}), 400

    temp_input_path = None
    temp_output_path = None

    try:
        pdf_bytes = base64.b64decode(pdf_content_base64)

        temp_input_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        temp_input_file.write(pdf_bytes)
        temp_input_file.close()
        temp_input_path = temp_input_file.name
        logging.debug(f"PDF temporário de entrada criado: {temp_input_path}")

        safe_base = re.sub(r'[^\w\-_\.]', '_', os.path.splitext(original_filename)[0])
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        signed_filename_temp = f"signed_temp_{safe_base}_{timestamp}.pdf"
        temp_output_path = os.path.join(tempfile.gettempdir(), signed_filename_temp)

        logging.debug(f"PDF temporário de saída esperado: {temp_output_path}")

        assinar_pdf(temp_input_path, temp_output_path, pin, x, y, width, height)

        if not os.path.exists(temp_output_path):
            raise Exception(f"O arquivo assinado não foi encontrado: {temp_output_path}")

        with open(temp_output_path, 'rb') as f_signed:
            signed_pdf_bytes = f_signed.read()

        logging.debug("PDF assinado lido para retorno.")

        return send_file(
            io.BytesIO(signed_pdf_bytes),
            mimetype='application/pdf',
            as_attachment=False,
            download_name=f"signed_{original_filename}"
        )

    except Exception as e:
        logging.error(f"Erro no serviço de assinatura: {e}")
        return jsonify({"error": "Erro no serviço de assinatura", "details": str(e)}), 500
    finally:
        if temp_input_path and os.path.exists(temp_input_path):
            os.remove(temp_input_path)
            logging.debug(f"Arquivo temporário de entrada removido: {temp_input_path}")
        if temp_output_path and os.path.exists(temp_output_path):
            os.remove(temp_output_path)
            logging.debug(f"Arquivo temporário de saída removido: {temp_output_path}")

@app.route("/ping")
def ping():
    return "pong", 200

if __name__ == '__main__':
    ip = socket.gethostbyname(socket.gethostname())
    print(f"🔐 Servidor de assinatura disponível em: http://{ip}:15000")
    app.run(host='0.0.0.0', port=15000, debug=True)