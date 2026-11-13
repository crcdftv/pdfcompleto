import sys
import os
from endesive import pdf, signer
import pkcs11  # Importa a biblioteca 'python-pkcs11' (nome do pacote é 'pkcs11')

# --- Configurações do seu token ---
PKCS11_LIB_PATH = 'C:\\Windows\\System32\\aetpkss1.dll'  # <--- AJUSTE AQUI O CAMINHO DA SUA DLL/SO PKCS#11
# PIN do token USB: leia da variavel de ambiente TOKEN_PIN
# (nunca versionar o segredo no repositorio)
TOKEN_PIN = os.environ.get('TOKEN_PIN', '')
CERT_LABEL = None  # <--- OPCIONAL: Ajuste aqui
KEY_LABEL = None  # <--- OPCIONAL: Ajuste aqui
# --- Fim das configurações ---

session = None
lib = None
cert_obj = None
private_key_obj = None

try:
    lib = pkcs11.lib(PKCS11_LIB_PATH)
    slots = lib.get_slots(token_present=True)
    if not slots:
        raise Exception("Nenhum token USB encontrado. Verifique se está conectado e os drivers estão instalados.")

    session = pkcs11.Session(lib, slots[0])

    # Se 'find_objects' ainda não funcionar, tentaremos 'get_objects'
    # mas o erro 'find_objects' é o mais estranho para esta lib.
    certs = session.find_objects({  # Esta linha é a que falhou
        pkcs11.CKA_CLASS: pkcs11.CKO_CERTIFICATE,
        pkcs11.CKA_TOKEN: pkcs11.CKA_TRUE
    })

    my_cert_obj = None
    for c_obj in certs:
        try:
            cert_label_attr = c_obj.get_attribute(pkcs11.CKA_LABEL)
            if isinstance(cert_label_attr, bytes):
                cert_label_attr = cert_label_attr.decode('utf-8', errors='ignore')
        except pkcs11.PKCS11Error:
            cert_label_attr = None

        if CERT_LABEL and cert_label_attr == CERT_LABEL:
            my_cert_obj = c_obj
            break
        elif not CERT_LABEL:
            my_cert_obj = c_obj
            break

    if not my_cert_obj:
        raise Exception(
            f"Certificado não encontrado no token. Verifique o label ('{CERT_LABEL}' se especificado) ou se ele existe.")

    cert_der = my_cert_obj.get_attribute(pkcs11.CKA_VALUE)

    key_attributes = {
        pkcs11.CKA_CLASS: pkcs11.CKO_PRIVATE_KEY,
        pkcs11.CKA_TOKEN: pkcs11.CKA_TRUE
    }
    if KEY_LABEL:
        key_attributes[pkcs11.CKA_LABEL] = KEY_LABEL.encode('utf-8')

    privKeys_iter = session.find_objects(key_attributes)  # Esta linha também falharia

    private_key_obj = None
    for k_obj in privKeys_iter:
        private_key_obj = k_obj
        break

    if not private_key_obj:
        raise Exception(
            "Chave privada não encontrada no token. Certifique-se de que o certificado selecionado tem uma chave privada correspondente.")


    def pkcs11_sign_func(digest):
        return session.sign(private_key_obj, digest, pkcs11.Mechanism(pkcs11.CKM_SHA256_RSA_PKCS))


    signer_instance = signer.CAdESSigner(
        data_signer=pkcs11_sign_func,
        cert=cert_der,
    )

    input_pdf_path = 'documento_nao_assinado.pdf'
    output_pdf_path = 'documento_assinado_endesive.pdf'

    if not os.path.exists(input_pdf_path):
        raise FileNotFoundError(f"O arquivo de entrada '{input_pdf_path}' não foi encontrado.")

    with open(input_pdf_path, 'rb') as fp:
        datau = fp.read()

    dct = {
        'sigflags': 3,
        'sigpage': 0,
        'sigaprx:reason': 'Assinatura de teste com endesive e token USB',
        'sigaprx:location': 'Brasília, DF, Brasil',
        'sigaprx:contact': 'seu_email@dominio.com',
        'sigaprx:signer': 'Seu Nome Completo',
    }

    datas = pdf.cms.sign(datau, dct, signer_instance)

    with open(output_pdf_path, 'wb') as fp:
        fp.write(datas)

    print(f"PDF assinado com sucesso e salvo em: {output_pdf_path}")

except pkcs11.PKCS11Error as e:
    print(f"Erro PKCS#11 durante a operação: {e}")
    if isinstance(e, pkcs11.exceptions.PinIncorrect):
        print("PIN incorreto. Verifique sua senha do token.")
    elif isinstance(e, pkcs11.exceptions.TokenNotPresent):
        print("Token não presente. Certifique-se de que o token esteja conectado.")
    elif isinstance(e, pkcs11.exceptions.UserNotLoggedIn):
        print("Usuário não logado. Tente fazer login na sessão.")
    else:
        print(f"Erro PKCS#11 detalhe: {e.args}")
except FileNotFoundError as e:
    print(f"Erro de arquivo: {e}")
except Exception as e:
    print(f"Ocorreu um erro inesperado: {e}. Traceback: {sys.exc_info()}")
finally:
    if session:
        try:
            session.close()
            print("Sessão PKCS#11 encerrada com sucesso.")
        except Exception as e:
            print(f"Erro ao fechar a sessão PKCS#11: {e}")

    print("Limpeza da biblioteca PKCS#11 concluída (sem método 'finalize').")