import base64
import hashlib
import logging
from datetime import UTC, datetime, timedelta

import jwt
from cryptography.fernet import Fernet
from jwt import InvalidTokenError
from passlib.context import CryptContext

from app.config import settings

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Derive a deterministic Fernet key from SECRET_KEY (32 url-safe base64 bytes)
_fernet_key = base64.urlsafe_b64encode(
    hashlib.sha256(settings.SECRET_KEY.encode()).digest()
)
fernet = Fernet(_fernet_key)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(UTC) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm="HS256")


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
    except InvalidTokenError:
        return None


def create_refresh_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    to_encode.update({"type": "refresh"})
    expire = datetime.now(UTC) + (
        expires_delta or timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm="HS256")


def decode_refresh_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        if payload.get("type") != "refresh":
            return None
        return payload
    except InvalidTokenError:
        return None


def encrypt_api_key(api_key: str) -> str:
    return fernet.encrypt(api_key.encode()).decode()


def decrypt_api_key(encrypted_key: str) -> str:
    """Decrypt a Fernet-encrypted API key.

    Returns the plaintext key, or an empty string if decryption fails
    (e.g. because the ``SECRET_KEY`` changed since encryption).
    """
    try:
        return fernet.decrypt(encrypted_key.encode()).decode()
    except Exception:
        logger.warning(
            "Failed to decrypt API key — key may have been "
            "encrypted with a different SECRET_KEY; "
            "falling back to environment variable"
        )
        return ""
