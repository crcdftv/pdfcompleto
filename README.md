# PDFCompleto

Editor de PDF completo em Python/Flask, com OCR, assinatura digital, compressão,
conversão para Word/Excel e ferramentas de edição — direto no navegador.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Flask](https://img.shields.io/badge/flask-3.x-black)
![Tesseract](https://img.shields.io/badge/ocr-tesseract-green)

## Funcionalidades

| Recurso | Descrição |
|---|---|
| **Visualização/OCR** | PDF pesquisável: o texto reconhecido entra como camada invisível **sobre a página original** (cores, vetores e assinaturas intactos) |
| **Editor de PDF** | Tarjas (redaction), texto, rotação, zoom, busca e miniaturas |
| **Assinatura digital** | Assinatura via token USB (PKCS#11) ou certificado local |
| **Conversões** | PDF → Word (`.docx`), PDF → Excel (`.xlsx`), OCR de PDF |
| **Manipulação** | Dividir, comprimir, juntar e extrair páginas |
| **Sessões ativas** | Indicador de quantos navegadores estão usando o sistema (heartbeat) |

## Requisitos

- **Python 3.10+**
- **Tesseract OCR** (com os idiomas `por` e `eng`) — configurado em `core/config.py`
- **Poppler** (para `pdf2image`) e **Windows** para o token PKCS#11

## Instalação

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

No Windows, as dependências extras (build, PyQt, token USB) estão em
`requirements-windows.txt`:

```bash
pip install -r requirements-windows.txt
```

## Instalação em servidor Linux (VPS)

Instalação **nativa** (venv + systemd + nginx) em Ubuntu/Debian:

```bash
git clone https://github.com/crcdftv/pdfcompleto.git
cd pdfcompleto
sudo bash deploy/install.sh
```

O instalador cuida de tudo: Tesseract (`por`+`eng`), Poppler, nginx, usuário
`sistema pdfcompleto`, venv em `/opt/pdfcompleto`, dados em
`/var/lib/pdfcompleto`, serviço systemd e proxy nginx.

- **Guia completo (passo a passo, domínio, HTTPS, swap, backup):**
  [`deploy/DEPLOY.md`](deploy/DEPLOY.md)
- **Configuração por variáveis de ambiente:** [`deploy/.env.example`](deploy/.env.example)
- **Atualizar o código depois:** `sudo bash deploy/update.sh`

Alternativa com Docker:

```bash
docker build -t pdfcompleto .
docker run -d -p 5000:5000 -e SECRET_KEY=$(openssl rand -hex 32) \
  -v pdfcompleto_dados:/data --restart unless-stopped pdfcompleto
```

> A assinatura digital por **token USB** é Windows-only (driver SafeSign). Na
> VPS o sistema sobe sem ela — continue assinando pelo PC Windows.

## Executando

```bash
# desenvolvimento
python app.py

# produção (waitress, porta 5000)
python run_production.py
```

Depois abra <http://localhost:5000>.

## OCR: como funciona

O OCR é o ponto mais delicado do projeto, então vale explicar:

- A página **nunca é reescrita**. O texto reconhecido é escrito como camada
  invisível (`render_mode=3`) na própria página do documento — assim o PDF
  mantém cores, resolução, vetores, formulários e assinaturas digitais.
- Páginas com **texto nativo denso** são mantidas como estão (o texto original
  já é perfeito; re-OCRizar só duplicaria e pioraria).
- Páginas **digitalizadas** ganham a camada de OCR; palavras já cobertas pelo
  texto nativo são ignoradas para não duplicar.
- Páginas **giradas** (`/Rotate`) são carimbadas com `rotate=page.rotation`, para
  o texto ficar deitado na página como o leitor mostra.
- O pré-processamento (`core/ocr_preprocess.py`) normaliza contraste, corrige
  inclinação (deskew por Hough) e refaz o reconhecimento com outros modos de
  segmentação quando o resultado sai ruim.

## Estrutura

```
app.py                 # app Flask: registra os blueprints
core/                  # config, utils, pré-processamento de OCR, presença
routes/                # blueprints: upload, ocr, excel, compress, signing,
                       # editing, conversions, manipulation
static/                # CSS e JS (módulos ES)
templates/             # HTML da interface
assinador_local/       # pacote do assinador (desktop)
pkcs11_service.py      # ponte para o token USB (PKCS#11)
```

## Segurança

- O **PIN do token USB** não fica no código: leia da variável de ambiente
  ```bash
  set TOKEN_PIN=seu_pin
  ```
- Chaves (`*.pem`), certificados (`*.pfx`), PDFs dos clientes e arquivos de
  sessão ficam fora do repositório (ver `.gitignore`).
- `app.config['SECRET_KEY']` deve ser trocado por um valor forte e fixo em
  produção (hoje é gerado em memória a cada start).

## Licença

Projeto interno. Todos os direitos reservados.
