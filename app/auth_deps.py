import os
import jwt
from fastapi import Request, HTTPException, status

from app.security_config import configured_secret, credentials_match

ALGORITHM = "HS256"

async def verify_token(request: Request):
    """Dependency to check JWT token in the Authorization header."""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Missing or invalid token"
        )
    
    token = auth_header.split(" ")[1]
    try:
        payload = jwt.decode(
            token,
            configured_secret("JWT_SECRET"),
            algorithms=[ALGORITHM],
        )
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, 
                detail="Invalid token payload"
            )
        return username
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Token has expired"
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Could not validate credentials"
        )


async def verify_rag_api_key(request: Request):
    """Dependency to check the dedicated API key for RAG endpoints."""
    expected_key = os.getenv("RAG_API_KEY", "").strip()
    if not expected_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RAG API key is not configured",
        )

    provided_key = (request.headers.get("X-API-Key") or "").strip()
    if not provided_key or not credentials_match(provided_key, expected_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid RAG API key",
        )
    return True
