from tools.rag.vector_store import VectorStore
from tools.tool_config import RAGToolAdvancedConfig


async def ingest_document(
    vector_store: VectorStore,
    document_path: str,
    rag_advanced_config: RAGToolAdvancedConfig,
):
    chunk_size = rag_advanced_config.chunk_size
    chunk_overlap = rag_advanced_config.chunk_overlap
    documents = vector_store.chunk_document(document_path, chunk_size, chunk_overlap)
    await vector_store.add_documents(documents)
