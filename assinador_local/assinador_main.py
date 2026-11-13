# assinador_main.py
import subprocess
import sys
import os
from app_assinador import app

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    app_path = os.path.join(base_dir, "app_assinador.py")

    subprocess.Popen(
        [sys.executable, app_path],
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    )

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=15000, debug=False)