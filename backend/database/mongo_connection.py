import os
from typing import Optional
from dotenv import load_dotenv
from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.asynchronous.collection import AsyncCollection
from database.schema import UserProfile, AgentCatalog
from utils.logger import get_logger
from bson import ObjectId

load_dotenv()
logger = get_logger("database.mongo_connection")


class MongoConnection:
    """
    Handles asynchronous MongoDB connection establishment, managing database and collection instances
    loaded from environment variables (.env) or explicit constructor parameters using AsyncMongoClient.
    """

    def __init__(
        self,
        uri: Optional[str] = None,
        db_name: Optional[str] = None,
        collection_name: Optional[str] = None,
    ):
        load_dotenv()

        self.uri = uri or os.getenv("MONGO_CONN_STRING") or os.getenv("MONGO_URI")
        self.db_name = (
            db_name or os.getenv("MONGO_DATABASE") or os.getenv("MONGO_DB_NAME")
        )
        self.collection_name = (
            collection_name
            or os.getenv("MONGO_COLLECTION")
            or os.getenv("MONGO_COLLECTION_NAME")
        )

        if not self.uri:
            logger.error("MongoDB connection URI is missing.")
            raise ValueError(
                "MongoDB connection URI not specified and MONGO_CONN_STRING environment variable is missing."
            )
        if not self.db_name:
            logger.error("MongoDB database name is missing.")
            raise ValueError(
                "Database name not specified and MONGO_DATABASE / MONGO_DB_NAME environment variable is missing."
            )

        self._client: Optional[AsyncMongoClient] = None
        self._db: Optional[AsyncDatabase] = None
        self._collection: Optional[AsyncCollection] = None

    def connect(self) -> AsyncMongoClient:
        """Establishes and returns the AsyncMongoClient connection."""
        if self._client is None:
            logger.info("Connecting to MongoDB database '%s'...", self.db_name)
            self._client = AsyncMongoClient(self.uri)
            logger.info("MongoDB AsyncMongoClient connected successfully.")
        return self._client

    @property
    def client(self) -> AsyncMongoClient:
        """Returns the active AsyncMongoClient instance, connecting if needed."""
        if self._client is None:
            self.connect()
        return self._client

    @property
    def db(self) -> AsyncDatabase:
        """Returns the target async MongoDB Database instance."""
        if self._db is None:
            self._db = self.client[self.db_name]
            logger.debug("Accessed database instance: '%s'", self.db_name)
        return self._db

    @property
    def collection(self) -> AsyncCollection:
        """Returns the default async MongoDB Collection instance configured via environment/params."""
        if self._collection is None:
            if not self.collection_name:
                logger.error(
                    "Collection name is missing when accessing default collection."
                )
                raise ValueError(
                    "Collection name not specified and MONGO_COLLECTION / MONGO_COLLECTION_NAME environment variable is missing."
                )
            self._collection = self.db[self.collection_name]
            logger.debug("Accessed collection instance: '%s'", self.collection_name)
        return self._collection

    def get_collection(self, name: Optional[str] = None) -> AsyncCollection:
        """Returns a specific collection by name, or the default collection if none is provided."""
        target_name = name or self.collection_name
        if not target_name:
            logger.error("No collection name provided to get_collection().")
            raise ValueError("Collection name must be specified.")
        logger.debug("Getting collection '%s'", target_name)
        return self.db[target_name]

    async def close(self) -> None:
        """Closes the AsyncMongoClient connection asynchronously."""
        if self._client is not None:
            logger.info("Closing MongoDB connection...")
            await self._client.close()
            self._client = None
            self._db = None
            self._collection = None
            logger.info("MongoDB connection closed.")

    async def __aenter__(self):
        self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


class UserProfileCollection(MongoConnection):
    """
    Subclass of MongoConnection specialized for the 'user_profile' collection.
    """

    def __init__(self, collection_name: str = "user_profile", **kwargs):
        super().__init__(collection_name=collection_name, **kwargs)

    async def find_existing_user(self, email: str):
        return await self.collection.find_one({"email": email})

    async def register_new_user(self, new_user: UserProfile):
        return await self.collection.insert_one(new_user.model_dump())


class AgentCatalogConnection(MongoConnection):
    """
    Subclass of MongoConnection specialized for the 'agent_catalog' collection.
    """

    def __init__(self, collection_name: str = "agent_catalog", **kwargs):
        super().__init__(collection_name=collection_name, **kwargs)

    async def register_new_agent(self, new_agent_catalog: AgentCatalog):
        return await self.collection.insert_one(new_agent_catalog.model_dump())

    async def get_agent_config(self, agent_id: str):
        return await self.collection.find_one({"_id": ObjectId(agent_id)})

    async def edit_agent_config(
        self, agent_id: str, available_agent_catalog: AgentCatalog
    ):
        return await self.collection.update_one(
            {"_id": ObjectId(agent_id)}, {"$set": available_agent_catalog.model_dump()}
        )


async def get_db_connection() -> MongoConnection:
    """Helper for MongoConnection."""
    return MongoConnection(collection_name="user_profile")
