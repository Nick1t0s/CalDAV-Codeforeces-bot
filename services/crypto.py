from cryptography.fernet import Fernet, InvalidToken

from config import SECRET_KEY

_FERNET: Fernet | None = None


def _get_fernet() -> Fernet:
    global _FERNET
    if _FERNET is None:
        if not SECRET_KEY:
            raise RuntimeError("SECRET_KEY не задан: export SECRET_KEY=... (см. .env.example)")
        _FERNET = Fernet(SECRET_KEY.encode())
    return _FERNET


def encrypt(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, ValueError):
        return ciphertext
