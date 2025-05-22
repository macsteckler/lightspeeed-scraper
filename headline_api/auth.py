"""Authentication utilities for the headline content scraper API."""
import os
from jose import jwt
from jose.exceptions import JWTError, ExpiredSignatureError, JWTClaimsError

# JWT configuration - in a real app, these would be in env vars
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key")  # Should be properly set in production
JWT_ALGORITHM = "HS256"

def verify_token(token: str) -> dict:
    """
    Verify the JWT token.
    
    Args:
        token: The JWT token to verify
        
    Returns:
        The decoded token payload
        
    Raises:
        ValueError: If the token is invalid
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except ExpiredSignatureError:
        raise ValueError("Token has expired")
    except JWTClaimsError:
        raise ValueError("Invalid token claims")
    except JWTError:
        raise ValueError("Invalid token") 