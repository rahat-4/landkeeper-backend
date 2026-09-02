from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _get_fernet():
    return Fernet(settings.STRIPE_TOKEN_ENCRYPTION_KEY.encode())


def encrypt_token(plain_text: str) -> str:
    if not plain_text:
        return ""
    return _get_fernet().encrypt(plain_text.encode()).decode()


def decrypt_token(encrypted_text: str) -> str:
    if not encrypted_text:
        return ""
    try:
        return _get_fernet().decrypt(encrypted_text.encode()).decode()
    except InvalidToken:
        raise ValueError("Could not decrypt token — key mismatch or corrupted data")
