import sys
import os
from cx_Freeze import setup, Executable

# Obter o diretório atual do script setup_antigo.py
current_dir = os.path.dirname(os.path.abspath(__file__))

# Caminho completo para o seu arquivo DLL do SafeSign
# Certifique-se de que este caminho está correto no seu sistema
SAFE_SIGN_DLL_PATH = "C:\\Windows\\System32\\aetpkss1.dll"

# Verificar se o DLL existe antes de tentar incluí-lo (opcional, mas recomendado)
if not os.path.exists(SAFE_SIGN_DLL_PATH):
    print(f"AVISO: O arquivo DLL '{SAFE_SIGN_DLL_PATH}' não foi encontrado. Certifique-se de que ele existe e o caminho está correto.", file=sys.stderr)
    # Você pode optar por parar aqui ou continuar sem o DLL, dependendo da sua estratégia.

# Base para o executável (Console para ver os logs do Flask)
base = "Console" if sys.platform == "win32" else None

# Opções de build para cx_Freeze
build_exe_options = {
    # Lista de pacotes que devem ser incluídos.
    # cx_Freeze tenta detectar, mas explicitamente é mais seguro para libs complexas.
    "packages": [
        "flask", "flask_cors", "PyKCS11", "pyhanko",
        "os", "io", "re", "sys", "base64", "socket", "logging", "tempfile", "traceback", "datetime",
        "chardet",
        "asyncio" # Agora incluso corretamente
    ],
    # Módulos que podem precisar ser explicitamente incluídos porque cx_Freeze não os encontra.
    # pyhanko tem algumas dependências internas que podem precisar de atenção.
    "includes": [
        "pyhanko.sign.pkcs11",
        "pyhanko.sign.signers",
        "pyhanko.sign.fields",
        "pyhanko.stamp",
        "pyhanko.sign.general",
        "certifi", # pyhanko pode depender de certifi para certificados SSL/TLS
        "asn1crypto", # pyhanko usa asn1crypto para parsing ASN.1
        "cryptography", # pyhanko e PyKCS11 podem depender de cryptography
        "idna", # Flask e requests podem depender
        "chardet", # Flask e requests podem depender
        "urllib3", # Flask e requests podem depender
        "requests", # Flask e dependências
        "werkzeug", # Flask
        "jinja2", # Flask
        "itsdangerous", # Flask
        "click", # Flask
    ],
    # Exclua módulos que você sabe que não precisa para reduzir o tamanho.
    "excludes": ["tkinter", "unittest", "pydoc", "doctest", "xmlrpc", "test", "distutils"], # 'asyncio' REMOVIDO DAQUI
    "optimize": 1, # Nível de otimização

    # Incluir o DLL do SafeSign.
    # O primeiro elemento da tupla é o caminho de origem, o segundo é o nome/caminho de destino no bundle.
    "include_files": [
        (SAFE_SIGN_DLL_PATH, os.path.basename(SAFE_SIGN_DLL_PATH)),
        # Você pode adicionar outros arquivos aqui se o seu aplicativo precisar, por exemplo:
        # os.path.join(current_dir, "config.ini"),
        # os.path.join(current_dir, "images"), # Para incluir uma pasta inteira
    ],
    "include_msvcr": True, # Inclui as DLLs de tempo de execução do Visual C++ no Windows (essencial!)
}

# Configuração do executável
setup(
    name="AssinadorLocal",
    version="1.0",
    description="Serviço de Assinatura Local de PDFs com PyHanko e PKCS#11",
    options={"build_exe": build_exe_options},
    executables=[
        Executable(
            "assinador_local.py", # Seu script principal unificado
            base=base,
            target_name="AssinadorLocal.exe", # Nome do executável de saída
            icon=None # Opcional: Caminho para um arquivo .ico se desejar um ícone personalizado
        )
    ]
)