from OpenSSL import crypto
import ipaddress
import socket

# Descobre IP local automaticamente
hostname = socket.gethostname()
local_ip = socket.gethostbyname(hostname)
print(f"🔍 IP detectado: {local_ip}")

# Cria chave RSA
key = crypto.PKey()
key.generate_key(crypto.TYPE_RSA, 4096)

# Cria certificado X.509
cert = crypto.X509()
cert.get_subject().C = "BR"
cert.get_subject().ST = "Distrito Federal"
cert.get_subject().L = "Brasilia"
cert.get_subject().O = "Servidor Flask Local"
cert.get_subject().OU = "Desenvolvimento"
cert.get_subject().CN = "localhost"
cert.set_serial_number(1001)
cert.gmtime_adj_notBefore(0)
cert.gmtime_adj_notAfter(365 * 24 * 60 * 60)
cert.set_issuer(cert.get_subject())
cert.set_pubkey(key)

# 🧩 Adiciona Subject Alternative Names (SAN)
san_list = [
    f"DNS:localhost",
    f"IP:{local_ip}",
    "IP:127.0.0.1"
]
cert.add_extensions([
    crypto.X509Extension(
        b"subjectAltName",
        False,
        ", ".join(san_list).encode()
    )
])

# Assina o certificado
cert.sign(key, 'sha256')

# Salva arquivos PEM
with open("cert.pem", "wb") as f:
    f.write(crypto.dump_certificate(crypto.FILETYPE_PEM, cert))
with open("key.pem", "wb") as f:
    f.write(crypto.dump_privatekey(crypto.FILETYPE_PEM, key))

print(f"✅ Certificado criado para localhost e {local_ip}")
