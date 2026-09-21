"""
Agent Invoker Service Module for Router Agent
Handles unified agent invocation using catalog configuration.
"""

from typing import Dict, Any, Optional, List
from ..config.catalog_loader import CatalogLoader
from ..services.agent_loader import AgentLoader
from ..core.context_builder import ContextBuilder
from ..utils.response_formatter import ResponseFormatter
import re
import httpx
import json


class AgentInvoker:
    """Invokes agents with unified interface based on catalog configuration."""
    
    def __init__(self, catalog_loader: CatalogLoader, agent_loader: AgentLoader, context_builder: ContextBuilder):
        self.catalog_loader = catalog_loader
        self.agent_loader = agent_loader
        self.context_builder = context_builder
        self.response_formatter = ResponseFormatter()
    
    async def _invoke_external_agent(self, agent_info: Dict, query: str, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Call an external agent via its configured API URL with LLM-powered adaptation and formatting."""
        from api import _build_external_payload, _external_request_kwargs, _extract_external_response, _llm_call_async, \
            _build_payload_adaptation_prompt, _build_response_formatting_prompt

        external_url = agent_info.get("external_api_url", "")
        payload_template = agent_info.get("external_payload_template", "")
        external_headers = agent_info.get("external_headers", {})
        external_method = agent_info.get("external_method", "POST").upper()
        external_payload_format = agent_info.get("external_payload_format", "json")
        agent_name = agent_info.get("name", "External Agent")
        agent_description = agent_info.get("description", "External AI agent")

        try:
            if payload_template and payload_template.strip() and "{{query}}" in payload_template:
                payload = _build_external_payload(payload_template, query, session_id or "default")
            else:
                try:
                    adapt_prompt = _build_payload_adaptation_prompt(
                        query, agent_name, agent_description, payload_template, external_url, session_id or "default"
                    )
                    llm_payload_text = await _llm_call_async(adapt_prompt, max_tokens=1024, temperature=0.1)
                    llm_payload_text = llm_payload_text.strip()
                    if llm_payload_text.startswith("```"):
                        lines = llm_payload_text.split("\n")
                        lines = [l for l in lines if not l.strip().startswith("```")]
                        llm_payload_text = "\n".join(lines)
                    payload = json.loads(llm_payload_text)
                except Exception as e:
                    print(f"[Router/ExternalAgent] LLM payload adaptation failed ({e}), falling back to default")
                    payload = {"query": query, "session_id": session_id or "default"}

            req_headers = {"Content-Type": "application/json"}
            if external_headers and isinstance(external_headers, dict):
                req_headers.update(external_headers)
            req_headers, request_kwargs = _external_request_kwargs(
                payload, external_payload_format, req_headers
            )

            async with httpx.AsyncClient(timeout=120.0, verify=False) as client:
                ext_response = await client.request(
                    external_method, external_url, headers=req_headers, **request_kwargs
                )
                ext_response.raise_for_status()

            raw_response = _extract_external_response(ext_response)

            is_json_blob = raw_response.strip().startswith("{") or raw_response.strip().startswith("[")
            needs_formatting = is_json_blob or len(raw_response) > 2000

            if needs_formatting:
                try:
                    format_prompt = _build_response_formatting_prompt(raw_response, agent_name, query)
                    formatted_response = await _llm_call_async(format_prompt, max_tokens=4096, temperature=0.3)
                except Exception as e:
                    print(f"[Router/ExternalAgent] LLM formatting failed ({e}), using raw response")
                    formatted_response = raw_response
            else:
                formatted_response = raw_response

            return {
                "success": True,
                "response": formatted_response,
                "thinking_steps": [
                    {"type": "info", "content": f"Analyzed query and adapted payload for '{agent_name}'"},
                    {"type": "info", "content": f"Called external API at {external_url}"},
                    {"type": "info", "content": "Formatted response using LLM" if needs_formatting else "Returned response directly"}
                ]
            }
        except httpx.HTTPStatusError as e:
            return {"success": False, "response": f"External API error ({e.response.status_code}): {e.response.text[:500]}", "thinking_steps": []}
        except Exception as e:
            return {"success": False, "response": f"Error calling external agent '{agent_name}': {str(e)}", "thinking_steps": []}

    async def invoke_agent(self, agent_id: str, query: str, session_id: Optional[str] = None, conversation_history: Optional[List[Dict]] = None, references_context: bool = False, github_token: Optional[str] = None, file_content: Optional[str] = None, file_type: Optional[str] = None, file_name: Optional[str] = None) -> Dict[str, Any]:
        """Unified agent invocation using catalog configuration."""
        agent_info = self.catalog_loader.get_agent_info(agent_id)
        if not agent_info:
            return {"success": False, "response": f"Agent '{agent_id}' not found.", "thinking_steps": []}

        if agent_info.get("external_api_url"):
            return await self._invoke_external_agent(agent_info, query, session_id)

        instance = self.agent_loader.get_agent_instance(agent_id)
        if not instance:
            return {"success": False, "response": f"Could not load agent '{agent_info['name']}'.", "thinking_steps": []}

        contextualized_query = self.context_builder.build_context_query(query, conversation_history, agent_id, references_context)
        invocation = agent_info.get("invocation", {})
        
        # Special preprocessing for github_repo agent
        if agent_id == "github_repo":
            effective_token = github_token
            if not effective_token:
                token_match = re.search(r'(ghp_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})', query)
                if token_match:
                    effective_token = token_match.group(1)
                    contextualized_query = query.replace(effective_token, '').strip()
                    if not contextualized_query or contextualized_query in ('', '.', ','):
                        contextualized_query = "push the code to GitHub"
            github_token = effective_token
        
        # Special preprocessing for unit_test_agent
        if agent_id == "unit_test_agent" and invocation.get("requires_github_session"):
            effective_session = session_id or "default"
            ut_session = instance._get_session(effective_session)
            if not ut_session.get("cloned"):
                github_agent = self.agent_loader.get_agent_instance("github_repo")
                if github_agent and hasattr(github_agent, 'sessions'):
                    gh_session = github_agent.sessions.get(effective_session)
                    if gh_session and gh_session.get("cloned") and gh_session.get("repo_path") and gh_session.get("repo_url"):
                        instance.set_repo(
                            session_id=effective_session,
                            repo_url=gh_session["repo_url"],
                            repo_path=gh_session["repo_path"],
                            repo_name=gh_session.get("repo_name", "unknown"),
                        )

        try:
            # Build method call parameters from invocation config
            method_name = invocation.get("method", "process_query")
            param_mapping = invocation.get("params", {"query": "query"})
            is_async = invocation.get("is_async", False)
            
            # Map parameters
            call_params = {}
            for param_key, value_source in param_mapping.items():
                if value_source == "query":
                    call_params[param_key] = contextualized_query
                elif value_source == "session_id":
                    call_params[param_key] = session_id or "default"
                elif value_source == "github_token":
                    call_params[param_key] = github_token
                elif value_source == "file_content":
                    call_params[param_key] = file_content
                elif value_source == "file_type":
                    call_params[param_key] = file_type
                elif value_source == "file_name":
                    call_params[param_key] = file_name
            
            # Call the method
            method = getattr(instance, method_name, None)
            if not method:
                return {"success": False, "response": f"Method '{method_name}' not found on agent.", "thinking_steps": []}
            
            if is_async:
                result = await method(**call_params)
            else:
                result = method(**call_params)
            
            # Handle model_dump for Pydantic models
            if invocation.get("has_model_dump"):
                if hasattr(result, 'model_dump'):
                    result = result.model_dump()
                elif hasattr(result, 'dict'):
                    result = result.dict()
            
            # Handle basic_agent special case (may return non-dict)
            if agent_id == "basic_agent" and not isinstance(result, dict):
                return {"success": True, "response": str(result), "thinking_steps": []}
            
            # Extract result fields based on result_path
            result_paths = invocation.get("result_path", ["response", "thinking_steps"])
            response_dict = {"success": result.get("success", True)}
            
            for path in result_paths:
                if path in result:
                    if path == "thinking_steps" or path == "intermediate_steps":
                        response_dict["thinking_steps"] = self.response_formatter.normalize_thinking_steps(result.get(path, []))
                    else:
                        response_dict[path] = result[path]
            
            # Ensure thinking_steps exists
            if "thinking_steps" not in response_dict:
                response_dict["thinking_steps"] = []
            
            return response_dict

        except Exception as e:
            return {
                "success": False,
                "response": f"Error calling {agent_info['name']}: {str(e)}",
                "thinking_steps": []
            }
