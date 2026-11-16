# Guia de instalação na VPS (Ubuntu / Debian)

Instalação **nativa** (sem Docker): Python em *venv* + systemd + nginx.
O sistema roda com **1 worker gunicorn + 4 threads** e o OCR usa o Tesseract
instalado pelo apt.

> **A assinatura digital por token USB não funciona na VPS** (driver SafeSign é
> Windows-only). O sistema sobe normalmente sem ela — o botão de assinar fica
> indisponível. Continue assinando pelo PC Windows, como hoje.

---

## 1. Requisitos da VPS

| Item | Mínimo | Recomendado |
|---|---|---|
| SO | Ubuntu 22.04+ / Debian 11+ | Ubuntu 24.04 LTS |
| Python | 3.11 – 3.13 (o instalador garante) | 3.12 |
| RAM | 1 GB | 2–4 GB |
| Disco | 10 GB | 30 GB+ (PDFs processed ocupam espaço) |
| Acesso | `root` via SSH | `root` via SSH |

Acesso SSH:

```bash
ssh root@IP_DA_VPS
```

> **Ubuntu 26.04 "resolute" (Python 3.14):** vários pacotes fixados
> (`numpy`, `pandas`, `lxml`, `pikepdf`) **não têm wheel** para 3.14 e tentam
> compilar do zero — o que falha com
> `Error: Please make sure the libxml2 and libxslt development packages are installed`.
> O instalador já resolve isso: instala as build deps **e** garante um
> **Python 3.12** (do sistema, do apt ou via `uv` com Python standalone em
> `/opt/python`), que é a mesma versão validada no `Dockerfile`.

---

## 2. Instalar (tudo de uma vez)

```bash
# 2.1 sistema + dependências
apt-get update && apt-get install -y git curl ca-certificates

# 2.2 clonar o repositório
cd /root
git clone https://github.com/crcdftv/pdfcompleto.git
cd pdfcompleto

# 2.3 instalar
sudo bash deploy/install.sh
```

O instalador faz tudo: Tesseract (`por`+`eng`), Poppler, nginx, usuário de
sistema `pdfcompleto`, venv Python em `/opt/pdfcompleto`, dados em
`/var/lib/pdfcompleto`, serviço systemd e proxy nginx.

### Opções do instalador

```bash
sudo bash deploy/install.sh
```

| Variável | Padrão | Para quê |
|---|---|---|
| `REPO_URL` | `https://github.com/crcdftv/pdfcompleto.git` | repo (privado → use token) |
| `SERVER_NAME` | `_` | domínio, ex. `pdf.seudominio.com.br` |
| `APP_PORT` | `5000` | porta interna do Flask |
| `DATA_DIR` | `/var/lib/pdfcompleto` | pasta de uploads/resultados |
| `OCR_MAX_WORKERS` | `2` | páginas em paralelo no OCR (menos = menos RAM) |
| `MEMORY_MAX` | *(vazio)* | limite de RAM do serviço, ex. `3G` |
| `PYTHON_VERSION` | `3.12` | versão do Python (3.11–3.13 têm wheels) |

Exemplo com domínio e repo privado:

```bash
export REPO_URL='https://USUARIO:TOKEN@github.com/crcdftv/pdfcompleto.git'
export SERVER_NAME='pdf.seudominio.com.br'
export OCR_MAX_WORKERS=2
sudo bash deploy/install.sh
```

---

## 3. Verificar se está de pé

```bash
curl http://127.0.0.1:5000/health.json
```

Resposta esperada:

```json
{"status":"ok","checks":{"tesseract":{"status":"ok","path":"/usr/bin/tesseract"},
 "pkcs11":{"status":"unavailable"}, ...}}
```

`pkcs11: unavailable` é **normal** — assinatura por token fica só no Windows.

```bash
systemctl status pdfcompleto     # servico
journalctl -u pdfcompleto -f     # logs ao vivo
```

---

## 4. Domínio e HTTPS

```bash
# 4.1 apontar o dominio para a VPS (no painel do registrador)
#     A -> IP_DA_VPS

# 4.2 instalar o certbot
apt-get install -y certbot python3-certbot-nginx

# 4.3 emitir o certificado (ajuste o dominio)
certbot --nginx -d pdf.seudominio.com.br
```

O certbot ajusta o nginx e instala a renovação automática. Teste:

```bash
curl -I https://pdf.seudominio.com.br
```

> **Não esqueça de abrir a porta 80 e 443 no firewall do painel da VPS**
> (e a porta 22 para o SSH). O app **não** fica exposto na 5000: ela só
> escuta em `127.0.0.1` e quem fala com ela é o nginx.

---

## 5. Configuração

Arquivo de ambiente: `/etc/pdfcompleto.env` (não versionar, não compartilhar).

```bash
sudo nano /etc/pdfcompleto.env
```

```ini
SECRET_KEY=<gere um novo>
PDFCOMPLETO_DATA_DIR=/var/lib/pdfcompleto
TESSERACT_CMD=/usr/bin/tesseract
TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata
OCR_MAX_WORKERS=2
```

Depois de mudar: `sudo systemctl restart pdfcompleto`.

---

## 6. Atualizar o sistema

```bash
cd /root/pdfcompleto && sudo git pull
sudo bash deploy/update.sh
```

O `update.sh` atualiza o código, as dependências e reinicia o serviço.

---

## 7. Operação

```bash
systemctl status pdfcompleto      # estado do servico
systemctl restart pdfcompleto     # reiniciar
journalctl -u pdfcompleto -f      # logs em tempo real
journalctl -u pdfcompleto --since "1 hour ago"   # última hora

du -sh /var/lib/pdfcompleto/*     # espaço usado
ls /var/lib/pdfcompleto/uploads   # PDFs enviados
```

### Problemas conhecidos

**`Error: Please make sure the libxml2 and libxslt development packages are installed`**

O Python do sistema (3.14 no Ubuntu 26.04) não tem wheels para os pacotes
fixados e eles tentam compilar. **Solução:** use o instalador atualizado,
que instala as build deps e garante um Python 3.12:

```bash
cd /root/pdfcompleto && sudo git pull && sudo bash deploy/install.sh
```

Se preferir resolver na mão:

```bash
sudo apt-get install -y build-essential pkg-config libxml2-dev libxslt1-dev \
    zlib1g-dev libjpeg-dev libffi-dev libssl-dev
```

**`PermissionError` / `Worker failed to boot` no log**

O serviço roda como o usuário `pdfcompleto` e grava log em
`/var/lib/pdfcompleto/logs`. Verifique a dono/permissão:

```bash
sudo chown -R pdfcompleto:pdfcompleto /var/lib/pdfcompleto
sudo systemctl restart pdfcompleto
```

**`git pull` recusando o repositório (`dubious ownership`)**

```bash
sudo git config --global --add safe.directory /opt/pdfcompleto
```

### Backup

```bash
sudo tar czf /root/pdfcompleto-backup-$(date +%F).tar.gz /var/lib/pdfcompleto
```

### "Servidor caiu depois de um OCR grande"

Sintoma: `journalctl` mostra `Killed` (OOM killer). O PDF era grande e havia
pouca RAM. Aumente o swap e reduza o paralelismo:

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

sudo sed -i 's/^OCR_MAX_WORKERS=.*/OCR_MAX_WORKERS=1/' /etc/pdfcompleto.env
sudo systemctl restart pdfcompleto
```

---

## 8. Alternativa: Docker

Se preferir container em vez de instalação nativa:

```bash
git clone https://github.com/crcdftv/pdfcompleto.git
cd pdfcompleto
docker build -t pdfcompleto .
docker run -d --name pdfcompleto -p 5000:5000 \
  -e SECRET_KEY=$(openssl rand -hex 32) \
  -v pdfcompleto_dados:/data \
  --restart unless-stopped pdfcompleto
```

O `Dockerfile` já instala Tesseract (`por`+`eng`) e Poppler. Para HTTPS, use
nginx ou Caddy como proxy na frente, ou um host com proxy embutido.

---

## 9. Checklist

- [ ] `apt-get update && apt-get install -y git curl ca-certificates`
- [ ] `git clone https://github.com/crcdftv/pdfcompleto.git`
- [ ] `sudo bash deploy/install.sh`
- [ ] `curl http://127.0.0.1:5000/health.json` → `"status":"ok"`
- [ ] domínio apontando para a VPS
- [ ] portas 22/80/443 liberadas no firewall
- [ ] `certbot --nginx -d SEU_DOMINIO`
- [ ] upload de PDF + OCR funcionando no navegador
- [ ] `SECRET_KEY` forte em `/etc/pdfcompleto.env`
- [ ] swap configurado (recomendado em VPS com 1–2 GB)

---

## 10. O que **não** vai para a VPS

| Item | Motivo |
|---|---|
| assinatura por token USB | driver SafeSign é Windows-only |
| `key.pem` / `cert.pem` | segredos — nunca versionar nem copiar |
| PIN do token | lido de `TOKEN_PIN` no ambiente |
| `.flask_session` | bytes das sessões dos usuários |
| PDFs de exemplo | não estão no repositório |

---

**Dúvidas/problemas:** veja `deploy/DEPLOY.md` e os logs com
`journalctl -u pdfcompleto -n 100 --no-pager`.
