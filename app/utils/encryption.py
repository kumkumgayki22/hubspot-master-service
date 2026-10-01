import base64
import os
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from typing import Optional


class Encrypter:
    """
    Fernet-based symmetric encryption utility for sensitive credentials
    stored at rest or in temporary configurations.
    """

    def __init__(self, secret_key: Optional[str] = None):
        key_str = secret_key or os.getenv("ENCRYPTION_SECRET_KEY", "default-fallback-secret-key-32chars")
        
        # Derive a 32-byte url-safe base64 Fernet key using PBKDF2
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"hubspot_master_service_salt",
            iterations=100000,
        )
        fernet_key = base64.urlsafe_b64encode(kdf.derive(key_str.encode()))
        self._fernet = Fernet(fernet_key)

    def encrypt(self, plain_text: str) -> str:
        if not plain_text:
            return ""
        return self._fernet.encrypt(plain_text.encode()).decode()

    def decrypt(self, cipher_text: str) -> str:
        if not cipher_text:
            return ""
        return self._fernet.decrypt(cipher_text.encode()).decode()
