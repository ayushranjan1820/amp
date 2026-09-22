import bcrypt
from pymongo.asynchronous.collection import AsyncCollection
from datetime import datetime, timedelta

from models.api_req import RegisterUserReq
from models.api_res import RegisterUserRes
from utils.logger import get_logger
from database.mongo_connection import UserProfileCollection
from database.schema import UserProfile
import jwt
from models.api_req import LoginUserReq
from models.api_res import LoginUserRes
import os

logger = get_logger("services.user")


async def register_new_user(
    req: RegisterUserReq, collection: UserProfileCollection
) -> RegisterUserRes:
    """
    Registers a new user by hashing their password with bcrypt and saving the user details
    in the MongoDB user_profile collection.
    """
    logger.info("Received request to register user: %s (name: %s)", req.email, req.name)

    # Check if user already exists with the given email
    logger.debug("Checking for existing user with email: %s", req.email)
    existing_user = await collection.find_existing_user(req.email)
    if existing_user:
        logger.warning(
            "Registration attempt failed: User with email '%s' already exists.",
            req.email,
        )
        raise ValueError(f"User with email '{req.email}' already exists.")

    # Hash password using bcrypt
    logger.debug("Hashing password using bcrypt for user: %s", req.email)
    hashed_password = bcrypt.hashpw(
        req.password.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")

    # Prepare document for MongoDB user_profile collection
    new_user = UserProfile(
        name=req.name,
        email=req.email,
        password=hashed_password,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    # Store user in collection
    logger.debug("Inserting new user document for: %s", req.email)
    result = await collection.register_new_user(new_user)
    logger.info(
        "Successfully registered user '%s' with MongoDB ID: %s",
        req.email,
        result.inserted_id,
    )

    return RegisterUserRes(
        user_id=str(result.inserted_id),
        user_name=req.name,
        user_email=req.email,
    )


async def login_user(
    req: LoginUserReq, collection: UserProfileCollection
) -> LoginUserRes:
    """
    Login a existing user and return access token.
    """
    # Check user exists
    existing_user = await collection.find_existing_user(req.email)

    if not existing_user:
        raise ValueError("User not found.")

    # check password
    if not bcrypt.checkpw(
        req.password.encode("utf-8"), existing_user["password"].encode("utf-8")
    ):
        raise ValueError("Invalid password.")
    
    current_time = datetime.now()

    # generate access token
    claim = {
        "id": str(existing_user["_id"]),
        "name": existing_user["name"],
        "sub": existing_user["email"],
        "iat": current_time,
        "exp": current_time + timedelta(hours=int(os.getenv("JWT_EXPIRY_HOURS"))),
        "iss": "backend",
    }

    token = await _generate_token(claim)
    return LoginUserRes(
        token=token
    )


async def _generate_token(info: dict):

    token = jwt.encode(
        payload=info,
        key=os.getenv("JWT_SECRET_KEY"),
        algorithm=os.getenv("JWT_ALGORITHM"),
    )
    return token
