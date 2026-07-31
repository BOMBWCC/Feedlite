import os
import jwt
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from app.auth_deps import ALGORITHM
from app.security_config import configured_secret, credentials_match
from app.login_throttle import LoginThrottle

router = APIRouter(prefix="/api/auth", tags=["auth"])
login_throttle = LoginThrottle()

def _access_token_expire_days() -> int:
    try:
        days = int(os.getenv("ACCESS_TOKEN_EXPIRE_DAYS", "30"))
    except ValueError:
        return 30
    return max(1, days)

class LoginRequest(BaseModel):
    username: str
    password: str

def create_access_token(data: dict, expires_delta: timedelta):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        configured_secret("JWT_SECRET"),
        algorithm=ALGORITHM,
    )
    return encoded_jwt

@router.post("/login")
async def login(req: LoginRequest, request: Request = None):
    client_key = request.client.host if request and request.client else "unknown"
    if login_throttle.is_blocked(client_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again later.",
            headers={"Retry-After": str(login_throttle.window_seconds)},
        )

    env_user = os.getenv("ADMIN_USERNAME", "admin")
    env_pass = configured_secret("ADMIN_PASSWORD")

    if (
        credentials_match(req.username, env_user)
        and credentials_match(req.password, env_pass)
    ):
        login_throttle.record_success(client_key)
        access_token = create_access_token(
            data={"sub": req.username}, 
            expires_delta=timedelta(days=_access_token_expire_days())
        )
        return {"access_token": access_token, "token_type": "bearer"}
    
    login_throttle.record_failure(client_key)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect username or password",
        headers={"WWW-Authenticate": "Bearer"},
    )
