import os
import asyncio
import httpx
from typing import List, Dict, Any

try:
    from ddgs import DDGS
    DDGS_AVAILABLE = True
except ImportError:
    DDGS_AVAILABLE = False

try:
    from perplexity import Perplexity
    PERPLEXITY_AVAILABLE = True
except ImportError:
    PERPLEXITY_AVAILABLE = False
    print("⚠️ perplexity module not installed - SEBI Perplexity search will be unavailable")

from pathlib import Path

if not os.getenv("_AGENTSERVER_RUNNING"):
    from user_config import load_dotenv_then_scrub_pwc
    load_dotenv_then_scrub_pwc(dotenv_path=Path(__file__).parent.parent.parent.parent / ".env")


class PerplexitySearchService:
    """Service to search for SEBI information using Perplexity API."""
    
    def __init__(self):
        self.client = None
        provider = self._provider()
        if provider == "free_ollama":
            if not self._ollama_api_key():
                print("⚠️ OLLAMA_API_KEY not found - SEBI Ollama free search disabled")
            return
        if provider == "free_duckduckgo":
            if not DDGS_AVAILABLE:
                print("⚠️ ddgs package not installed - SEBI DuckDuckGo search disabled")
            return

        if not PERPLEXITY_AVAILABLE:
            print("⚠️ Perplexity SDK not available - SEBI search functionality limited")
            return

        api_key = os.getenv("PERPLEXITY_API_KEY")
        if not api_key:
            print("⚠️ PERPLEXITY_API_KEY not found - SEBI Perplexity search disabled")
            return
        self.client = Perplexity(api_key=api_key)

    @staticmethod
    def _provider() -> str:
        raw = (os.getenv("SEBI_WEB_SEARCH_PROVIDER") or "perplexity").strip().lower()
        if raw in ("free", "free_web", "free_ollama", "ollama", "ollama_free"):
            return "free_ollama"
        if raw in ("free_duckduckgo", "duckduckgo", "duck", "ddg"):
            return "free_duckduckgo"
        return "perplexity"

    @staticmethod
    def _ollama_api_key() -> str:
        return (
            (os.getenv("OLLAMA_API_KEY") or "").strip()
            or (os.getenv("ON_PREM_CLOUD_ACCESS_TOKEN") or "").strip()
            or (os.getenv("OLLAMA_CLOUD_BEARER_TOKEN") or "").strip()
        )

    @staticmethod
    def _search_duckduckgo_sync(query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        if not DDGS_AVAILABLE:
            return []
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max(1, min(10, int(max_results or 10)))))
        except Exception as e:
            print(f"❌ DuckDuckGo search error: {e}")
            return []

        out: List[Dict[str, Any]] = []
        for result in results:
            if not isinstance(result, dict):
                continue
            out.append({
                'title': (result.get('title') or '').strip(),
                'url': (result.get('href') or result.get('url') or '').strip(),
                'date': (result.get('date') or '').strip(),
                'snippet': (result.get('body') or result.get('snippet') or '').strip(),
                'content': (result.get('body') or result.get('content') or '').strip(),
            })
        return out
    
    def _detect_language(self, query: str) -> str:
        """Detect requested language from query, default to English."""
        query_lower = query.lower()
        
        # Language detection patterns
        language_patterns = {
            'hindi': ['in hindi', 'hindi me', 'hindi mein', 'हिंदी में'],
            'tamil': ['in tamil', 'tamil me', 'tamil la'],
            'telugu': ['in telugu', 'telugu lo'],
            'kannada': ['in kannada', 'kannadaalli'],
            'malayalam': ['in malayalam', 'malayalam il'],
            'bengali': ['in bengali', 'bangla te'],
            'marathi': ['in marathi', 'marathi madhe'],
            'gujarati': ['in gujarati', 'gujarati ma'],
            'spanish': ['in spanish', 'en español', 'en espanol'],
            'french': ['in french', 'en français', 'en francais'],
            'german': ['in german', 'auf deutsch'],
            'chinese': ['in chinese', '中文'],
            'japanese': ['in japanese', '日本語'],
        }
        
        for language, patterns in language_patterns.items():
            if any(pattern in query_lower for pattern in patterns):
                return language
        
        return 'english'  # Default
    
    async def search_sebi(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        Search for SEBI information using Perplexity API focused on sebi.gov.in domain.
        """
        provider = self._provider()
        if provider == "perplexity" and not self.client:
            print("❌ Perplexity client not initialized - cannot search")
            return []
        if provider == "free_ollama" and not self._ollama_api_key():
            print("❌ OLLAMA_API_KEY not configured - cannot search")
            return []
        if provider == "free_duckduckgo" and not DDGS_AVAILABLE:
            print("❌ ddgs package is not installed - cannot search")
            return []
            
        try:
            # Detect requested language
            language = self._detect_language(query)
            print(f"🔍 Searching SEBI website for: '{query}'")
            if provider == 'free_ollama':
                provider_label = 'Ollama free web search'
            elif provider == 'free_duckduckgo':
                provider_label = 'DuckDuckGo free web search'
            else:
                provider_label = 'Perplexity'
            print(f"🔎 Search provider: {provider_label}")
            print(f"🌐 Response language: {language.title()}")
            
            # Format query to search specifically on SEBI website
            # Direct Perplexity to find information from SEBI's official website
            enhanced_query = f"Find information about '{query}' from Securities and Exchange Board of India official website sebi.gov.in"
            
            print(f"📍 Search URL focus: https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=1&ssid=1&smid=0")
            
            if provider == "free_ollama":
                api_key = self._ollama_api_key()
                base_url = (os.getenv("OLLAMA_WEB_SEARCH_BASE_URL") or "https://ollama.com").rstrip("/")
                endpoint = f"{base_url}/api/web_search"
                payload = {
                    "query": enhanced_query,
                    "max_results": max(1, min(10, int(max_results or 10))),
                }
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }
                async with httpx.AsyncClient(timeout=40.0) as client:
                    resp = await client.post(endpoint, json=payload, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
                raw_results = []
                for item in data.get("results") or []:
                    if not isinstance(item, dict):
                        continue
                    raw_results.append({
                        'title': (item.get('title') or '').strip(),
                        'url': (item.get('url') or '').strip(),
                        'date': (item.get('date') or '').strip(),
                        'snippet': (item.get('content') or item.get('snippet') or '').strip(),
                        'content': (item.get('content') or '').strip(),
                    })
            elif provider == "free_duckduckgo":
                raw_results = await asyncio.to_thread(self._search_duckduckgo_sync, enhanced_query, max_results)
            else:
                search = self.client.search.create(
                    query=enhanced_query,
                    max_results=max_results,
                    search_domain_filter=["sebi.gov.in"]
                )
            
            try:
                from cost_tracker import log_cost_event
                log_cost_event(event_type="perplexity_search", agent_name="SEBI Circular Agent", metadata={"query": query})
            except Exception:
                pass
            
            results = []
            iterable = raw_results if provider in ("free_ollama", "free_duckduckgo") else search.results
            for result in iterable:
                if provider in ("free_ollama", "free_duckduckgo"):
                    result_data = result
                else:
                    result_data = {
                        'title': result.title,
                        'url': result.url,
                        'date': result.date if hasattr(result, 'date') else None,
                        'snippet': result.snippet if hasattr(result, 'snippet') else None,
                        'content': result.content if hasattr(result, 'content') else None,
                    }
                
                results.append(result_data)
                
                # Print to console for debugging
                print(f"  ✓ {result_data.get('title', 'N/A')}")
                print(f"    🔗 {result_data.get('url', '')}")
                if result_data.get('date'):
                    print(f"    📅 {result_data.get('date')}")
                
                # Prioritize sebi.gov.in URLs
                if 'sebi.gov.in' in (result_data.get('url', '')).lower():
                    print(f"    ⭐ Official SEBI source")
            
            print(f"✅ Found {len(results)} results")
            return results
            
        except Exception as e:
            error_msg = f"Error during Perplexity search: {str(e)}"
            print(f"❌ {error_msg}")
            return []
    
    async def get_detailed_info(self, query: str, search_results: List[Dict[str, Any]]) -> str:
        """
        Extract content from SEBI links and provide detailed information.
        """
        if not self.client:
            return "Perplexity client not initialized. Please configure PERPLEXITY_API_KEY."
            
        if not search_results:
            return "No search results to analyze."
        
        try:
            # Detect requested language
            language = self._detect_language(query)
            
            print(f"📥 Extracting content from {len(search_results)} SEBI links...")
            
            # Extract URLs from search results
            urls = [r['url'] for r in search_results]
            
            # Get content from each URL using Perplexity
            extracted_contents = []
            for idx, result in enumerate(search_results, 1):
                url = result['url']
                print(f"  {idx}. Extracting from: {url}")
                
                # Use Perplexity to extract and summarize content from the specific URL
                try:
                    extract_query = f"Extract and provide the complete content from this SEBI page: {url}"
                    
                    content_search = self.client.search.create(
                        query=extract_query,
                        max_results=1
                    )
                    
                    try:
                        from cost_tracker import log_cost_event
                        log_cost_event(event_type="perplexity_search", agent_name="SEBI Circular Agent", metadata={"query": extract_query[:100]})
                    except Exception:
                        pass
                    
                    if content_search.results:
                        page_content = content_search.results[0].content if hasattr(content_search.results[0], 'content') else None
                        if page_content:
                            extracted_contents.append({
                                'url': url,
                                'title': result['title'],
                                'date': result.get('date'),
                                'content': page_content
                            })
                            print(f"     ✓ Content extracted successfully")
                        else:
                            print(f"     ⚠ No content available")
                except Exception as e:
                    print(f"     ❌ Error extracting from {url}: {str(e)}")
                    continue
            
            if not extracted_contents:
                return "Could not extract content from any of the SEBI links found."
            
            print(f"✅ Successfully extracted content from {len(extracted_contents)} sources")
            
            # Now use the extracted content to answer the user's query
            formatted_contexts = []
            for item in extracted_contents:
                context_text = f"""
SOURCE: {item['title']}
URL: {item['url']}
{f"DATE: {item['date']}" if item.get('date') else ""}

CONTENT:
{item['content']}
"""
                formatted_contexts.append(context_text)
            
            # Create a comprehensive query for final response
            final_query = f"""Based on the following content extracted from SEBI official website pages:

{chr(10).join(formatted_contexts)}

Answer the user's question: {query}

CRITICAL REQUIREMENTS:
1. Use ONLY the information from the extracted SEBI content above
2. Use professional formatting with clear structure, headings, and bullet points
3. Always include: publish date, reference number/circular ID, and key points
4. Format your response naturally based on what the user is asking
5. Use proper markdown formatting for readability
6. Maintain a professional, authoritative tone
7. Cite the source URLs when referencing specific information

Provide a well-structured, professional response based strictly on the extracted SEBI content."""
            
            # Add language instruction if not English
            if language != 'english':
                final_query += f"\n\nIMPORTANT: Respond in {language} language while maintaining professional formatting."
            
            # Get final detailed response from Perplexity
            final_search = self.client.search.create(
                query=final_query,
                max_results=1
            )
            
            if final_search.results and hasattr(final_search.results[0], 'content'):
                return final_search.results[0].content
            else:
                # Fallback: return the extracted content formatted
                response = f"# Information from SEBI Website\n\n"
                for item in extracted_contents:
                    response += f"## {item['title']}\n"
                    response += f"**Source:** {item['url']}\n"
                    if item.get('date'):
                        response += f"**Date:** {item['date']}\n"
                    response += f"\n{item['content']}\n\n---\n\n"
                return response
            
        except Exception as e:
            print(f"❌ Error getting detailed info: {str(e)}")
            return f"Error retrieving detailed information: {str(e)}"


perplexity_search = PerplexitySearchService()
