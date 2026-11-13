"""
Rotas de assinatura digital de PDF.
"""
import os
import uuid
import io
import logging

import fitz  # PyMuPDF
from PIL import Image, ImageDraw, ImageFont
from flask import Blueprint, request, jsonify

from core.config import UPLOAD_FOLDER, OCR_OUTPUT_FOLDER, SIGNED_FOLDER

logger = logging.getLogger(__name__)

signing_bp = Blueprint('signing', __name__)


@signing_bp.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Recurso não encontrado"}), 404

@signing_bp.errorhandler(400)
def bad_request(e):
    return jsonify({"error": "Requisição inválida"}), 400

@signing_bp.errorhandler(500)
def internal_error(e):
    logger.error(f"Erro interno: {e}")
    return jsonify({"error": "Erro interno do servidor"}), 500

# Referência ao serviço PKCS#11 (será definida no app.py)
pkcs11_service = None


def set_pkcs11_service(service):
    """Define o serviço PKCS#11 para uso nas rotas de assinatura."""
    global pkcs11_service
    pkcs11_service = service


def get_local_ip():
    """Obtém o IP local da máquina."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def gerar_iniciais(nome_completo):
    """Gera as iniciais de um nome completo."""
    palavras = nome_completo.split()
    if not palavras:
        return ""
    if len(palavras) == 1:
        return palavras[0][0].upper()
    return (palavras[0][0] + palavras[-1][0]).upper()


@signing_bp.route('/obter_certificado_info', methods=['POST'])
def obter_certificado_info():
    """
    Obtém as informações do certificado digital a partir do token USB.
    Recebe o PIN do token via JSON (campo 'pin').
    """
    if not pkcs11_service:
        return jsonify({"success": False, "message": "Serviço PKCS#11 não carregado. Não é possível consultar o certificado."}), 500

    data = request.get_json()
    pin = data.get("pin")

    if not pin:
        return jsonify({"success": False, "message": "PIN não fornecido."}), 400

    try:
        cert_info = pkcs11_service.get_certificate_info(pin)

        assinatura_texto = (
            f"Assinado Digitalmente\n"
            f"{cert_info['name']}\n"
            f"{'CPF' if len(cert_info['doc_id']) == 11 else 'CNPJ'}: {cert_info['doc_id']}\n"
            f"Válido de: {cert_info['valid_from']}\n"
            f"Válido até: {cert_info['valid_until']}"
        )

        return jsonify({
            "success": True,
            "cert_info": {
                "name": cert_info['name'],
                "doc_id": cert_info['doc_id'],
                "valid_from": cert_info['valid_from'],
                "valid_until": cert_info['valid_until'],
                "assinatura_texto": assinatura_texto
            }
        }), 200

    except RuntimeError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "message": f"Ocorreu um erro inesperado: {e}"}), 500


@signing_bp.route('/assinar_pdf_local', methods=['POST'])
def assinar_pdf_local():
    """
    Assina um PDF digitalmente usando o token PKCS#11 localmente.
    Recebe o nome do arquivo, PIN e coordenadas da assinatura do frontend.
    """
    if not pkcs11_service:
        return jsonify({"success": False, "message": "Serviço PKCS#11 não carregado. Não é possível assinar."}), 500

    data = request.get_json()
    pdf_filename_with_path = data.get("filename")

    pin = data.get("pin")
    signature_x = data.get("signature_x")
    signature_y = data.get("signature_y")
    signature_width = data.get("signature_width")
    signature_height = data.get("signature_height")
    page_num = data.get("page_num", 0)

    signature_reason = data.get("signature_reason", "Assinado Digitalmente")
    signature_location = data.get("signature_location", get_local_ip())
    signature_contact_info = data.get("signature_contact_info", "Contato Não Informado")

    if not pdf_filename_with_path:
        return jsonify({"error": "Caminho do PDF não fornecido para assinatura."}), 400
    if not pin:
        return jsonify({"error": "PIN é obrigatório para a assinatura."}), 400
    if any(p is None for p in [signature_x, signature_y, signature_width, signature_height]):
        return jsonify({"error": "Coordenadas de assinatura incompletas do frontend."}), 400

    input_pdf_full_path = None
    if pdf_filename_with_path.startswith('/ocr_outputs/'):
        pdf_name_only = pdf_filename_with_path.replace('/ocr_outputs/', '')
        input_pdf_full_path = os.path.join(OCR_OUTPUT_FOLDER, pdf_name_only)
    elif pdf_filename_with_path.startswith('/uploads/'):
        pdf_name_only = pdf_filename_with_path.replace('/uploads/', '')
        input_pdf_full_path = os.path.join(UPLOAD_FOLDER, pdf_name_only)
    else:
        temp_path_upload = os.path.join(UPLOAD_FOLDER, pdf_filename_with_path)
        temp_path_ocr = os.path.join(OCR_OUTPUT_FOLDER, pdf_filename_with_path)
        if os.path.exists(temp_path_ocr):
            input_pdf_full_path = temp_path_ocr
        elif os.path.exists(temp_path_upload):
            input_pdf_full_path = temp_path_upload

    if not input_pdf_full_path or not os.path.exists(input_pdf_full_path):
        return jsonify({"error": f"Arquivo '{pdf_filename_with_path}' não encontrado no servidor para assinatura."}), 404

    try:
        with open(input_pdf_full_path, 'rb') as f:
            pdf_bytes_to_sign = f.read()

        if not pdf_bytes_to_sign:
            return jsonify({"error": "O arquivo PDF a ser assinado está vazio."}), 400

        signed_pdf_bytes = pkcs11_service.sign_pdf_document(
            pdf_bytes_to_sign,
            pin,
            signature_reason,
            signature_location,
            signature_contact_info,
            page_num,
            signature_x,
            signature_y,
            signature_width,
            signature_height
        )

        if not signed_pdf_bytes:
            return jsonify({"error": "O serviço de assinatura retornou um PDF assinado vazio."}), 500

        original_base_name = os.path.basename(pdf_filename_with_path)
        signed_filename = f"signed_{uuid.uuid4().hex}_{original_base_name}"
        signed_path = os.path.join(SIGNED_FOLDER, signed_filename)

        with open(signed_path, "wb") as f_out:
            f_out.write(signed_pdf_bytes)

        return jsonify({
            "message": "PDF assinado com sucesso",
            "signed_pdf_path": f"/signed/{signed_filename}"
        }), 200

    except RuntimeError as e:
        return jsonify({"error": f"Erro ao assinar digitalmente: {e}"}), 400
    except Exception as e:
        return jsonify({"error": f"Ocorreu um erro interno ao assinar o PDF: {e}"}), 500


@signing_bp.route('/assinar_pdf_area_texto', methods=['POST'])
def assinar_pdf_area_texto():
    data = request.get_json()

    pdf_filename_with_path = data.get("filename")
    pin = data.get("pin")
    signature_x = data.get("signature_x")
    signature_y = data.get("signature_y")
    signature_width = data.get("signature_width")
    signature_height = data.get("signature_height")
    page_num = data.get("page_num", 0)
    assinatura_texto = data.get("assinatura_texto")
    nome_completo = data.get("nome_completo", "")

    if not pdf_filename_with_path:
        return jsonify({"error": "Caminho do PDF não fornecido."}), 400
    if not assinatura_texto:
        return jsonify({"error": "Texto de assinatura não fornecido."}), 400

    input_pdf_full_path = None
    if pdf_filename_with_path.startswith('/ocr_outputs/'):
        pdf_name_only = pdf_filename_with_path.replace('/ocr_outputs/', '')
        input_pdf_full_path = os.path.join(OCR_OUTPUT_FOLDER, pdf_name_only)
    elif pdf_filename_with_path.startswith('/uploads/'):
        pdf_name_only = pdf_filename_with_path.replace('/uploads/', '')
        input_pdf_full_path = os.path.join(UPLOAD_FOLDER, pdf_name_only)
    else:
        temp_path_upload = os.path.join(UPLOAD_FOLDER, pdf_filename_with_path)
        temp_path_ocr = os.path.join(OCR_OUTPUT_FOLDER, pdf_filename_with_path)
        if os.path.exists(temp_path_ocr):
            input_pdf_full_path = temp_path_ocr
        elif os.path.exists(temp_path_upload):
            input_pdf_full_path = temp_path_upload

    if not input_pdf_full_path or not os.path.exists(input_pdf_full_path):
        return jsonify({"error": f"Arquivo '{pdf_filename_with_path}' não encontrado."}), 404

    try:
        doc = fitz.open(input_pdf_full_path)
        page = doc[page_num]
        page_height = page.rect.height
        page_width = page.rect.width

        pdf_x = signature_x
        pdf_y = signature_y
        pdf_width = signature_width
        pdf_height = signature_height

        MIN_WIDTH_PDF = 100
        MIN_HEIGHT_PDF = 20

        if pdf_width < MIN_WIDTH_PDF:
            delta_w = (MIN_WIDTH_PDF - pdf_width) / 2
            pdf_x = max(0, pdf_x - delta_w)
            pdf_width = MIN_WIDTH_PDF

        if pdf_height < MIN_HEIGHT_PDF:
            delta_h = (MIN_HEIGHT_PDF - pdf_height) / 2
            pdf_y = max(0, pdf_y - delta_h)
            pdf_height = MIN_HEIGHT_PDF

        rect = fitz.Rect(pdf_x, pdf_y, pdf_x + pdf_width, pdf_y + pdf_height)

        img_width_px = int(pdf_width * 2)
        img_height_px = int(pdf_height * 2)

        img = Image.new("RGBA", (img_width_px, img_height_px), (255, 255, 255, 0))
        draw = ImageDraw.Draw(img)

        try:
            logo = Image.open("crc.jpg").convert("RGBA")
            logo = logo.resize((img_width_px, img_height_px))

            alpha = 80
            r, g, b, a = logo.split()
            a = a.point(lambda p: alpha)
            logo = Image.merge("RGBA", (r, g, b, a))

            img.paste(logo, (0, 0), logo)
        except Exception as e:
            print(f"[WARNING] Falha ao aplicar logo de fundo: {e}")

        iniciais = gerar_iniciais(nome_completo)

        watermark_fontsize = int(img_height_px * 0.4)

        try:
            watermark_font = ImageFont.truetype("arial.ttf", size=watermark_fontsize)
        except:
            watermark_font = ImageFont.load_default()

        bbox_wm = draw.textbbox((0, 0), iniciais, font=watermark_font)
        wm_w = bbox_wm[2] - bbox_wm[0]
        wm_h = bbox_wm[3] - bbox_wm[1]

        wm_x = (img_width_px - wm_w) / 2
        wm_y = (img_height_px - wm_h) / 2

        draw.text((wm_x, wm_y), iniciais, font=watermark_font, fill=(0, 0, 0, 255))

        fontsize = int(img_height_px * 0.4)
        min_fontsize = 8

        while fontsize >= min_fontsize:
            try:
                font = ImageFont.truetype("arial.ttf", size=fontsize)
            except:
                font = ImageFont.load_default()

            bbox = draw.textbbox((0, 0), assinatura_texto, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]

            if text_w <= img_width_px * 0.95:
                break
            fontsize -= 1

        text_x = (img_width_px - text_w) / 2
        text_y = (img_height_px - text_h) / 2 + (img_height_px * 0.05)

        draw.text((text_x, text_y), assinatura_texto, font=font, fill="black")

        img_rgb = img.convert("RGB")
        img_bytes = io.BytesIO()
        img_rgb.save(img_bytes, format="PNG")
        img_bytes.seek(0)

        page.insert_image(rect, stream=img_bytes.getvalue(), overlay=True)

        original_base_name = os.path.basename(pdf_filename_with_path)
        signed_filename = f"signed_image_{uuid.uuid4().hex}_{original_base_name}"
        signed_path = os.path.join(SIGNED_FOLDER, signed_filename)
        doc.save(signed_path)
        doc.close()

        return jsonify({
            "message": "PDF assinado com sucesso (modo imagem com iniciais).",
            "signed_pdf_path": f"/signed/{signed_filename}"
        }), 200

    except Exception as e:
        return jsonify({"error": f"Falha ao assinar PDF: {e}"}), 500
