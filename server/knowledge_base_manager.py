import os
import time
import base64
from typing import List, Dict, Any, Optional, Tuple
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure
from datetime import datetime


class KnowledgeBaseManager:
    def __init__(self):
        self._client: Optional[MongoClient] = None
        self._uri: Optional[str] = None

    def _get_uri(self) -> str:
        uri = os.environ.get("MONGODB_URI", "")
        if not uri:
            raise ValueError("MONGODB_URI environment variable is not set")
        return uri

    def connect(self) -> Tuple[bool, str]:
        try:
            uri = self._get_uri()
            self._client = MongoClient(uri, serverSelectionTimeoutMS=10000)
            self._client.admin.command("ping")
            self._uri = uri
            return True, "Connected to MongoDB Atlas"
        except ValueError as e:
            return False, str(e)
        except ConnectionFailure as e:
            import re
            safe_msg = re.sub(r'//[^:]+:[^@]+@', '//***:***@', str(e))
            return False, f"Connection failed: {safe_msg}"
        except Exception as e:
            import re
            safe_msg = re.sub(r'//[^:]+:[^@]+@', '//***:***@', str(e))
            return False, f"Error: {safe_msg}"

    def get_client(self) -> MongoClient:
        if not self._client:
            success, msg = self.connect()
            if not success:
                raise ValueError(msg)
        try:
            self._client.admin.command("ping")
        except Exception:
            success, msg = self.connect()
            if not success:
                raise ValueError(msg)
        return self._client

    def list_databases(self) -> List[Dict[str, Any]]:
        client = self.get_client()
        result = []
        for db_name in client.list_database_names():
            if db_name in ("admin", "local", "config"):
                continue
            db = client[db_name]
            collections = db.list_collection_names()
            size_info = client.admin.command("dbStats") if False else {}
            result.append({
                "name": db_name,
                "collections": collections,
                "collection_count": len(collections),
            })
        return result

    def list_collections(self, db_name: str) -> List[Dict[str, Any]]:
        client = self.get_client()
        db = client[db_name]
        result = []
        for coll_name in db.list_collection_names():
            try:
                stats = db.command("collStats", coll_name)
                doc_count = stats.get("count", 0)
                size_bytes = stats.get("size", 0)
            except Exception:
                doc_count = db[coll_name].estimated_document_count()
                size_bytes = 0
            result.append({
                "name": coll_name,
                "document_count": doc_count,
                "size_bytes": size_bytes,
                "size_display": self._format_size(size_bytes),
            })
        return result

    def list_indexes(self, db_name: str, collection_name: str) -> List[Dict[str, Any]]:
        client = self.get_client()
        db = client[db_name]
        collection = db[collection_name]

        regular_indexes = []
        for idx in collection.list_indexes():
            regular_indexes.append({
                "name": idx.get("name", ""),
                "type": "regular",
                "keys": {k: v for k, v in idx.get("key", {}).items()},
                "unique": idx.get("unique", False),
            })

        search_indexes = []
        try:
            for idx in collection.list_search_indexes():
                idx_type = idx.get("type", "search")
                fields = []
                definition = idx.get("latestDefinition", idx.get("definition", {}))
                if "fields" in definition:
                    for f in definition["fields"]:
                        fields.append({
                            "path": f.get("path", ""),
                            "type": f.get("type", ""),
                            "numDimensions": f.get("numDimensions"),
                            "similarity": f.get("similarity"),
                        })
                search_indexes.append({
                    "name": idx.get("name", ""),
                    "type": idx_type,
                    "status": idx.get("status", "UNKNOWN"),
                    "fields": fields,
                    "queryable": idx.get("queryable", False),
                })
        except Exception as e:
            print(f"[KBManager] Could not list search indexes: {e}")

        return regular_indexes + search_indexes

    def browse_documents(self, db_name: str, collection_name: str, page: int = 1, page_size: int = 20, search: str = "") -> Dict[str, Any]:
        client = self.get_client()
        db = client[db_name]
        collection = db[collection_name]

        query: Dict[str, Any] = {}
        if search.strip():
            query["$or"] = [
                {"text": {"$regex": search.strip(), "$options": "i"}},
                {"file_name": {"$regex": search.strip(), "$options": "i"}},
            ]

        total = collection.count_documents(query)
        skip = (page - 1) * page_size

        cursor = collection.find(query).sort("_id", 1).skip(skip).limit(page_size)
        documents = []
        for doc in cursor:
            row: Dict[str, Any] = {}
            for k, v in doc.items():
                if k == "_id":
                    row[k] = str(v)
                elif k == "embedding" and isinstance(v, list):
                    row[k] = {"dimensions": len(v), "preview": v[:5]}
                elif isinstance(v, datetime):
                    row[k] = v.isoformat()
                else:
                    row[k] = str(v)[:500] if isinstance(v, (str, bytes)) else v
            documents.append(row)

        return {
            "documents": documents,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, (total + page_size - 1) // page_size),
        }

    def list_all_indexes(self, db_name: str) -> Dict[str, List[Dict[str, Any]]]:
        client = self.get_client()
        db = client[db_name]
        search_indexes: List[Dict[str, Any]] = []
        regular_indexes: List[Dict[str, Any]] = []

        for coll_name in db.list_collection_names():
            collection = db[coll_name]

            for idx in collection.list_indexes():
                regular_indexes.append({
                    "name": idx.get("name", ""),
                    "type": "regular",
                    "collection": coll_name,
                    "keys": {k: v for k, v in idx.get("key", {}).items()},
                    "unique": idx.get("unique", False),
                })

            try:
                for idx in collection.list_search_indexes():
                    idx_type = idx.get("type", "search")
                    fields = []
                    definition = idx.get("latestDefinition", idx.get("definition", {}))
                    if "fields" in definition:
                        for f in definition["fields"]:
                            fields.append({
                                "path": f.get("path", ""),
                                "type": f.get("type", ""),
                                "numDimensions": f.get("numDimensions"),
                                "similarity": f.get("similarity"),
                            })
                    search_indexes.append({
                        "name": idx.get("name", ""),
                        "type": idx_type,
                        "collection": coll_name,
                        "status": idx.get("status", "UNKNOWN"),
                        "fields": fields,
                        "queryable": idx.get("queryable", False),
                    })
            except Exception:
                pass

        return {"search_indexes": search_indexes, "regular_indexes": regular_indexes}

    def _get_index_dimensions(self, db_name: str, collection_name: str, index_name: str) -> int:
        client = self.get_client()
        db = client[db_name]
        collection = db[collection_name]
        try:
            for idx in collection.list_search_indexes():
                if idx.get("name") == index_name:
                    definition = idx.get("latestDefinition", idx.get("definition", {}))
                    for field in definition.get("fields", []):
                        if field.get("type") == "vector" and field.get("numDimensions"):
                            return int(field["numDimensions"])
        except Exception:
            pass
        return 384

    def _get_genai_embedding(self, text: str) -> List[float]:
        import requests
        started_at = time.time()
        api_key = os.getenv("PWC_GENAI_API_KEY") or os.getenv("GEMINI_API_KEY")
        bearer_token = os.getenv("PWC_GENAI_BEARER_TOKEN")
        base_url = os.getenv("PWC_GENAI_ENDPOINT_URL") or os.getenv(
            "GEMINI_API_ENDPOINT",
            "https://genai-sharedservice-americas.pwc.com"
        )
        embeddings_url = base_url.replace("/completions", "").rstrip("/") + "/embeddings"

        headers = {
            "accept": "application/json",
            "API-Key": api_key,
            "Content-Type": "application/json",
        }
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"

        payload = {
            "model": os.getenv("EMBEDDING_MODEL", "vertex_ai.text-embedding-005"),
            "input": text,
        }

        resp = requests.post(embeddings_url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        embedding = data["data"][0]["embedding"]

        try:
            from langfuse_tracer import trace_llm_call

            usage = data.get("usage") or {}
            trace_llm_call(
                model=str(payload.get("model") or "vertex_ai.text-embedding-005"),
                prompt=f"[embedding request chars={len(text)}]",
                completion=f"[embedding vector dims={len(embedding)}]",
                prompt_tokens=int(usage.get("prompt_tokens") or max(1, len(text.split()))),
                completion_tokens=int(usage.get("completion_tokens") or 0),
                latency_ms=(time.time() - started_at) * 1000,
                agent_name="Knowledge Base Manager",
                extra_metadata={"path": "kb_manager/embeddings_single", "endpoint": "/embeddings"},
            )
        except Exception:
            pass

        return embedding

    def vector_search_query(self, db_name: str, collection_name: str, query_text: str, index_name: str = "vector_index", limit: int = 10) -> Dict[str, Any]:
        client = self.get_client()
        db = client[db_name]
        collection = db[collection_name]

        index_dims = self._get_index_dimensions(db_name, collection_name, index_name)

        query_embedding = None
        if index_dims > 384:
            try:
                query_embedding = self._get_genai_embedding(query_text)
                print(f"[KBManager] Used GenAI embedding ({len(query_embedding)}d) for {index_dims}d index")
            except Exception as e:
                print(f"[KBManager] GenAI embedding failed: {e}, falling back to local model")

        if query_embedding is None:
            from agents.MongoDB_RAG_agent.tools.embedding_service import get_embeddings
            embeddings = get_embeddings([query_text])
            if not embeddings or not embeddings[0]:
                return {"success": False, "message": "Failed to generate embedding for query", "results": []}
            query_embedding = embeddings[0]

        try:
            pipeline = [
                {
                    "$vectorSearch": {
                        "index": index_name,
                        "path": "embedding",
                        "queryVector": query_embedding,
                        "numCandidates": limit * 10,
                        "limit": limit,
                    }
                },
                {
                    "$project": {
                        "embedding": 0,
                        "score": {"$meta": "vectorSearchScore"},
                    }
                }
            ]
            results = list(collection.aggregate(pipeline))
            for doc in results:
                if "_id" in doc:
                    doc["_id"] = str(doc["_id"])
                for k, v in doc.items():
                    if isinstance(v, datetime):
                        doc[k] = v.isoformat()

            return {"success": True, "results": results, "count": len(results), "query": query_text}
        except Exception as e:
            return {"success": False, "message": str(e), "results": []}

    def get_collection_stats(self, db_name: str, collection_name: str) -> Dict[str, Any]:
        client = self.get_client()
        db = client[db_name]
        collection = db[collection_name]

        doc_count = collection.estimated_document_count()
        files = []
        try:
            files = collection.distinct("file_name")
            files = [f for f in files if f]
        except Exception:
            pass

        sample_doc = None
        try:
            sample = collection.find_one({}, {"embedding": 0, "_id": 0})
            if sample:
                sample_doc = {k: str(v)[:200] for k, v in sample.items()}
        except Exception:
            pass

        return {
            "document_count": doc_count,
            "files": files,
            "file_count": len(files),
            "sample_document": sample_doc,
        }

    def create_vector_index(
        self,
        db_name: str,
        collection_name: str,
        index_name: str = "vector_index",
        embedding_field: str = "embedding",
        dimensions: int = 384,
        similarity: str = "cosine",
    ) -> Dict[str, Any]:
        client = self.get_client()
        db = client[db_name]
        collection = db[collection_name]

        try:
            existing = list(collection.list_search_indexes())
            for idx in existing:
                if idx.get("name") == index_name:
                    return {"success": False, "message": f"Index '{index_name}' already exists"}
        except Exception:
            pass

        try:
            from pymongo.operations import SearchIndexModel
            search_index = SearchIndexModel(
                definition={
                    "fields": [
                        {
                            "type": "vector",
                            "path": embedding_field,
                            "numDimensions": dimensions,
                            "similarity": similarity,
                        },
                        {
                            "type": "filter",
                            "path": "file_name",
                        }
                    ]
                },
                name=index_name,
                type="vectorSearch",
            )
            collection.create_search_index(model=search_index)
            return {
                "success": True,
                "message": f"Vector search index '{index_name}' created on '{db_name}.{collection_name}'",
                "index_name": index_name,
            }
        except OperationFailure as e:
            if "already exists" in str(e).lower():
                return {"success": True, "message": f"Index '{index_name}' already exists", "index_name": index_name}
            return {"success": False, "message": f"Operation failed: {str(e)}"}
        except Exception as e:
            return {"success": False, "message": f"Error creating index: {str(e)}"}

    def delete_collection(self, db_name: str, collection_name: str) -> Dict[str, Any]:
        client = self.get_client()
        db = client[db_name]
        try:
            db.drop_collection(collection_name)
            return {"success": True, "message": f"Collection '{collection_name}' deleted from '{db_name}'"}
        except Exception as e:
            return {"success": False, "message": f"Error deleting collection: {str(e)}"}

    def rename_collection(self, db_name: str, old_name: str, new_name: str) -> Dict[str, Any]:
        client = self.get_client()
        db = client[db_name]
        try:
            db[old_name].rename(new_name)
            return {"success": True, "message": f"Collection renamed from '{old_name}' to '{new_name}'"}
        except Exception as e:
            return {"success": False, "message": f"Error renaming collection: {str(e)}"}

    def delete_search_index(self, db_name: str, collection_name: str, index_name: str) -> Dict[str, Any]:
        client = self.get_client()
        db = client[db_name]
        collection = db[collection_name]

        try:
            collection.drop_search_index(index_name)
            return {"success": True, "message": f"Index '{index_name}' deleted"}
        except Exception as e:
            return {"success": False, "message": f"Error deleting index: {str(e)}"}

    def ingest_file(
        self,
        db_name: str,
        project_id: str,
        file_content_b64: str,
        file_name: str,
        file_type: str,
    ) -> Dict[str, Any]:
        from kb_ingestion_pipeline import ingest_file_pipeline

        client = self.get_client()
        return ingest_file_pipeline(
            mongodb_client=client,
            db_name=db_name,
            project_id=project_id,
            file_content_b64=file_content_b64,
            file_name=file_name,
            file_type=file_type,
        )

    def delete_file_chunks(self, db_name: str, collection_name: str, file_name: str) -> Dict[str, Any]:
        client = self.get_client()
        db = client[db_name]
        collection = db[collection_name]

        result = collection.delete_many({"file_name": file_name})
        return {
            "success": True,
            "message": f"Deleted {result.deleted_count} chunks for '{file_name}'",
            "deleted_count": result.deleted_count,
        }

    def create_database_and_collection(self, db_name: str, collection_name: str) -> Dict[str, Any]:
        client = self.get_client()
        db = client[db_name]
        db[collection_name].insert_one({"_init": True, "created_at": datetime.utcnow()})
        db[collection_name].delete_one({"_init": True})
        return {
            "success": True,
            "message": f"Created database '{db_name}' with collection '{collection_name}'",
        }

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


kb_manager = KnowledgeBaseManager()
