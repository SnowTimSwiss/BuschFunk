from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .. import auth
from ..db import get_db
from ..schemas import Login, SetPassword, SetupCodeVerify

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/status")
def status_(request: Request, db: Session = Depends(get_db)):
    return {
        "setup_required": not auth.has_admin(db),
        "logged_in": bool(request.session.get("admin")),
    }


@router.post("/verify-setup-code")
def verify_setup_code(body: SetupCodeVerify, db: Session = Depends(get_db)):
    return {"valid": auth.verify_setup_code(db, body.code)}


@router.post("/set-password")
def set_password(body: SetPassword, request: Request, db: Session = Depends(get_db)):
    if auth.has_admin(db):
        raise HTTPException(status.HTTP_409_CONFLICT, "Admin-Passwort bereits gesetzt")
    if len(body.password) < 8:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Passwort muss mindestens 8 Zeichen haben")
    if not auth.consume_setup_code(db, body.code):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Setup-Code ungültig oder bereits verwendet")
    auth.set_admin_password(db, body.password)
    request.session["admin"] = True
    return {"ok": True}


@router.post("/login")
def login(body: Login, request: Request, db: Session = Depends(get_db)):
    if not auth.verify_login(db, body.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Falsches Passwort")
    request.session["admin"] = True
    return {"ok": True}


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}
