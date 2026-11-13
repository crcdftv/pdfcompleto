"""
Agente PKCS#11 – múltiplos tokens / múltiplos certificados
Requisitos: PyKCS11, cryptography, Flask, flask-cors
"""

import re
import threading
import logging
from typing import Dict, List

import PyKCS11
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.x509.oid import NameOID
from flask import Flask, request, jsonify
from flask_cors import CORS
from cryptography.x509.oid import NameOID, ObjectIdentifier

# ---------------------------------------------------------------------------
#  🔧 Configurações
# ---------------------------------------------------------------------------

PKCS11_LIB_PATH = r"C:\Windows\System32\aetpkss1.dll"  # ajuste se necessário
LOG_LEVEL = logging.INFO

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# ---------------------------------------------------------------------------
#  🔒 Cache da DLL e lock global (driver não é thread-safe)
# ---------------------------------------------------------------------------

_pkcs11_lib = None
_pkcs11_lock = threading.Lock()

def get_pkcs11_lib() -> PyKCS11.PyKCS11Lib:
    """Carrega a DLL só uma vez (singleton) e devolve a instância."""
    global _pkcs11_lib
    with _pkcs11_lock:
        if _pkcs11_lib is None:
            lib = PyKCS11.PyKCS11Lib()
            lib.load(PKCS11_LIB_PATH)
            _pkcs11_lib = lib
            logging.debug("DLL PKCS#11 carregada: %s", PKCS11_LIB_PATH)
        return _pkcs11_lib


# ---------------------------------------------------------------------------
#  🛠️  Funções utilitárias para certificados
# ---------------------------------------------------------------------------

def _der_to_x509(der: bytes) -> x509.Certificate:
    return x509.load_der_x509_certificate(der, default_backend())

def _extract_doc_id(cert: x509.Certificate) -> str | None:
    """
    Tenta obter CPF (11 dígitos) ou CNPJ (14 dígitos) do certificado ICP-Brasil.

    1. OIDs oficiais:
       - CPF  : 2.16.76.1.3.1
       - CNPJ : 2.16.76.1.3.3
    2. Fallback: busca 11-14 dígitos em qualquer parte do CN.
    """
    # ① Via OID do CPF
    cpf_oid  = ObjectIdentifier("2.16.76.1.3.1")
    cnpj_oid = ObjectIdentifier("2.16.76.1.3.3")

    for oid in (cpf_oid, cnpj_oid):
        attrs = cert.subject.get_attributes_for_oid(oid)
        if attrs:
            return re.sub(r"\D", "", attrs[0].value)

    # ② Fallback: regex no CN
    cn_attrs = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    if cn_attrs:
        match = re.search(r"(\d{11,14})", cn_attrs[0].value)
        if match:
            return match.group(1)

    return None

def get_document_id_from_cert(cert_x509_obj: x509.Certificate) -> str | None:
    """
    Extrai CPF ou CNPJ do final do Common Name.
    Aceita 11–14 dígitos depois de dois-pontos.
    Ex.: CN=JOSE DA SILVA:12345678901
    """
    subject_cn_attr = cert_x509_obj.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    subject_cn = subject_cn_attr[0].value if subject_cn_attr else None
    if subject_cn:
        match = re.search(r':(\d{11,14})$', subject_cn)
        if match:
            return match.group(1)
    return None


def _serialize_cert(cert: x509.Certificate, token_label: str, slot: int) -> dict:
    cn_attr = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    name = cn_attr[0].value if cn_attr else ""
    doc_id = _extract_doc_id(cert)                # ← usa função acima
    return {
        "token_label": token_label,
        "slot": slot,
        "name": name,
        "doc_id": doc_id,                         # ← garantido agora
        "subject": cert.subject.rfc4514_string(),
        "issuer": cert.issuer.rfc4514_string(),
        "valid_from": cert.not_valid_before_utc.strftime("%d/%m/%Y %H:%M:%S"),
        "valid_until": cert.not_valid_after_utc.strftime("%d/%m/%Y %H:%M:%S"),

    }



# ---------------------------------------------------------------------------
#  🔍 Enumeração de tokens e certificados
# ---------------------------------------------------------------------------

def list_tokens() -> List[dict]:
    """Retorna rótulo e número de série de todos os tokens presentes."""
    pkcs11 = get_pkcs11_lib()
    tokens = []
    for slot in pkcs11.getSlotList(tokenPresent=True):
        info = pkcs11.getTokenInfo(slot)
        tokens.append(
            {"slot": slot, "label": info.label.strip(), "serial": info.serialNumber.strip()}
        )
    return tokens

def enumerate_certificates(pin_map: Dict[str, str]) -> List[dict]:
    """
    Percorre todos os tokens e devolve lista com os certificados de assinatura
    que possuem CPF ou CNPJ.

    pin_map → {"NomeDoToken": "1234", ...}
    """
    pkcs11 = get_pkcs11_lib()
    certs_info: List[dict] = []

    for slot in pkcs11.getSlotList(tokenPresent=True):
        token_label = pkcs11.getTokenInfo(slot).label.strip()
        pin = pin_map.get(token_label)
        if pin is None:
            logging.warning("PIN não fornecido para token '%s' (slot %d). Pulando.", token_label, slot)
            continue

        with _pkcs11_lock:
            session = pkcs11.openSession(slot)
            try:
                session.login(pin)
                for obj in session.findObjects([(PyKCS11.CKA_CLASS, PyKCS11.CKO_CERTIFICATE)]):
                    der = session.getAttributeValue(obj, [PyKCS11.CKA_VALUE])[0]
                    cert_bytes = bytes(der) if isinstance(der, tuple) else der
                    cert_x509 = _der_to_x509(cert_bytes)

                    # 🔒 filtro: tem que ser de assinatura digital
                    try:
                        ku = cert_x509.extensions.get_extension_for_class(x509.KeyUsage)
                        if not ku.value.digital_signature:
                            continue
                    except x509.ExtensionNotFound:
                        continue

                    # 🧾 filtro: tem que ter CPF ou CNPJ
                    doc_id = _extract_doc_id(cert_x509)
                    if not doc_id:
                        continue

                    # ✅ tudo certo, inclui na lista
                    certs_info.append(_serialize_cert(cert_x509, token_label, slot))
            finally:
                try:
                    session.logout()
                finally:
                    session.closeSession()

    return certs_info


# ---------------------------------------------------------------------------
#  📜 Compatibilidade: pegar apenas UM certificado (primeiro token)
# ---------------------------------------------------------------------------

def get_first_cert_info(pin: str) -> dict:
    pkcs11 = get_pkcs11_lib()
    with _pkcs11_lock:
        slots = pkcs11.getSlotList(tokenPresent=True)
        if not slots:
            raise RuntimeError("Nenhum token USB encontrado.")

        session = pkcs11.openSession(slots[0])
        try:
            session.login(pin)
            for obj in session.findObjects([(PyKCS11.CKA_CLASS, PyKCS11.CKO_CERTIFICATE)]):
                der = session.getAttributeValue(obj, [PyKCS11.CKA_VALUE])[0]
                cert_x509 = _der_to_x509(der)
                # Filtra por uso de assinatura digital
                try:
                    ku = cert_x509.extensions.get_extension_for_class(x509.KeyUsage)
                    if not ku.value.digital_signature:
                        continue
                except x509.ExtensionNotFound:
                    continue
                return _serialize_cert(cert_x509, pkcs11.getTokenInfo(slots[0]).label.strip(), slots[0])
        finally:
            try:
                session.logout()
            finally:
                session.closeSession()

    raise RuntimeError("Certificado de assinatura não encontrado no token.")


# ---------------------------------------------------------------------------
#  🌐 Flask API
# ---------------------------------------------------------------------------

app = Flask(__name__)
CORS(app)  # ajuste origins se desejar restringir

@app.route("/list_tokens", methods=["GET"])
def api_list_tokens():
    return jsonify({"success": True, "tokens": list_tokens()}), 200


@app.route("/list_certificates", methods=["POST"])
def api_list_certificates():
    """
    Espera JSON: { "pins": { "LabelTokenA": "1234", "Outro": "9999" } }
    """
    data = request.get_json(silent=True) or {}
    pin_map = data.get("pins") or {}
    if not pin_map:
        return jsonify({"success": False, "error": "Nenhum PIN fornecido"}), 400
    try:
        certs = enumerate_certificates(pin_map)
        return jsonify({"success": True, "certificates": certs}), 200
    except Exception as exc:
        logging.exception("Erro list_certificates")
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route("/get_cert_info", methods=["POST"])
def api_get_cert_info():
    """
    Compatível com a versão antiga.
    Espera JSON: { "pin": "1234" }
    """
    data = request.get_json(silent=True) or {}
    pin = data.get("pin")
    if not pin:
        return jsonify({"success": False, "error": "PIN não fornecido"}), 400
    try:
        cert_info = get_first_cert_info(pin)
        return jsonify({"success": True, "cert_info": cert_info}), 200
    except Exception as exc:
        logging.exception("Erro get_cert_info")
        return jsonify({"success": False, "error": str(exc)}), 500


# ---------------------------------------------------------------------------
#  🚀 Execução
# ---------------------------------------------------------------------------

def main() -> None:
    print("🟢 Agente PKCS11 rodando em http://localhost:5005")
    app.run(host="127.0.0.1", port=5005)

if __name__ == "__main__":
    main()
