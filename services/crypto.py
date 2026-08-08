from cryptography.fernet import Fernet, InvalidToken

from config import SECRET_KEY

_ENCRYPTION_ENABLED = bool(SECRET_KEY)
_FERNET: Fernet | None = None


def _get_fernet() -> Fernet | None:
    global _FERNET
    if _ENCRYPTION_ENABLED and _FERNET is None:
        _FERNET = Fernet(SECRET_KEY.encode())
    return _FERNET


def encryption_enabled() -> bool:
    return _ENCRYPTION_ENABLED


def encrypt(plaintext: str) -> str:
    fernet = _get_fernet()
    if fernet is None:
        return plaintext
    return fernet.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    fernet = _get_fernet()
    if fernet is None:
        return ciphertext
    try:
        return fernet.decrypt(ciphertext.encode()).decode()
    except (InvalidToken, ValueError):
        return ciphertext
