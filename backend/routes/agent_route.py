from fastapi import APIRouter, Request, Depends, FastAPI, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from utils.logger import get_logger
from contextlib import asynccontextmanager
from tools.preconfigured import create_preconfigured_registry
from tools.tool_factory import ToolFactory
from agents.agent_factory import AgentFactory
from agents.agent_config import AgentConfig
from dotenv import load_dotenv
from decorator.token_validation import validate_token
from database.mongo_connection import AgentCatalogConnection
from services.agent_service import register_new_agent, edit_available_agent, get_agents, add_new_tools_to_agent
from services.chat_service import chat_with_agent
from models.api_res import ServerResponseWrapper
from models.api_req import NewAgentReq, ChatReq
from tools.api import ApiValidator, ApiToolExecutor, ApiInputSchemaFactory
from tools.tool_provider import ApiToolProvider

load_dotenv()

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Route-level lifespan context manager that initializes AgentCatalogConnection
    and attaches it to app.state.agent_catalog_collection during app startup.
    """
    logger.info("Initializing AgentCatalogConnection at route level...")
    app.state.agent_catalog_collection = AgentCatalogConnection(
        collection_name="agent_catalog"
    )

    # ----- Preconfigured Tools -----
    preconfigured_registry = (
        create_preconfigured_registry()
    )

    # ----- API Tools -----
    api_validator = ApiValidator()
    api_executor = ApiToolExecutor(api_validator)
    api_schema_factory = ApiInputSchemaFactory()
    api_tool_provider = ApiToolProvider(api_executor, api_schema_factory)

    # ----- Common ToolFactory -----
    tool_factory = ToolFactory(
        preconfigured_registry=preconfigured_registry,
        api_provider=api_tool_provider
    )

    agent_factory = AgentFactory(
        tool_factory=tool_factory,
    )

    # ----- Application State -----
    app.state.tool_factory = tool_factory
    app.state.agent_factory = agent_factory

    yield
    logger.info("Closing AgentCatalogConnection at route level...")


def get_agent_catalog_collection(request: Request) -> AgentCatalogConnection:
    """
    FastAPI Dependency Provider retrieving the initialized AgentCatalogConnection from request.app.state.
    """
    return request.app.state.agent_catalog_collection


router = APIRouter(tags=["agents"], lifespan=lifespan)
security = HTTPBearer()


@router.post("/create")
@validate_token
async def create_agent(
    request: Request,
    req: NewAgentReq,
    collection: AgentCatalogConnection = Depends(get_agent_catalog_collection),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user_email = getattr(request.app.state, "email", None)
    user_id = getattr(request.app.state, "id", None)

    new_agent = await register_new_agent(user_id, req, collection)
    response_data = ServerResponseWrapper(
        data=new_agent.model_dump(),
        message="Agent created successfully",
        status_code=status.HTTP_201_CREATED,
    )
    logger.info(
        "New agent '%s' registered with id: %s for user: %s",
        new_agent.name,
        new_agent.agent_id,
        user_email,
    )
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=response_data.model_dump(mode="json"),
    )


@router.put("/edit/{agent_id}")
@validate_token
async def edit_agent(
    request: Request,
    agent_id: str,
    req: NewAgentReq,
    collection: AgentCatalogConnection = Depends(get_agent_catalog_collection),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user_email = getattr(request.app.state, "email", None)
    user_id = getattr(request.app.state, "id", None)

    updated_agent = await edit_available_agent(user_id, agent_id, req, collection)
    if updated_agent is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=ServerResponseWrapper(
                status_code=status.HTTP_404_NOT_FOUND,
                error="Agent not found",
            ).model_dump(mode="json"),
        )

    response_data = ServerResponseWrapper(
        data=updated_agent.model_dump(),
        message="Available tools updated successfully",
        status_code=status.HTTP_200_OK,
    )
    logger.info(
        "Available tools updated for agent '%s' with id: %s for user: %s",
        updated_agent.name,
        updated_agent.agent_id,
        user_email,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=response_data.model_dump(mode="json"),
    )


@router.patch("/add-tools/{agent_id}")
@validate_token
async def add_tools(
    request: Request,
    agent_id: str,
    tool_config: dict,
    collection: AgentCatalogConnection = Depends(get_agent_catalog_collection),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user_id = getattr(request.app.state, "id", None)
    updated_agent = await add_new_tools_to_agent(agent_id, tool_config, user_id, collection)
    response_data = ServerResponseWrapper(
        data=updated_agent.model_dump(),
        message="Tools added successfully",
        status_code=status.HTTP_200_OK,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=response_data.model_dump(mode="json"),
    )


@router.post("/chat/{agent_id}")
@validate_token
async def chat(
    request: Request,
    agent_id: str,
    req: ChatReq,
    collection: AgentCatalogConnection = Depends(get_agent_catalog_collection),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user_id = getattr(request.app.state, "id", None)
    agent_factory: AgentFactory = request.app.state.agent_factory
    agent_response = await chat_with_agent(agent_id, user_id, req.message, agent_factory, collection)
    response_data = ServerResponseWrapper(
        data=agent_response,
        message="Chat response",
        status_code=status.HTTP_200_OK,
    )
    return JSONResponse(
        content=response_data.model_dump(mode="json"),
        status_code=status.HTTP_200_OK
    )

@router.get("/fetch")
@validate_token
async def fetch_all_agents(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    collection: AgentCatalogConnection = Depends(get_agent_catalog_collection)
):
    user_id = getattr(request.app.state, "id", None)
    available_agents = await get_agents(user_id, collection)
    response_data = ServerResponseWrapper(
        data = available_agents,
        message = "Available agents fetched successfully",
        status_code = status.HTTP_200_OK,
    )
    logger.info(
        "%s agents found for user: %s", len(available_agents), user_id,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=response_data.model_dump(mode="json"),
    )
    
