from contextlib import asynccontextmanager

from agents.agent_config import AgentConfig
from agents.agent_factory import AgentFactory
from database.mongo_connection import (
    AgentCatalogConnection,
    TokenCatalogConnection,
    ToolCatalogConnection,
)
from decorator.token_validation import validate_token
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from models.api_req import ChatReq, NewAgentReq, TokenReq, ModelReq
from models.api_res import ServerResponseWrapper, TokenRes
from services.agent_service import edit_available_agent, get_agents, register_new_agent
from services.chat_service import chat_with_agent
from services.tool_service import (
    add_new_token,
    add_new_tools_to_agent,
    fetch_tools_by_tool_ids,
    get_tokens_by_user_id,
    get_all_tools_from_mcp_config
)
from tools.api import ApiInputSchemaFactory, ApiToolExecutor, ApiValidator
from tools.preconfigured import create_preconfigured_registry
from tools.tool_factory import ToolFactory
from tools.tool_provider import ApiToolProvider, MCPToolProvider
from utils.logger import get_logger
from tools.mcp.mcp_tools_filter import MCPToolFilter

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
    app.state.tool_catalog_collection = ToolCatalogConnection(
        collection_name="tool_catalog"
    )

    app.state.token_catalog_connection = TokenCatalogConnection(
        collection_name="token_catalog"
    )

    # ----- Preconfigured Tools -----
    preconfigured_registry = create_preconfigured_registry()

    # ----- API Tools -----
    api_validator = ApiValidator()
    api_executor = ApiToolExecutor(api_validator)
    api_schema_factory = ApiInputSchemaFactory()
    api_tool_provider = ApiToolProvider(api_executor, api_schema_factory)

    # ----- MCP Tools -----
    tool_filter = MCPToolFilter()
    mcp_tool_provider = MCPToolProvider(tool_filter)

    # ----- Common ToolFactory -----
    tool_factory = ToolFactory(
        preconfigured_registry=preconfigured_registry, api_provider=api_tool_provider, mcp_provider=mcp_tool_provider
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


def get_tool_catalog_collection(request: Request) -> ToolCatalogConnection:
    """
    FastAPI Dependency Provider retrieving the initialized ToolCatalogConnection from request.app.state
    """
    return request.app.state.tool_catalog_collection


def get_token_catalog_collection(request: Request) -> TokenCatalogConnection:
    """
    FastAPI Dependency Provider retrieving the initialized TokenCatalogConnection from request.app.state
    """
    return request.app.state.token_catalog_connection


router = APIRouter(tags=["agents_tools_tokens"], lifespan=lifespan)
security = HTTPBearer()


@router.post("/")
@validate_token
async def create_agent(
    request: Request,
    req: NewAgentReq,
    collection: AgentCatalogConnection = Depends(get_agent_catalog_collection),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Add a new agent configuration
    """
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
    """
    Edit an existing agent config
    """
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


@router.post("/chat/{agent_id}")
@validate_token
async def chat(
    request: Request,
    agent_id: str,
    req: ChatReq,
    agent_catalog_collection: AgentCatalogConnection = Depends(
        get_agent_catalog_collection
    ),
    tool_catalog_collection: ToolCatalogConnection = Depends(
        get_tool_catalog_collection
    ),
    token_catalog_collection: TokenCatalogConnection = Depends(
        get_token_catalog_collection
    ),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Chat with an agent
    """
    user_id = getattr(request.app.state, "id", None)
    agent_factory: AgentFactory = request.app.state.agent_factory
    agent_response = await chat_with_agent(
        agent_id,
        user_id,
        req.message,
        agent_factory,
        agent_catalog_collection,
        tool_catalog_collection,
        token_catalog_collection,
    )
    response_data = ServerResponseWrapper(
        data=agent_response,
        message="Chat response",
        status_code=status.HTTP_200_OK,
    )
    return JSONResponse(
        content=response_data.model_dump(mode="json"), status_code=status.HTTP_200_OK
    )


@router.get("/")
@validate_token
async def fetch_all_agents(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    collection: AgentCatalogConnection = Depends(get_agent_catalog_collection),
):
    """
    Fetch all available agents of an user
    """
    user_id = getattr(request.app.state, "id", None)
    available_agents = await get_agents(user_id, collection)
    response_data = ServerResponseWrapper(
        data=available_agents,
        message="Available agents fetched successfully",
        status_code=status.HTTP_200_OK,
    )
    logger.info(
        "%s agents found for user: %s",
        len(available_agents),
        user_id,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=response_data.model_dump(mode="json"),
    )


@router.post("/model/{agent_id}")
@validate_token
async def add_model_to_an_agent(
    request: Request,
    agent_id: str,
    model_req: ModelReq,
    agent_catalog_collection: AgentCatalogConnection = Depends(
        get_agent_catalog_collection
    ),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Add new tool(s) to an existing agent
    """
    user_id = getattr(request.app.state, "id", None)
    updated_agent = await add_new_tools_to_agent(
        agent_id,
        tool_config,
        user_id,
        agent_catalog_collection,
        tool_catalog_collection,
    )
    response_data = ServerResponseWrapper(
        data=updated_agent.model_dump(),
        message="Tools added successfully",
        status_code=status.HTTP_200_OK,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=response_data.model_dump(mode="json"),
    )


@router.post("/tools/{agent_id}")
@validate_token
async def add_tools_to_an_agent(
    request: Request,
    agent_id: str,
    tool_config: list[dict],
    agent_catalog_collection: AgentCatalogConnection = Depends(
        get_agent_catalog_collection
    ),
    tool_catalog_collection: ToolCatalogConnection = Depends(
        get_tool_catalog_collection
    ),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Add new tool(s) to an existing agent
    """
    user_id = getattr(request.app.state, "id", None)
    updated_agent = await add_new_tools_to_agent(
        agent_id,
        tool_config,
        user_id,
        agent_catalog_collection,
        tool_catalog_collection,
    )
    response_data = ServerResponseWrapper(
        data=updated_agent.model_dump(),
        message="Tools added successfully",
        status_code=status.HTTP_200_OK,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=response_data.model_dump(mode="json"),
    )


@router.post("/tools/fetch")
@validate_token
async def fetch_tool_configs_by_tool_ids(
    request: Request,
    tool_ids: list[str],
    tool_catalog_collection: ToolCatalogConnection = Depends(
        get_tool_catalog_collection
    ),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Fetch tools by tools_ids saved in a particular agent config
    """
    user_id = getattr(request.app.state, "id", None)
    tools = await fetch_tools_by_tool_ids(tool_ids, tool_catalog_collection)
    response_data = ServerResponseWrapper(
        data=tools,
        message="Tools fetched successfully",
        status_code=status.HTTP_200_OK,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=response_data.model_dump(mode="json"),
    )


@router.post("/tokens")
@validate_token
async def add_credentials(
    request: Request,
    token_config: TokenReq,
    token_catalog_collection: TokenCatalogConnection = Depends(
        get_token_catalog_collection
    ),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user_id = getattr(request.app.state, "id", None)
    updated_agent = await add_new_token(token_config, user_id, token_catalog_collection)
    response_data = ServerResponseWrapper(
        data=updated_agent.model_dump(),
        message="Credentials added successfully",
        status_code=status.HTTP_200_OK,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=response_data.model_dump(mode="json"),
    )


@router.get("/tokens")
@validate_token
async def fetch_tokens_of_user(
    request: Request,
    token_catalog_collection: TokenCatalogConnection = Depends(
        get_token_catalog_collection
    ),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    user_id = getattr(request.app.state, "id", None)
    tokens = await get_tokens_by_user_id(user_id, token_catalog_collection)
    response_data = ServerResponseWrapper(
        data=tokens,
        message=f"Tokens fetched successfully for user id: {user_id}",
        status_code=status.HTTP_200_OK,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=response_data.model_dump(mode="json"),
    )


@router.post("/tools-from-mcp")
@validate_token
async def get_tools_from_config(
    request: Request,
    mcp_config: dict,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Fetch tools from MCP config
    """
    tools = await get_all_tools_from_mcp_config(mcp_config)
    response_data = ServerResponseWrapper(
        data=tools,
        message="All available tools from MCP config fetched successfully",
        status_code=status.HTTP_200_OK,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=response_data.model_dump(mode="json"),
    )