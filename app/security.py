"""
Password hashing helpers.

Uses bcrypt via passlib. bcrypt has a hard 72-byte limit on the input, so we
truncate defensively (standard practice) to stay compatible across versions.
No plaintext passwords are ever stored — only hashes.
"""
from passlib.context import CryptContext

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__truncate_error=False)


def hash_password(password: str) -> str:
    # bcrypt only considers the first 72 bytes; truncate to avoid version errors.
    return _pwd.hash(password[:72])


def verify_password(password: str, hashed: str) -> bool:
    return _pwd.verify(password[:72], hashed)
