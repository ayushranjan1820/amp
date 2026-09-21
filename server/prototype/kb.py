"""Hardcoded knowledge-base admin API payloads."""

from __future__ import annotations

from typing import Any, Dict, List


def kb_status() -> Dict[str, Any]:
    return {"connected": True, "message": "Knowledge base ready"}


def kb_databases() -> Dict[str, Any]:
    return {
        "databases": [
            {"name": "agents_kb", "collections": ["documents", "policies", "runbooks"], "collection_count": 3},
        ]
    }


def kb_collections(db_name: str) -> Dict[str, Any]:
    return {
        "database": db_name,
        "collections": [
            {"name": "documents", "document_count": 128, "size_bytes": 5242880, "size_display": "5.0 MB"},
            {"name": "policies", "document_count": 42, "size_bytes": 1048576, "size_display": "1.0 MB"},
            {"name": "runbooks", "document_count": 18, "size_bytes": 524288, "size_display": "512 KB"},
        ],
    }


def kb_indexes(db_name: str, collection_name: str) -> Dict[str, Any]:
    return {
        "database": db_name,
        "collection": collection_name,
        "indexes": [
            {
                "name": "vector_index",
                "type": "vectorSearch",
                "status": "READY",
                "fields": [{"path": "embedding", "type": "vector", "numDimensions": 1536, "similarity": "cosine"}],
                "queryable": True,
            },
            {"name": "_id_", "type": "regular", "keys": {"_id": 1}},
        ],
    }


def kb_stats(db_name: str, collection_name: str) -> Dict[str, Any]:
    return {
        "database": db_name,
        "collection": collection_name,
        "document_count": 128,
        "files": ["expense-policy.pdf", "onboarding-guide.docx", "security-runbook.md"],
        "file_count": 3,
        "sample_document": {"file_name": "expense-policy.pdf", "section": "4.2"},
    }


def kb_documents(db_name: str, collection_name: str, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
    docs = [
        {"_id": "1", "file_name": "expense-policy.pdf", "section": "4.2", "chunk_index": 0},
        {"_id": "2", "file_name": "onboarding-guide.docx", "section": "Day 1", "chunk_index": 0},
    ]
    return {"documents": docs, "total": len(docs), "page": page, "page_size": page_size, "total_pages": 1}


def kb_all_indexes(db_name: str) -> Dict[str, Any]:
    return {"database": db_name, "indexes": kb_indexes(db_name, "documents")["indexes"]}


def kb_all_vector_indexes() -> Dict[str, Any]:
    return {
        "indexes": [
            {
                "database": "agents_kb",
                "collection": "documents",
                "index_name": "vector_index",
                "dimensions": 1536,
                "similarity": "cosine",
                "status": "READY",
            }
        ]
    }


def kb_success(message: str = "OK") -> Dict[str, Any]:
    return {"success": True, "message": message}


def kb_vector_search(query: str, limit: int = 10) -> Dict[str, Any]:
    return {
        "success": True,
        "results": [
            {
                "score": 0.94,
                "file_name": "expense-policy.pdf",
                "section": "4.2",
                "text": f"Relevant excerpt for: {query}",
            }
        ],
        "count": 1,
    }
