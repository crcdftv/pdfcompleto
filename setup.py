import sys
import os
from cx_Freeze import setup, Executable

# Nome do seu arquivo principal (ajuste se for diferente)
script_principal = "assinador_interface.py"
# Nome do ícone
icone_arquivo = "signature.ico"

# Configurações do build
build_exe_options = {
    "packages": [
        "os", "sys", "re", "threading", "datetime", "io",
        "PyQt6", "fitz", "PIL", "PyKCS11", "cryptography", "pypdf", "asn1crypto"
    ],
    "includes": [
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets"
    ],
    "include_files": [
        (icone_arquivo, icone_arquivo), # Garante que o ícone vá junto na pasta
        # Adicione aqui outros recursos como .env ou imagens da interface
    ],
    "excludes": ["tkinter", "unittest", "pydoc", "http", "email"],
    "optimize": 2,
}

# Configuração para Windows: Ocultar o console (CMD)
base = None
if sys.platform == "win32":
    base = "Win32GUI"

executable = [
    Executable(
        script_principal,
        base=base,
        target_name="AssinadorPDF.exe",
        icon=icone_arquivo # Define o ícone do .exe
    )
]

setup(
    name="Assinador PDF",
    version="1.0",
    description="Sistema de Assinatura Digital PKCS#11",
    options={"build_exe": build_exe_options},
    executables=executable
)