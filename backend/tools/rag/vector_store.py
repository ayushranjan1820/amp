import time
from abc import ABC, abstractmethod
from typing import Optional

from langchain_cohere import CohereEmbeddings
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_docling.loader import DoclingLoader
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from langchain_qdrant import QdrantVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pinecone import Pinecone, ServerlessSpec
from qdrant_client import QdrantClient
from qdrant_client.http.models.models import Distance, VectorParams
from tools.tool_config import (
    DistanceStrategy,
    EmbeddingModelConfig,
    EmbeddingModelProvider,
    RAGToolAdvancedConfig,
    VectorDBConfig,
)
from langchain_chroma import Chroma
from chromadb import CloudClient
from utils.logger import get_logger

logger = get_logger(__name__)


class VectorStore(ABC):
    """Abstract Base Class for Vector Stores."""

    def __init__(
        self,
        vector_db_config: VectorDBConfig,
        embedding_config: EmbeddingModelConfig,
        advanced_config: RAGToolAdvancedConfig,
    ):
        """Initializes shared vector store fields across all implementations."""

        match (embedding_config.provider):
            case EmbeddingModelProvider.GOOGLE:
                embedding_model = GoogleGenerativeAIEmbeddings(
                    model=embedding_config.model,
                    google_api_key=embedding_config.api_key,
                    output_dimensionality=vector_db_config.vector_dimension,
                )
            case EmbeddingModelProvider.OPENAI:
                embedding_model = OpenAIEmbeddings(
                    model=embedding_config.model,
                    api_key=embedding_config.api_key,
                )
            case EmbeddingModelProvider.COHERE:
                embedding_model = CohereEmbeddings(
                    model=embedding_config.model,
                    cohere_api_key=embedding_config.api_key,
                )
            case default:
                raise AgentMartException("Model provider is not in the list", 404)

        self.vector_db_config = vector_db_config
        self.embedding = embedding_model
        self.advanced_config = advanced_config
        self.index_name = vector_db_config.collection_name.lower()
        self.api_key = vector_db_config.vector_db_api_key
        self.namespace = vector_db_config.namespace

    @staticmethod
    def sanitize_metadata(metadata: dict) -> dict:
        """
        Sanitizes metadata so values conform to vector DB constraints (e.g. Pinecone).
        Only accepts str, int, float, bool, or list[str], dropping complex nested objects.
        """
        clean_meta = {}
        for key, val in metadata.items():
            if isinstance(val, (str, int, float, bool)):
                clean_meta[key] = val
            elif isinstance(val, list) and all(isinstance(item, str) for item in val):
                clean_meta[key] = val
        return clean_meta

    @abstractmethod
    def initialize_vector_store(self):
        """Initializes provider-specific vector store client, indexes, and connections."""
        raise NotImplementedError("Subclasses must implement initialize_vector_store()")

    def chunk_document(
        self, doc_path: str, chunk_size: int, chunk_overlap: int
    ) -> list[Document]:
        """Loads and splits the document into chunks."""
        documents = DoclingLoader(doc_path).load()
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )
        return text_splitter.split_documents(documents)

    @abstractmethod
    async def add_documents(self, documents: list[Document]):
        """Asynchronously adds documents to the vector store."""
        raise NotImplementedError("Subclasses must implement add_documents()")

    @abstractmethod
    async def get_retrieved_documents(self, query: str) -> list[Document]:
        """Asynchronously retrieves documents from the vector store."""
        raise NotImplementedError("Subclasses must implement get_retrieved_documents()")


class PineconeVectorStoreImpl(VectorStore):

    def __init__(
        self,
        vector_db_config: VectorDBConfig,
        embedding_config: EmbeddingModelConfig,
        advanced_config: Optional[RAGToolAdvancedConfig] = None,
    ):
        super().__init__(vector_db_config, embedding_config, advanced_config)
        self.initialize_vector_store()

    def initialize_vector_store(self):
        distance_metric = str(self.advanced_config.distance_strategy)
        vector_type = self.advanced_config.vector_type
        cloud = self.vector_db_config.cloud_provider
        region = self.vector_db_config.region
        dimension = self.vector_db_config.vector_dimension

        pc = Pinecone(api_key=self.api_key)
        if not pc.has_index(self.index_name):
            pc.create_index(
                name=self.index_name,
                metric=distance_metric,
                vector_type=vector_type,
                spec=ServerlessSpec(cloud=cloud, region=region),
                dimension=dimension,
            )
            # Wait until index is ready
            while not pc.describe_index(self.index_name).status.get("ready"):
                time.sleep(1)

        self.pc_index = pc.Index(self.index_name)

        self.pinecone_vector_store = PineconeVectorStore(
            index=self.pc_index,
            embedding=self.embedding,
            namespace=self.namespace,
        )

    async def add_documents(self, documents: list[Document]):
        for doc in documents:
            doc.metadata = self.sanitize_metadata(doc.metadata)
        await self.pinecone_vector_store.aadd_documents(documents)

    async def get_retrieved_documents(self, query: str) -> list[Document]:
        retriever = self.pinecone_vector_store.as_retriever(
            search_type=self.advanced_config.retrieval_strategy,
            search_kwargs={
                "k": self.advanced_config.top_k,
            },
        )
        return await retriever.ainvoke(query)


class QdrantVectorStoreImpl(VectorStore):

    def __init__(
        self,
        vector_db_config: VectorDBConfig,
        embedding_config: EmbeddingModelConfig,
        advanced_config: Optional[RAGToolAdvancedConfig] = None,
    ):
        super().__init__(vector_db_config, embedding_config, advanced_config)
        self.initialize_vector_store()

    def initialize_vector_store(self):
        match self.advanced_config.distance_strategy:
            case DistanceStrategy.COSINE:
                distance_metric = Distance.COSINE
            case DistanceStrategy.DOTPRODUCT:
                distance_metric = Distance.DOT
            case DistanceStrategy.EUCLIDEAN:
                distance_metric = Distance.EUCLID
            case DistanceStrategy.MANHATTAN:
                distance_metric = Distance.MANHATTAN
            case default:
                raise AgentMartException(
                    f"Distance {self.rag_advanced_config.distance_strategy} not supported for Qdrant or does not exist",
                    404,
                )

        self.qdrant_client = QdrantClient(
            url=self.vector_db_config.vector_db_url,
            api_key=self.api_key,
        )
        if not self.qdrant_client.collection_exists(self.index_name):
            self.qdrant_client.create_collection(
                collection_name=self.index_name,
                vectors_config=VectorParams(
                    size=self.vector_db_config.vector_dimension,
                    distance=distance_metric,
                ),
            )
        self.qdrant_vector_store = QdrantVectorStore(
            client=self.qdrant_client,
            collection_name=self.index_name,
            embedding=self.embedding,
            distance=distance_metric,
        )

    async def add_documents(self, documents: list[Document]):
        for doc in documents:
            doc.metadata = self.sanitize_metadata(doc.metadata)
        await self.qdrant_vector_store.aadd_documents(documents)

    async def get_retrieved_documents(self, query: str) -> list[Document]:
        retriever = self.qdrant_vector_store.as_retriever(
            search_type=self.advanced_config.retrieval_strategy,
            search_kwargs={
                "k": self.vector_db_config.top_k,
            },
        )
        documents =  await retriever.ainvoke(query)
        logger.debug("Retrieved %d documents successfully", len(documents))
        return documents


class ChromaVectorStoreImpl(VectorStore):

    def __init__(
        self,
        vector_db_config: VectorDBConfig,
        embedding_config: EmbeddingModelConfig,
        advanced_config: Optional[RAGToolAdvancedConfig] = None,
    ):
        super().__init__(vector_db_config, embedding_config, advanced_config)
        self.initialize_vector_store()

    def initialize_vector_store(self):
        self.chroma_client = CloudClient(
            tenant=self.vector_db_config.vector_db_tenant,
            api_key=self.vector_db_config.vector_db_api_key,
            database=self.vector_db_config.vector_db_url, # For ChromaDB, storing database name in 'vector_db_url' field
        )
        self.chroma_vector_store = Chroma(
            client=self.chroma_client,
            collection_name=self.index_name,
            embedding_function=self.embedding
        )

    async def add_documents(self, documents: list[Document]):
        for doc in documents:
            doc.metadata = self.sanitize_metadata(doc.metadata)
        await self.chroma_vector_store.aadd_documents(documents)

    async def get_retrieved_documents(self, query: str) -> list[Document]:
        retriever = self.chroma_vector_store.as_retriever(
            search_type=self.advanced_config.retrieval_strategy,
            search_kwargs={
                "k": self.vector_db_config.top_k,
            },
        )
        documents =  await retriever.ainvoke(query)
        logger.debug("Retrieved %d documents successfully", len(documents))
        return documents


class WeaviateVectorStoreImpl(VectorStore):

    def __init__(
        self,
        vector_db_config: VectorDBConfig,
        embedding: Embeddings,
        advanced_config: Optional[RAGToolAdvancedConfig] = None,
    ):
        super().__init__(vector_db_config, embedding, advanced_config)
        self.initialize_vector_store()

    def initialize_vector_store(self):
        pass

    async def add_documents(self, documents: list[Document]):
        raise NotImplementedError(
            "WeaviateVectorStoreImpl.add_documents() is not yet implemented"
        )


class VectorStoreFactory:
    @staticmethod
    def get_vector_store(
        vector_store_type: str,
        vector_db_config: VectorDBConfig,
        embedding_config: EmbeddingModelConfig,
        advanced_config: RAGToolAdvancedConfig,
    ) -> VectorStore:
        provider = str(vector_store_type).lower()
        if "pinecone" in provider:
            return PineconeVectorStoreImpl(
                vector_db_config, embedding_config, advanced_config
            )
        elif "qdrant" in provider:
            return QdrantVectorStoreImpl(
                vector_db_config, embedding_config, advanced_config
            )
        elif "chroma" in provider:
            return ChromaVectorStoreImpl(
                vector_db_config, embedding_config, advanced_config
            )
        elif "weaviate" in provider:
            return WeaviateVectorStoreImpl(
                vector_db_config, embedding_config, advanced_config
            )
        else:
            raise ValueError(
                f"Invalid or unsupported vector store type: {vector_store_type}"
            )
