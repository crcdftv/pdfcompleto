import sys
import os
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from waitress import serve

try:
    from app import app
except Exception:
    print("ERRO ao importar app.py:", file=sys.stderr)
    traceback.print_exc()
    sys.exit(1)

from core.utils import garantir_instancia_unica

if __name__ == "__main__":
    ok, motivo, lock_sock = garantir_instancia_unica(port=5000)
    if not ok:
        print(f"PDFCompleto encerrando: {motivo}", file=sys.stderr)
        sys.exit(1)

    # Mantém o cadeado aberto enquanto o serviço viver
    _LOCK_SOCK = lock_sock

    serve(app, host="0.0.0.0", port=5000)
