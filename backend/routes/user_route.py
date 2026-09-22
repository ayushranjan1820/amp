from contextlib import asynccontextmanager
from fastapi import APIRouter, Depends, FastAPI, Request, status
from fastapi.responses import JSONResponse
from pymongo.asynchronous.collection import AsyncCollection

from database import UserProfileCollection
from models.api_req import RegisterUserReq, LoginUserReq
from models.api_res import ServerResponseWrapper, LoginUserRes
from services.user_service import (
    register_new_user as register_user_service,
    login_user as login_user_service,
)
from utils.logger import get_logger


logger = get_logger("routes.user")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Route-level lifespan context manager that initializes UserProfileCollection
    and attaches it to app.state.user_profile_collection during app startup.
    """
    logger.info("Initializing UserProfileCollection at route level...")
    app.state.user_profile_collection = UserProfileCollection(
        collection_name="user_profile"
    )

    yield
    logger.info("Closing UserProfileCollection at route level...")


def get_user_profile_collection(request: Request) -> UserProfileCollection:
    """
    FastAPI Dependency Provider retrieving the initialized UserProfileCollection from request.app.state.
    """
    return request.app.state.user_profile_collection


router = APIRouter(tags=["user"], lifespan=lifespan)


@router.post("/register", response_class=JSONResponse)
async def register_new_user(
    req: RegisterUserReq,
    collection: UserProfileCollection = Depends(get_user_profile_collection),
):
    """
    Registers a new user into the system using MongoDB dependency injection initialized via router lifespan.
    """
    logger.info("HTTP POST /register called for email: %s", req.email)

    user_res = await register_user_service(req, collection)
    response_data = ServerResponseWrapper(
        data=user_res.model_dump(),
        message="User registered successfully",
        status_code=status.HTTP_201_CREATED,
    )
    logger.info(
        "Registration successful for email: %s, user_id: %s",
        req.email,
        user_res.user_id,
    )
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=response_data.model_dump(mode="json"),
    )


@router.post("/login")
async def login_user(
    req: LoginUserReq,
    collection: UserProfileCollection = Depends(get_user_profile_collection),
):
    user_res = await login_user_service(req, collection)
    response_data = ServerResponseWrapper(
        data=user_res.model_dump(),
        message="User logged in successfully",
        status_code=status.HTTP_200_OK,
    )
    logger.info(
        "Login successful for email: %s",
        req.email,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=response_data.model_dump(mode="json"),
    )
