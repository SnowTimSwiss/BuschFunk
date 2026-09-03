import logging
import secrets

import bcrypt
from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from .models import AdminUser, SetupCode

logger = logging.getLogger("buschfunk.auth")


def _hash(secret: str) -> str:
    return bcrypt.hashpw(secret.encode(), bcrypt.gensalt()).decode()


def _verify(secret: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(secret.encode(), hashed.encode())
    except ValueError:
        return False


def has_admin(db: Session) -> bool:
    return db.query(AdminUser).first() is not None


def ensure_setup_code(db: Session) -> None:
    """Beim Start: solange kein Admin-Passwort gesetzt ist, einen frischen
    Setup-Code erzeugen und laut ins Log schreiben (physischer Zugriff nötig)."""
    if has_admin(db):
        return

    db.query(SetupCode).delete()
    code = f"{secrets.randbelow(1_000_000):06d}"
    db.add(SetupCode(code_hash=_hash(code), used=False))
    db.commit()

    banner = "=" * 48
    logger.warning(banner)
    logger.warning("BuschFunk Setup-Code (einmalig, physischer Zugriff nötig):")
    logger.warning("   %s", code)
    logger.warning("Admin-UI -> 'Admin' -> Setup-Code eingeben, um das Passwort zu setzen.")
    logger.warning(banner)


def verify_setup_code(db: Session, code: str) -> bool:
    row = db.query(SetupCode).filter(SetupCode.used.is_(False)).first()
    if row is None:
        return False
    return _verify(code, row.code_hash)


def consume_setup_code(db: Session, code: str) -> bool:
    row = db.query(SetupCode).filter(SetupCode.used.is_(False)).first()
    if row is None or not _verify(code, row.code_hash):
        return False
    row.used = True
    db.commit()
    return True


def set_admin_password(db: Session, password: str) -> AdminUser:
    if has_admin(db):
        raise HTTPException(status.HTTP_409_CONFLICT, "Admin-Passwort bereits gesetzt")
    admin = AdminUser(password_hash=_hash(password))
    db.add(admin)
    db.commit()
    return admin


def verify_login(db: Session, password: str) -> bool:
    admin = db.query(AdminUser).first()
    if admin is None:
        return False
    return _verify(password, admin.password_hash)


def require_admin(request: Request) -> None:
    if not request.session.get("admin"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Nicht angemeldet")
