import os
from functools import wraps
from typing import Callable, Any
import jwt
from fastapi import Request, HTTPException, status
from utils.logger import get_logger

logger = get_logger("decorator.token_validation")


def validate_token(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Asynchronous decorator for FastAPI route handlers that validates a JWT token
    from the request headers/query parameters and attaches the decoded 'email' and 'id'
    to the request state (request.state & request.app.state).
    """

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        # Locate FastAPI Request instance from kwargs or positional args
        request: Request | None = kwargs.get("request")
        if request is None:
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break

        if not request:
            logger.error(
                "Request object not found in arguments for decorated handler '%s'",
                func.__name__,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Request object required in endpoint parameters for token validation.",
            )

        # Extract authorization token from headers
        auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
        token: str | None = None

        if auth_header:
            parts = auth_header.split()
            if len(parts) == 2 and parts[0].lower() == "bearer":
                token = parts[1]
            elif len(parts) == 1:
                token = parts[0]

        # Fallback check for direct 'token' header or query parameter
        if not token:
            token = request.headers.get("token") or request.query_params.get("token")

        if not token:
            logger.warning("Token validation failed: Authorization token not provided.")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authorization token is missing.",
            )

        # Fetch JWT secrets from environment variables
        jwt_secret = os.getenv("JWT_SECRET_KEY")
        jwt_algorithm = os.getenv("JWT_ALGORITHM")

        try:
            payload = jwt.decode(token, jwt_secret, algorithms=[jwt_algorithm])
        except jwt.ExpiredSignatureError:
            logger.warning("Token validation failed: Token has expired.")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired.",
            )
        except jwt.InvalidTokenError as err:
            logger.warning("Token validation failed: Invalid token (%s)", err)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authorization token.",
            )

        # Extract user email and id claims from token payload
        user_email = payload.get("sub") or payload.get("email") or payload.get("user_email")
        user_id = payload.get("id") or payload.get("user_id") or payload.get("_id")

        if not user_email or not user_id:
            logger.warning("Token payload missing required claims: email='%s', id='%s'", user_email, user_id)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token payload is incomplete or invalid.",
            )

        # Set email and id in request state and app state
        request.state.email = user_email
        request.state.id = user_id

        request.app.state.email = user_email
        request.app.state.id = user_id

        logger.info(
            "Successfully validated token for email='%s', id='%s'",
            user_email,
            user_id,
        )

        return await func(*args, **kwargs)

    return wrapper


# Alias for validate_token
check_token = validate_token
