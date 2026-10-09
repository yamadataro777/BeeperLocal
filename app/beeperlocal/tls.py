"""Use macOS trust roots, independently of a developer's Python/OpenSSL install."""
import ssl
import sys


def client_context():
    if sys.platform == "darwin":
        import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return ssl.create_default_context()
