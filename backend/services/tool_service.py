from datetime import datetime
from pathlib import Path

from fastapi import UploadFile
from database.mongo_connection import (
    AgentCatalogConnection,
    ToolCatalogConnection,
)
from database.schema import AgentCatalog
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from models.api_req import TokenReq, ToolReq
from models.api_res import AgentRes, FileUploadRes, MCPToolRes, TokenRes
from pydantic import TypeAdapter
from tools.tool_config import ToolConfig
from utils.logger import get_logger
from errors.global_exception_handler import AgentMartException
from tools.tool_config import ToolType, EmbeddingModelProvider, ToolConfig
from services.rag_ingestion_service import ingest_document
from tools.rag.vector_store import VectorStore, VectorStoreFactory

logger = get_logger(__name__)

BLOB_DIR = Path(__file__).resolve().parent.parent / "blob"


async def add_new_tools_to_agent(
    agent_id: str,
    user_id: str,
    tool_config: ToolReq,
    agent_catalog_collection: AgentCatalogConnection,
    tool_catalog_collection: ToolCatalogConnection,
) -> AgentRes:
    """
    Add new tool(s) to an existing agent
    Args:
        agent_id (str): unique id of the agent config
        tool_id (str): unique id of the tool config
        user_id: unique id of the user
        tool_config (list[dict]): new tool config(s) to add in agent config
        agent_catalog_collection (AgentCatalogConnection): Mongo connection for agent_catalog collection
        tool_catalog_collection (ToolCatalogConnection): Mongo connection for tool_catalog collection
    Returns:
        AgentRes: Agent response
    """
    agent_config = await agent_catalog_collection.get_agent_config(agent_id)
    tool_config = tool_config.tool[0]
    if not agent_config:
        raise AgentMartException("Agent not found", 404)

    # Add tool config
    if tool_config.tool_type == ToolType.RAG:
        # initialize embedding model based on the provider
        embedding_config = tool_config.embedding_model_config
        rag_advanced_config = tool_config.rag_advanced_config
        vector_store = VectorStoreFactory.get_vector_store(
            vector_store_type=tool_config.vector_db_config.vector_db_provider,
            vector_db_config=tool_config.vector_db_config,
            embedding_config=embedding_config,
            advanced_config=rag_advanced_config,
        )
        await ingest_document(
            vector_store=vector_store,
            document_path=tool_config.document_path,
            rag_advanced_config=rag_advanced_config,
        )

    new_tool = await tool_catalog_collection.add_new_tool(tool_config.model_dump())
    new_tool_id = str(new_tool.inserted_id)

    # Add new tool ids into agent catalog
    agent_config["updated_at"] = datetime.now()
    agent_config["updated_by"] = user_id
    agent_config["tools"] = agent_config.get("tools", []) + [new_tool_id]
    updated_agent_config = await agent_catalog_collection.update_agent_config(
        agent_id, agent_config
    )
    updated_agent_config["_id"] = str(updated_agent_config["_id"])
    return AgentRes(**updated_agent_config)


async def fetch_tools_by_tool_ids(
    tool_ids: list[str],
    tool_catalog_collection: ToolCatalogConnection,
) -> list[ToolConfig]:
    """
    Fetch the tool configs based on the tool id(s)
    Args:
        tool_ids (list[str]): list of tool ids to fetch
        tool_catalog_collection (ToolCatalogConnection): Mongo connection for tool_catalog collection
    Returns:
        list[ToolConfig]: list of ToolConfig
    """
    result = await tool_catalog_collection.get_all_tool_configs(tool_ids)
    for tool in result:
        if "_id" in tool:
            tool["tool_id"] = str(tool["_id"])
    return [TypeAdapter(ToolConfig).validate_python(tool) for tool in result]


async def get_all_tools_from_mcp_config(mcp_config: dict) -> list[MCPToolRes]:
    """
    Fetch all tools from MCP config
    Args:
        mcp_config (dict): MCP config
    Returns:
        list[dict[str, str]]: List of tool names and descriptions
    """
    client = MultiServerMCPClient(mcp_config)
    tools = await client.get_tools()
    return [
        MCPToolRes(tool_name=tool.name, tool_description=tool.description)
        for tool in tools
    ]


async def upload_document_to_rag_tool(user_id: str, file: UploadFile) -> str:
    """
    Saves an uploaded document for a user under the 'blob/{user_id}' directory.
    Args:
        user_id (str): ID of the user uploading the file
        file (UploadFile): Uploaded file from the API
    Returns:
        str: Absolute path of the saved document
    """
    if not user_id:
        raise AgentMartException("User ID is required for file upload", 400)

    if not file.filename:
        raise AgentMartException("File name is missing", 400)

    safe_filename = Path(file.filename).name
    user_blob_dir = BLOB_DIR / user_id
    user_blob_dir.mkdir(parents=True, exist_ok=True)

    destination_path = user_blob_dir / safe_filename

    with open(destination_path, "wb") as buffer:
        while content := await file.read(1024 * 1024):  # 1MB chunks
            buffer.write(content)

    logger.info(
        "Document '%s' successfully saved at '%s' for user '%s'",
        safe_filename,
        destination_path,
        user_id,
    )
    return FileUploadRes(
        file_path=str(destination_path),
        file_name=safe_filename,
    )