import sys

from core.utils import garantir_instancia_unica

if __name__ == "__main__":
    ok, motivo, lock_sock = garantir_instancia_unica(port=5000)
    if not ok:
        print(f"PDFCompleto encerrando: {motivo}", file=sys.stderr)
        sys.exit(1)

    _LOCK_SOCK = lock_sock

    from waitress import serve
    from app import app

    serve(app, host="0.0.0.0", port=5000)
