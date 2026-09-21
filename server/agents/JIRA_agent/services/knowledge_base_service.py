"""Knowledge base service stub for JIRA agent."""


class KnowledgeBaseService:
    def __init__(self, db=None):
        self.db = db

    def search_knowledge_base(self, project_id=None, query="", limit=5):
        return []

    async def search_knowledge_base_async(self, project_id=None, query="", limit=5):
        return []

    def get_knowledge_stats(self, project_id=None):
        return {"total_documents": 0, "total_chunks": 0}
