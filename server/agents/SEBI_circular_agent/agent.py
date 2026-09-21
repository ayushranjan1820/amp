import asyncio
import os
from typing import List, Dict, Any, Optional, AsyncGenerator
import json
import re

try:
    from ddgs import DDGS
    DDGS_AVAILABLE = True
except ImportError:
    DDGS_AVAILABLE = False

from .tools.perplexity_search import perplexity_search
from .tools.email_sender import send_sebi_email, format_sebi_report_as_html
from .ai_service import ai_service


class SEBICircularAgent:
    """
    Context-aware SEBI Circular Agent using Perplexity for web search
    and PWC LLM for intelligent summarization and key point extraction.
    
    Features:
    - Conversation memory for context retention
    - Intent classification to avoid redundant searches
    - Smart handling of follow-up queries
    """
    
    def __init__(self):
        self.search = perplexity_search
        self.ai = ai_service
        # Conversation memory: {session_id: [{query, response, search_results}]}
        self.conversation_history: Dict[str, List[Dict[str, Any]]] = {}

    @staticmethod
    def _search_provider() -> str:
        raw = (os.getenv("SEBI_WEB_SEARCH_PROVIDER") or "perplexity").strip().lower()
        if raw in ("free", "free_web", "free_ollama", "ollama", "ollama_free"):
            return "free_ollama"
        if raw in ("free_duckduckgo", "duckduckgo", "duck", "ddg"):
            return "free_duckduckgo"
        return "perplexity"

    @staticmethod
    def _search_tool_name() -> str:
        provider = SEBICircularAgent._search_provider()
        if provider == "free_ollama":
            return "ollama_web_search"
        if provider == "free_duckduckgo":
            return "duckduckgo_web_search"
        return "perplexity_search"

    @staticmethod
    def _provider_configured() -> bool:
        provider = SEBICircularAgent._search_provider()
        if provider == "free_ollama":
            return bool(
                (os.getenv("OLLAMA_API_KEY") or "").strip()
                or (os.getenv("ON_PREM_CLOUD_ACCESS_TOKEN") or "").strip()
                or (os.getenv("OLLAMA_CLOUD_BEARER_TOKEN") or "").strip()
            )
        if provider == "free_duckduckgo":
            return DDGS_AVAILABLE
        return bool((os.getenv("PERPLEXITY_API_KEY") or "").strip())
    
    async def send_email_report(
        self,
        recipients: List[str],
        query: str,
        summary: str,
        search_results: List[Dict[str, Any]],
        subject: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send SEBI circular report via email with AI-formatted content.
        
        Args:
            recipients: List of email addresses
            query: The original user query
            summary: The formatted summary/response
            search_results: List of search results with title, url, snippet
            subject: Optional custom subject line
        
        Returns:
            dict with success status and message
        """
        # Use AI to format content specifically for email
        email_formatting_prompt = f"""You are formatting a SEBI circular research report for a professional email. Convert the following content into a well-structured, professional email format.

**Original Query:** {query}

**Content to Format:**
{summary}

**Instructions:**
1. Create a professional email greeting (use "Dear Sir/Madam" if no specific name)
2. Start with a brief introduction (1-2 sentences) explaining the purpose
3. Present the key information in a clear, organized manner:
   - Use short paragraphs (2-3 sentences max)
   - Use bullet points for lists and action items
   - Highlight important dates, numbers, and requirements
   - Keep technical terms but explain if needed
4. End with a professional closing
5. Keep the tone formal yet accessible
6. Make it scannable - busy professionals should grasp key points quickly
7. Limit to 400-500 words for the main body
8. Include section headings where appropriate (use bold)

**Output Format:**
Provide ONLY the email body content in HTML format using these tags:
- <h3> for main sections
- <p> for paragraphs
- <ul> and <li> for bullet lists
- <strong> for emphasis
- <br> for line breaks

Do not include greetings like "Dear..." or signatures - just the main content.

**Formatted Email Content:**"""

        try:
            # Get AI-formatted email content
            formatted_content = await self.ai.call_genai(
                email_formatting_prompt, 
                temperature=0.3, 
                max_tokens=2000
            )
        except Exception as e:
            # Fallback to basic formatting if AI fails
            formatted_content = f"<h3>SEBI Circular Research Report</h3><p>{summary[:500]}...</p>"
        
        # Generate custom subject if not provided
        if not subject:
            try:
                subject_prompt = f"""Generate a professional, concise email subject line for this SEBI circular report.

**Query:** {query}
**Content Preview:** {summary[:200]}

Create a subject line that:
- Is 50-60 characters max
- Clearly indicates it's about SEBI regulations/circulars
- Mentions the key topic
- Is professional and actionable

Respond with ONLY the subject line, no quotes or extra text.

**Subject:**"""
                
                custom_subject = await self.ai.call_genai(subject_prompt, temperature=0.2, max_tokens=30)
                subject = custom_subject.strip().strip('"\'')
                
                # Fallback if subject is too long or empty
                if not subject or len(subject) > 80:
                    subject = f"SEBI Circular Report: {query[:40]}..."
            except:
                subject = f"SEBI Circular Report: {query[:50]}..."
        
        # Format sources for email
        sources = []
        for result in search_results:
            sources.append({
                'title': result.get('title', 'Untitled'),
                'url': result.get('url', '#'),
                'snippet': result.get('snippet', '')
            })
        
        # Generate HTML email with AI-formatted content
        html_content = format_sebi_report_as_html(query, formatted_content, sources)
        
        # Send email
        result = send_sebi_email(
            recipients=recipients,
            subject=subject,
            html_content=html_content
        )
        
        return result
    
    async def _analyze_query_intent(self, query: str, has_history: bool, last_context: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Use AI to intelligently analyze query intent and determine action.
        No hardcoded rules - AI decides dynamically based on context.
        
        Returns dict with:
            'action': 'search' | 'use_context'
            'reason': explanation
            'context_needed': bool
        """
        query_lower = query.lower().strip()
        
        # If no history, must search
        if not has_history or not last_context:
            return {
                'action': 'search',
                'reason': 'No previous conversation history',
                'context_needed': False
            }
        
        # Get previous context
        previous_query = last_context.get('query', '')
        previous_response_preview = last_context.get('response', '')[:500]  # First 500 chars for context
        
        # Use AI to intelligently decide
        prompt = f"""You are an intelligent query router for a SEBI information agent. Analyze whether the current query needs a NEW web search or can use PREVIOUS context.

**Previous Query:** "{previous_query}"

**Previous Response Preview:**
{previous_response_preview}

**Current Query:** "{query}"

**Decision Criteria:**

Use PREVIOUS context if:
- Query asks to reformat/transform previous answer (e.g., "in email format", "make it shorter")
- Query extracts subset of previous data (e.g., "only key points", "just the dates")
- Query references previous content (e.g., "from above", "that response", "the previous answer")
- Query asks for clarification of previous response
- Query modifies presentation of existing data

Requires NEW search if:
- Query asks about a DIFFERENT SEBI topic
- Query needs updated or additional information not in previous response
- Query is about a new circular, regulation, or notification
- No clear reference to previous content

**Instructions:**
1. Analyze the relationship between current and previous queries
2. Determine if current query can be satisfied with existing data
3. Respond with ONLY one word: SEARCH or USE_CONTEXT

**Response:**"""

        try:
            decision = await self.ai.call_genai(prompt, temperature=0.1, max_tokens=20)
            decision_clean = decision.strip().upper()
            
            # Parse AI decision
            if 'USE_CONTEXT' in decision_clean or 'CONTEXT' in decision_clean:
                return {
                    'action': 'use_context',
                    'reason': 'AI determined query can be satisfied with previous context',
                    'context_needed': True
                }
            elif 'SEARCH' in decision_clean:
                return {
                    'action': 'search',
                    'reason': 'AI determined query requires new SEBI search',
                    'context_needed': False
                }
            else:
                # Unparseable response - use heuristic fallback
                raise ValueError(f"Unparseable AI response: {decision}")
                
        except Exception as e:
            # Minimal fallback heuristic only when AI fails
            context_indicators = ['above', 'previous', 'that', 'this', 'it', 'earlier', 'only', 'just', 'key', 'make', 'format', 'convert', 'give me', 'show me']
            has_context_ref = any(indicator in query_lower for indicator in context_indicators)
            is_short_query = len(query_lower.split()) <= 10
            
            if has_context_ref and is_short_query:
                return {
                    'action': 'use_context',
                    'reason': f'Fallback heuristic (AI error: {str(e)}): detected context reference',
                    'context_needed': True
                }
            else:
                return {
                    'action': 'search',
                    'reason': f'Fallback heuristic (AI error: {str(e)}): treating as new query',
                    'context_needed': False
                }
    
    async def _detect_email_request(self, query: str) -> Optional[List[str]]:
        """
        AI-powered detection of email requests and extraction of email addresses.
        
        Returns:
            List of email addresses if email is requested, None otherwise
        """
        # First, try regex extraction (fast and reliable for email addresses)
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        emails_found = re.findall(email_pattern, query)
        
        # If no emails found, no point checking intent
        if not emails_found:
            return None
        
        # Use AI to intelligently determine if user wants to send email
        prompt = f"""Analyze this user query and determine if they want to send an email.

**User Query:** "{query}"

**Email addresses detected:** {', '.join(emails_found)}

**Instructions:**
Determine if the user is requesting to:
- Send the report/information via email
- Email the results to someone
- Share via email
- Mail the content

Respond with ONLY one word:
- YES (if user wants to send email)
- NO (if user is just mentioning email but not requesting to send)

**Response:**"""

        try:
            decision = await self.ai.call_genai(prompt, temperature=0.1, max_tokens=10)
            decision_clean = decision.strip().upper()
            
            if 'YES' in decision_clean:
                return list(set(emails_found))  # Remove duplicates
            else:
                return None
                
        except Exception as e:
            # Fallback: if AI fails, use simple heuristic
            query_lower = query.lower()
            email_keywords = ['send email', 'email', 'send to', 'mail to', 'send me', 'email me', 'mail me', 'send an email']
            has_email_intent = any(keyword in query_lower for keyword in email_keywords)
            
            if has_email_intent and emails_found:
                return list(set(emails_found))
            
            return None
    
    def _get_last_context(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get the last query context from conversation history."""
        if session_id and session_id in self.conversation_history:
            history = self.conversation_history[session_id]
            if history:
                return history[-1]
        return None
    
    def _store_context(self, session_id: str, query: str, response: str, search_results: List[Dict] = None):
        """Store query and response in conversation history."""
        if not session_id:
            return
        
        if session_id not in self.conversation_history:
            self.conversation_history[session_id] = []
        
        # Keep only last 5 interactions to manage memory
        if len(self.conversation_history[session_id]) >= 5:
            self.conversation_history[session_id].pop(0)
        
        self.conversation_history[session_id].append({
            'query': query,
            'response': response,
            'search_results': search_results,
            'timestamp': asyncio.get_event_loop().time()
        })
    
    async def process_query(self, query: str, session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Process user query with dynamic tool selection.
        
        Workflow:
        1. Check if user wants to send email
        2. Analyze query intent using AI
        3. Dynamically decide: search SEBI OR use context OR hybrid
        4. Execute appropriate tool(s)
        5. Store context for future queries
        6. Send email if requested
        """
        thinking_steps = []
        
        thinking_steps.append({
            "type": "thinking",
            "content": f"🔍 Analyzing query intent: '{query}'"
        })
        
        # Check if user is requesting email
        email_recipients = await self._detect_email_request(query)
        
        # Get conversation history
        has_history = bool(session_id and session_id in self.conversation_history and self.conversation_history[session_id])
        last_context = self._get_last_context(session_id) if has_history else None
        
        # Use AI to determine the right action
        intent_analysis = await self._analyze_query_intent(query, has_history, last_context)
        
        thinking_steps.append({
            "type": "thinking",
            "content": f"🎯 Decision: {intent_analysis['action'].upper()} - {intent_analysis['reason']}"
        })
        
        # Route to appropriate handler based on AI decision
        if intent_analysis['action'] == 'use_context' and has_history:
            return await self._handle_follow_up(query, session_id, thinking_steps)
        
        # New query: proceed with search
        provider = self._search_provider()
        if provider == "free_ollama":
            provider_label = "Ollama free web search"
        elif provider == "free_duckduckgo":
            provider_label = "DuckDuckGo free web search"
        else:
            provider_label = "Perplexity"
        search_tool_name = self._search_tool_name()

        if not self._provider_configured():
            if provider == "free_ollama":
                missing = "SEBI_WEB_SEARCH_PROVIDER=free_ollama but OLLAMA_API_KEY is missing"
            elif provider == "free_duckduckgo":
                missing = "SEBI_WEB_SEARCH_PROVIDER=free_duckduckgo but ddgs package is not installed"
            else:
                missing = "SEBI_WEB_SEARCH_PROVIDER=perplexity but PERPLEXITY_API_KEY is missing"
            return self._format_error_response(query, missing, session_id, thinking_steps)

        thinking_steps.append({
            "type": "thinking",
            "content": "🔎 Initiating SEBI website search"
        })
        
        # Step 1: Search SEBI website using Perplexity
        thinking_steps.append({
            "type": "tool_call",
            "content": f"Searching SEBI website via {provider_label} for relevant documents",
            "tool_name": search_tool_name,
            "tool_input": f"Query: {query}, Domain: https://www.sebi.gov.in/"
        })
        
        try:
            search_results = await self.search.search_sebi(query, max_results=10)
        except Exception as e:
            thinking_steps.append({
                "type": "tool_result",
                "content": f"❌ Search error: {str(e)}",
                "tool_name": search_tool_name
            })
            return self._format_error_response(query, str(e), session_id, thinking_steps)
        
        thinking_steps.append({
            "type": "tool_result",
            "content": f"✅ Found {len(search_results)} relevant documents from SEBI website",
            "tool_name": search_tool_name
        })
        
        if not search_results:
            response = self._format_no_results(query)
            return {
                "response": response,
                "notifications": [],
                "session_id": session_id,
                "thinking_steps": thinking_steps
            }
        
        # Step 2: Use PWC LLM to analyze and format results
        thinking_steps.append({
            "type": "thinking",
            "content": "🤖 Analyzing documents with PWC LLM to extract key points and insights"
        })
        
        thinking_steps.append({
            "type": "tool_call",
            "content": f"Summarizing and extracting key points from {len(search_results)} documents",
            "tool_name": "pwc_llm_analyzer",
            "tool_input": f"Processing {len(search_results)} SEBI documents"
        })
        
        try:
            summary = await self.ai.extract_key_points_and_format(search_results, query)
        except Exception as e:
            thinking_steps.append({
                "type": "tool_result",
                "content": f"⚠️ AI summarization error: {str(e)}, providing basic summary",
                "tool_name": "pwc_llm_analyzer"
            })
            summary = self._create_basic_summary_from_perplexity(search_results, query)
        
        thinking_steps.append({
            "type": "tool_result",
            "content": "✅ Successfully analyzed and formatted SEBI documents",
            "tool_name": "pwc_llm_analyzer"
        })
        
        # Step 3: Format final response
        response = self._format_response(query, search_results, summary)
        
        # Store context for future follow-ups
        self._store_context(session_id, query, response, search_results)
        
        # Format notifications for the response
        notifications = []
        for result in search_results[:10]:
            notifications.append({
                'title': result.get('title', 'N/A'),
                'date': result.get('date', 'Date not available'),
                'link': result.get('url', '#'),
                'snippet': result.get('snippet', '')[:200] if result.get('snippet') else None
            })
        
        # Handle email request if detected
        email_status = None
        if email_recipients:
            thinking_steps.append({
                "type": "thinking",
                "content": f"📧 Detected email request to: {', '.join(email_recipients)}"
            })
            
            thinking_steps.append({
                "type": "tool_call",
                "content": f"Sending SEBI report via email to {len(email_recipients)} recipient(s)",
                "tool_name": "email_sender",
                "tool_input": f"Recipients: {', '.join(email_recipients)}"
            })
            
            try:
                email_result = await self.send_email_report(
                    recipients=email_recipients,
                    query=query,
                    summary=summary,
                    search_results=search_results
                )
                
                if email_result["success"]:
                    thinking_steps.append({
                        "type": "tool_result",
                        "content": f"✅ {email_result['message']}",
                        "tool_name": "email_sender"
                    })
                    email_status = {
                        "sent": True,
                        "message": email_result['message'],
                        "recipients": email_recipients
                    }
                    # Add email confirmation to response
                    response += f"\n\n---\n\n## ✉️ Email Sent\n\n✅ Report successfully sent to:\n"
                    for recipient in email_recipients:
                        response += f"- {recipient}\n"
                else:
                    thinking_steps.append({
                        "type": "tool_result",
                        "content": f"❌ Email failed: {email_result.get('error', 'Unknown error')}",
                        "tool_name": "email_sender"
                    })
                    email_status = {
                        "sent": False,
                        "error": email_result.get('error', 'Unknown error')
                    }
                    response += f"\n\n---\n\n## ⚠️ Email Error\n\n❌ Failed to send email: {email_result.get('error', 'Unknown error')}\n"
            
            except Exception as e:
                thinking_steps.append({
                    "type": "tool_result",
                    "content": f"❌ Email error: {str(e)}",
                    "tool_name": "email_sender"
                })
                email_status = {
                    "sent": False,
                    "error": str(e)
                }
                response += f"\n\n---\n\n## ⚠️ Email Error\n\n❌ Failed to send email: {str(e)}\n"
        
        result = {
            "response": response,
            "notifications": notifications,
            "session_id": session_id,
            "thinking_steps": thinking_steps
        }
        
        if email_status:
            result["email_status"] = email_status
        
        return result
    
    async def _handle_follow_up(self, query: str, session_id: str, thinking_steps: List[Dict]) -> Dict[str, Any]:
        """
        Handle follow-up queries using previous context without new search.
        """
        last_context = self._get_last_context(session_id)
        
        if not last_context:
            thinking_steps.append({
                "type": "thinking",
                "content": "⚠️ No previous context found - treating as new query"
            })
            return await self.process_query(query, session_id)
        
        # Check if user is requesting email
        email_recipients = await self._detect_email_request(query)
        
        previous_query = last_context.get('query', 'previous query')
        previous_response = last_context.get('response', '')
        search_results = last_context.get('search_results', [])
        
        thinking_steps.append({
            "type": "tool_call",
            "content": f"Reformatting previous response about: '{previous_query}'",
            "tool_name": "context_processor",
            "tool_input": f"Follow-up query: {query}"
        })
        
        # Use AI to reformat/process the previous response
        try:
            reformatted = await self.ai.reformat_response(previous_response, query, previous_query)
            
            thinking_steps.append({
                "type": "tool_result",
                "content": "✅ Successfully reformatted previous response",
                "tool_name": "context_processor"
            })
            
        except Exception as e:
            thinking_steps.append({
                "type": "tool_result",
                "content": f"⚠️ Reformat error: {str(e)}, using basic reformatting",
                "tool_name": "context_processor"
            })
            reformatted = self._basic_reformat(previous_response, query)
        
        # Store the follow-up context
        self._store_context(session_id, query, reformatted, search_results)
        
        # Format notifications from previous search results
        notifications = []
        if search_results:
            for result in search_results[:10]:
                notifications.append({
                    'title': result.get('title', 'N/A'),
                    'date': result.get('date', 'Date not available'),
                    'link': result.get('url', '#'),
                    'snippet': result.get('snippet', '')[:200] if result.get('snippet') else None
                })
        
        # Handle email request if detected
        email_status = None
        if email_recipients:
            thinking_steps.append({
                "type": "thinking",
                "content": f"📧 Detected email request to: {', '.join(email_recipients)}"
            })
            
            thinking_steps.append({
                "type": "tool_call",
                "content": f"Sending SEBI report via email to {len(email_recipients)} recipient(s)",
                "tool_name": "email_sender",
                "tool_input": f"Recipients: {', '.join(email_recipients)}"
            })
            
            try:
                email_result = await self.send_email_report(
                    recipients=email_recipients,
                    query=previous_query,
                    summary=reformatted,
                    search_results=search_results
                )
                
                if email_result["success"]:
                    thinking_steps.append({
                        "type": "tool_result",
                        "content": f"✅ {email_result['message']}",
                        "tool_name": "email_sender"
                    })
                    email_status = {
                        "sent": True,
                        "message": email_result['message'],
                        "recipients": email_recipients
                    }
                    reformatted += f"\n\n---\n\n## ✉️ Email Sent\n\n✅ Report successfully sent to:\n"
                    for recipient in email_recipients:
                        reformatted += f"- {recipient}\n"
                else:
                    thinking_steps.append({
                        "type": "tool_result",
                        "content": f"❌ Email failed: {email_result.get('error', 'Unknown error')}",
                        "tool_name": "email_sender"
                    })
                    email_status = {
                        "sent": False,
                        "error": email_result.get('error', 'Unknown error')
                    }
                    reformatted += f"\n\n---\n\n## ⚠️ Email Error\n\n❌ Failed to send email: {email_result.get('error', 'Unknown error')}\n"
            
            except Exception as e:
                thinking_steps.append({
                    "type": "tool_result",
                    "content": f"❌ Email error: {str(e)}",
                    "tool_name": "email_sender"
                })
                email_status = {
                    "sent": False,
                    "error": str(e)
                }
                reformatted += f"\n\n---\n\n## ⚠️ Email Error\n\n❌ Failed to send email: {str(e)}\n"
        
        result = {
            "response": reformatted,
            "notifications": notifications,
            "session_id": session_id,
            "thinking_steps": thinking_steps
        }
        
        if email_status:
            result["email_status"] = email_status
        
        return result
    
    def _basic_reformat(self, content: str, query: str) -> str:
        """
        Emergency fallback reformatting when AI service is completely unavailable.
        Uses simple text processing as last resort.
        """
        query_lower = query.lower()
        
        # Try to intelligently extract based on query intent
        # This is a FALLBACK - normally AI handles this
        
        # Extract key points if requested
        if any(word in query_lower for word in ['only', 'just', 'key', 'main', 'important', 'points']):
            # Try to find key points section
            if '🔑 Key Points:' in content or '## Key Points' in content or '# Key Points' in content:
                lines = content.split('\n')
                key_section = []
                in_key_section = False
                
                for line in lines:
                    if any(marker in line for marker in ['🔑 Key Points', '## Key Points', '# Key Points']):
                        in_key_section = True
                        key_section.append(line)
                        continue
                    
                    if in_key_section:
                        # Stop at next major section
                        if (line.startswith('##') or line.startswith('# ')) and 'Key Points' not in line:
                            break
                        if line.strip().startswith('📚') or line.strip().startswith('---'):
                            break
                        key_section.append(line)
                
                if key_section:
                    return '\n'.join(key_section) + "\n\n---\n*Emergency fallback: Extracted from previous response*"
            
            # Fallback: extract numbered/bulleted items
            lines = content.split('\n')
            key_lines = [line for line in lines if line.strip() and (
                line.strip().startswith(('-', '•', '*')) or 
                any(line.strip().startswith(f"{i}.") for i in range(1, 20))
            )]
            if key_lines:
                return "# Key Points\n\n" + '\n'.join(key_lines[:20]) + "\n\n---\n*Emergency fallback: Extracted key items*"
        
        # Email format (with typo tolerance)
        if any(kw in query_lower for kw in ['email', 'emai', 'emal', 'mail']):
            return f"""Subject: SEBI Circular Information

Dear Recipient,

{content}

Best regards,
SEBI Circular Agent

---
*Emergency fallback: Generated email format*
"""
        
        # Shorter format
        if any(word in query_lower for word in ['short', 'brief', 'simpl', 'concise']):
            lines = content.split('\n')
            important_lines = [line for line in lines if line.strip() and 
                             not line.startswith('---') and 
                             not line.strip().startswith('*')][:20]
            return "# Brief Summary\n\n" + '\n'.join(important_lines) + "\n\n---\n*Emergency fallback: Shortened version*"
        
        # Default: return content with fallback note
        return f"""{content}

---
⚠️ **Emergency Fallback Mode**
AI service unavailable. Content presented as-is from previous response.
"""
    
    def _create_basic_summary_from_perplexity(self, search_results: List[Dict[str, Any]], query: str) -> str:
        """Create a basic summary when PWC LLM is unavailable."""
        if not search_results:
            return "No documents found to summarize."
        
        summary_parts = []
        summary_parts.append("## 📊 Quick Summary\n")
        summary_parts.append(f"Found {len(search_results)} relevant documents from SEBI website.\n\n")
        
        summary_parts.append("## 🔑 Key Documents\n")
        for i, result in enumerate(search_results[:5], 1):
            title = result.get('title', 'Unknown')
            date = result.get('date', 'Date not available')
            snippet = result.get('snippet', '')
            
            summary_parts.append(f"### {i}. {title}\n")
            summary_parts.append(f"**Published:** {date}\n\n")
            
            if snippet:
                summary_parts.append(f"{snippet}\n\n")
        
        summary_parts.append("---\n")
        summary_parts.append("*Note: AI summarization temporarily unavailable. Please review the documents directly using the links provided.*\n")
        
        return "".join(summary_parts)
    
    def _format_response(self, query: str, search_results: List[Dict[str, Any]], summary: str) -> str:
        """Format the final response with search results and summary."""
        response_parts = []
        
        response_parts.append("# 📈 SEBI Circular Analysis Report\n")
        response_parts.append(f"**Query:** {query}\n")
        response_parts.append(f"**Source:** Securities and Exchange Board of India Official Website\n")
        response_parts.append("---\n\n")
        
        # Add the AI-generated summary
        response_parts.append(summary)
        response_parts.append("\n\n---\n\n")
        
        # Add source documents section
        response_parts.append("## 📚 Source Documents\n\n")
        for i, result in enumerate(search_results[:10], 1):
            title = result.get('title', 'N/A')
            url = result.get('url', '#')
            date = result.get('date', 'Date not available')
            
            response_parts.append(f"{i}. **[{title}]({url})**\n")
            response_parts.append(f"   - 📅 Published: {date}\n\n")
        
        response_parts.append("\n---\n\n")
        response_parts.append("## ℹ️ Disclaimer\n")
        response_parts.append("*All information is sourced from the official SEBI website (https://www.sebi.gov.in/). ")
        response_parts.append("Please refer to the original documents for complete and authoritative information. ")
        response_parts.append("This summary is generated using AI and should be verified with official sources.*\n\n")
        response_parts.append("🔗 [Visit SEBI Website](https://www.sebi.gov.in/) | ")
        response_parts.append("[Search SEBI Circulars](https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=1&ssid=1&smid=0)\n")
        
        return "".join(response_parts)
    
    def _format_no_results(self, query: str) -> str:
        """Format response when no results are found."""
        return f"""# 📈 SEBI Circular Search

**Query:** {query}
**Source:** Securities and Exchange Board of India Official Website

---

## ⚠️ No Matching Documents Found

No relevant SEBI circulars or notifications were found for your query.

### 💡 Suggestions:
- Try using different keywords or phrases
- Use specific terms like:
  - "LODR" instead of "listing requirements"
  - "mutual fund" or "scheme"
  - Specific circular numbers if known (e.g., "SEBI/HO/IMD/DF2/CIR/2023/180")
- Search for broader topics first, then narrow down
- Check for official terminology used by SEBI

### 🔗 Alternative Resources:
- [Browse All SEBI Circulars](https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=1&ssid=1&smid=0)
- [SEBI Master Circulars](https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doMasterCircular=yes)
- [SEBI FAQs](https://www.sebi.gov.in/faq.html)
- [SEBI Homepage](https://www.sebi.gov.in/)

---
*Try refining your search or explore the SEBI website directly using the links above.*
"""
    
    def _format_error_response(self, query: str, error: str, session_id: Optional[str], thinking_steps: List[Dict]) -> Dict[str, Any]:
        """Format error response."""
        error_message = f"""# ❌ Search Error

**Query:** {query}

---

## Error Details
An error occurred while searching the SEBI website:

```
{error}
```

### Possible Causes:
- Network connectivity issues
- API service temporarily unavailable
- Invalid API credentials
- Rate limiting

### What You Can Do:
1. **Try again** - The issue might be temporary
2. **Check your connection** - Ensure internet connectivity
3. **Visit SEBI directly** - [SEBI Website](https://www.sebi.gov.in/)
4. **Contact support** - If the problem persists

---
*We apologize for the inconvenience. Please try again in a few moments.*
"""
        
        return {
            "response": error_message,
            "notifications": [],
            "session_id": session_id,
            "thinking_steps": thinking_steps
        }


sebi_agent = SEBICircularAgent()
