from contextlib import asynccontextmanager

from agents.agent_config import AgentConfig
from agents.agent_factory import AgentFactory
from database.mongo_connection import (
    AgentCatalogConnection,
    ToolCatalogConnection,
)
from decorator.token_validation import validate_token
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from models.api_req import ChatReq, TokenReq, ToolIdsReq
from models.api_res import ServerResponseWrapper, TokenRes
from services.agent_service import get_agents, register_new_agent
from services.chat_service import chat_with_agent
from services.tool_service import (
    add_new_tools_to_agent,
    fetch_tools_by_tool_ids,
    get_all_tools_from_mcp_config,
)
from tools.api import ApiInputSchemaFactory, ApiToolExecutor, ApiValidator
from tools.preconfigured import create_preconfigured_registry
from tools.tool_factory import ToolFactory
from tools.tool_provider import ApiToolProvider, MCPToolProvider
from utils.logger import get_logger
from tools.mcp.mcp_tools_filter import MCPToolFilter
from typing import Optional, List

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
        preconfigured_registry=preconfigured_registry,
        api_provider=api_tool_provider,
        mcp_provider=mcp_tool_provider,
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



router = APIRouter(tags=["agents_and_tools"], lifespan=lifespan)
security = HTTPBearer()


@router.put("/")
@validate_token
async def upsert_agent_config(
    request: Request,
    req: dict,
    collection: AgentCatalogConnection = Depends(get_agent_catalog_collection),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Add a new agent configuration
    payload schema
    ```json
        {
            "_id": Optional[str]
            "name": str
            "description": str
            "system_prompt": str
            "tools": list[str] = []
            "model": Optional[ModelConfig] = None
            "capabilities": list[str] = []
            "enabled": bool = True
            "version": str
            "visibility": Visibility = Field(default_factory=lambda: Visibility.PRIVATE)
            "status": Status = Field(default_factory=lambda: Status.DRAFT)
        }
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


@router.post("/tools/fetch")
@validate_token
async def fetch_tool_configs_by_tool_ids(
    request: Request,
    tool_ids_req: ToolIdsReq,
    tool_catalog_collection: ToolCatalogConnection = Depends(
        get_tool_catalog_collection
    ),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Fetch tools by tools_ids saved in a particular agent config
    """
    user_id = getattr(request.app.state, "id", None)
    tool_ids = tool_ids_req.ids
    logger.info("asdfghjkl")
    tools = await fetch_tools_by_tool_ids(tool_ids, tool_catalog_collection)
    logger.info("qwertyuiop")
    response_data = ServerResponseWrapper(
        data=tools,
        message="Tools fetched successfully",
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
        user_id,
        tool_config,
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
