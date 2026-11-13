@echo off
cd /d C:\Users\Suporte\pdfcompleto
call .venv1\Scripts\activate
waitress-serve --host=0.0.0.0 --port=5000 app:app