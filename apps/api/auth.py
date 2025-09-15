from typing import Optional
from argon2 import PasswordHasher
from email_validator import validate_email, EmailNotValidError

hasher = PasswordHasher()

def hash_password(password: str) -> str:
    return hasher.hash(password)

def verify_password(password_hash: str, password: str) -> bool:
    try:
        return hasher.verify(password_hash, password)
    except Exception:
        return False

def normalize_email(email: str) -> Optional[str]:
    try:
        v = validate_email(email, allow_smtputf8=True)
        return v.normalized.lower()
    except EmailNotValidError:
        return None