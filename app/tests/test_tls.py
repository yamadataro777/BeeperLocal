"""TLS verification must work without developer CA paths and never trust a self-signed peer."""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import socket
import ssl
import tempfile
import threading
import unittest
from unittest.mock import patch
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from beeperlocal.tls import client_context


class TLSTests(unittest.TestCase):
    def test_missing_developer_certificate_paths_keep_verification_required(self):
        with patch.dict(os.environ, {'SSL_CERT_FILE': '/nonexistent/fixture-ca', 'SSL_CERT_DIR': '/nonexistent/fixture-certs'}):
            context = client_context()
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)

    def test_untrusted_server_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
            now = datetime.now(timezone.utc)
            cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
                .not_valid_after(now + timedelta(hours=1)).add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]), False)
                .sign(key, hashes.SHA256()))
            cert_path, key_path = Path(directory) / 'certificate.pem', Path(directory) / 'fixture-key.pem'
            cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            server_context.load_cert_chain(cert_path, key_path)
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0)); listener.listen(1); listener.settimeout(3)
                def server():
                    try:
                        conn, _ = listener.accept()
                        with conn:
                            with server_context.wrap_socket(conn, server_side=True): pass
                    except (ssl.SSLError, OSError): pass
                thread = threading.Thread(target=server, daemon=True)
                thread.start()
                with socket.create_connection(listener.getsockname(), timeout=3) as conn:
                    with self.assertRaises(ssl.SSLCertVerificationError):
                        client_context().wrap_socket(conn, server_hostname='localhost')
                thread.join(3)
                self.assertFalse(thread.is_alive())
