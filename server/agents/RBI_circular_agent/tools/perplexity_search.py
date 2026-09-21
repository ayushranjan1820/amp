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
    print("⚠️ perplexity module not installed - RBI Perplexity search will be unavailable")

from pathlib import Path

if not os.getenv("_AGENTSERVER_RUNNING"):
    from user_config import load_dotenv_then_scrub_pwc
    load_dotenv_then_scrub_pwc(dotenv_path=Path(__file__).parent.parent.parent.parent / ".env")


TRUSTED_RBI_DOMAINS = [
    "rbi.org.in",
    "website.rbi.org.in",
    "rbidocs.rbi.org.in",
    "gazette.rbi.org.in",
]

TRUSTED_LEGAL_DOMAINS = [
    "rbi.org.in",
    "taxguru.in",
    "moneycontrol.com",
    "livemint.com",
    "economictimes.indiatimes.com",
    "indiankanoon.org",
    "lawstreet.co",
    "barandbench.com",
]


class PerplexitySearchService:
    """Service to search for RBI information using Perplexity API."""
    
    def __init__(self):
        self.client = None
        provider = self._provider()
        if provider == "free_ollama":
            if not self._ollama_api_key():
                print("⚠️ OLLAMA_API_KEY not found - RBI Ollama free search disabled")
            return
        if provider == "free_duckduckgo":
            if not DDGS_AVAILABLE:
                print("⚠️ ddgs package not installed - RBI DuckDuckGo search disabled")
            return

        if not PERPLEXITY_AVAILABLE:
            print("⚠️ Perplexity SDK not available - search functionality limited")
            return

        api_key = os.getenv("PERPLEXITY_API_KEY")
        if not api_key:
            print("⚠️ PERPLEXITY_API_KEY not found - RBI Perplexity search disabled")
            return
        self.client = Perplexity(api_key=api_key)

    @staticmethod
    def _provider() -> str:
        raw = (os.getenv("RBI_WEB_SEARCH_PROVIDER") or "perplexity").strip().lower()
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
    def _search_duckduckgo_sync(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        if not DDGS_AVAILABLE:
            return []
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max(1, min(10, int(max_results or 5)))))
        except Exception as e:
            print(f"  ⚠️ DuckDuckGo search query failed: {str(e)[:100]}")
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
    
    def _sort_and_filter_by_date(self, results: List[Dict[str, Any]], current_year: int) -> List[Dict[str, Any]]:
        """Sort results by date (newest first) and prioritize recent ones."""
        import re
        from datetime import datetime
        
        def parse_date(date_str):
            if not date_str:
                return None
            for fmt in ['%Y-%m-%d', '%B %d, %Y', '%d %B %Y', '%d-%m-%Y', '%d/%m/%Y', '%b %d, %Y', '%d %b %Y']:
                try:
                    return datetime.strptime(date_str.strip(), fmt)
                except (ValueError, AttributeError):
                    continue
            year_match = re.search(r'(20\d{2})', str(date_str))
            if year_match:
                return datetime(int(year_match.group(1)), 1, 1)
            return None
        
        for r in results:
            r['_parsed_date'] = parse_date(r.get('date'))
        
        recent = [r for r in results if r['_parsed_date'] and r['_parsed_date'].year >= current_year - 1]
        older = [r for r in results if not r['_parsed_date'] or r['_parsed_date'].year < current_year - 1]
        
        recent.sort(key=lambda x: x['_parsed_date'] or datetime.min, reverse=True)
        older.sort(key=lambda x: x['_parsed_date'] or datetime.min, reverse=True)
        
        combined = recent + older
        
        for r in combined:
            r.pop('_parsed_date', None)
        
        if recent:
            print(f"📅 Date filter: {len(recent)} recent results ({current_year}/{current_year-1}), {len(older)} older")
        else:
            print(f"⚠️ No recent {current_year}/{current_year-1} results found — showing all {len(older)} results sorted by date")
        
        return combined
    
    def _detect_language(self, query: str) -> str:
        """Detect requested language from query, default to English."""
        query_lower = query.lower()
        
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
        
        return 'english'
    
    def _extract_topic_keywords(self, query: str) -> str:
        """Extract the core regulatory topic from the user query, fixing common typos."""
        query_lower = query.lower()
        
        common_typos = {
            'circulers': 'circulars',
            'circuler': 'circular',
            'guidelins': 'guidelines',
            'guidlines': 'guidelines',
            'regulaions': 'regulations',
            'regulaton': 'regulation',
            'notificaions': 'notifications',
            'lendng': 'lending',
            'lenidng': 'lending',
            'digtial': 'digital',
            'digtal': 'digital',
            'complance': 'compliance',
            'compiance': 'compliance',
            'requirments': 'requirements',
            'requiremnts': 'requirements',
        }
        
        words = query_lower.split()
        corrected_words = [common_typos.get(w, w) for w in words]
        query_lower = ' '.join(corrected_words)
        
        stop_words = {'what', 'are', 'the', 'latest', 'recent', 'new', 'current', 'guidelines', 
                      'circulars', 'circular', 'notifications', 'regulations', 'rules', 'for', 'about', 
                      'on', 'regarding', 'related', 'to', 'of', 'in', 'rbi', 'reserve', 'bank',
                      'india', 'please', 'tell', 'me', 'find', 'show', 'get', 'list', 'all',
                      'can', 'you', 'i', 'want', 'need', 'know', 'is', 'there', 'any', 'a', 'an'}
        topic_words = [w for w in corrected_words if w not in stop_words and len(w) > 1]
        return ' '.join(topic_words) if topic_words else query
    
    def _generate_search_queries(self, query: str, topic: str, current_year: int, current_month: str, needs_recency: bool) -> list:
        """
        Generate multiple targeted search queries for comprehensive coverage.
        Returns list of dicts: {'query': str, 'domain_mode': 'rbi'|'legal'|'open'}
        """
        queries = []
        
        year_context = f"in {current_year} or {current_year - 1}" if needs_recency else ""
        recency_prefix = f"latest {current_year}" if needs_recency else ""
        
        queries.append({
            'query': (
                f"Find the MOST RECENT circulars, notifications, and master directions "
                f"about '{query}' from Reserve Bank of India rbi.org.in "
                f"published {year_context}. "
                f"Include circular reference number, date, and URL for each."
            ),
            'domain_mode': 'rbi'
        })
        
        queries.append({
            'query': (
                f"RBI master direction {topic} {recency_prefix} "
                f"consolidated directions regulations framework {year_context}. "
                f"Include reference number, date of issue, and URL."
            ),
            'domain_mode': 'rbi'
        })
        
        queries.append({
            'query': (
                f"RBI {topic} {recency_prefix} circular notification guidelines "
                f"governance capital adequacy risk management "
                f"prudential norms compliance requirements {year_context}. "
                f"Include reference number, date, and URL."
            ),
            'domain_mode': 'legal'
        })
        
        queries.append({
            'query': (
                f"RBI {topic} directions {current_year} {current_year - 1} {current_year - 2} "
                f"consolidated updated amended framework regulatory timeline evolution. "
                f"Show the complete regulatory history and latest amendments. "
                f"Include reference number, date, and URL."
            ),
            'domain_mode': 'open'
        })
        
        return queries
    
    async def _execute_single_search(self, query: str, max_results: int = 5, domain_mode: str = 'rbi') -> List[Dict[str, Any]]:
        """
        Execute a single Perplexity search and return parsed results.
        domain_mode: 'rbi' (official RBI only), 'legal' (RBI + trusted legal/financial sites), 'open' (no filter)
        """
        try:
            provider = self._provider()
            if provider == "free_ollama":
                api_key = self._ollama_api_key()
                if not api_key:
                    return []
                base_url = (os.getenv("OLLAMA_WEB_SEARCH_BASE_URL") or "https://ollama.com").rstrip("/")
                endpoint = f"{base_url}/api/web_search"
                payload = {
                    "query": query,
                    "max_results": max(1, min(10, int(max_results or 5))),
                }
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }
                async with httpx.AsyncClient(timeout=40.0) as client:
                    resp = await client.post(endpoint, json=payload, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()

                out: List[Dict[str, Any]] = []
                for result in data.get("results") or []:
                    if not isinstance(result, dict):
                        continue
                    out.append({
                        'title': (result.get('title') or '').strip(),
                        'url': (result.get('url') or '').strip(),
                        'date': (result.get('date') or '').strip(),
                        'snippet': (result.get('content') or result.get('snippet') or '').strip(),
                        'content': (result.get('content') or '').strip(),
                    })
                return out
            if provider == "free_duckduckgo":
                return await asyncio.to_thread(self._search_duckduckgo_sync, query, max_results)

            search_kwargs = {
                "query": query,
                "max_results": max_results,
            }
            if domain_mode == 'rbi':
                search_kwargs["search_domain_filter"] = TRUSTED_RBI_DOMAINS
            elif domain_mode == 'legal':
                search_kwargs["search_domain_filter"] = TRUSTED_LEGAL_DOMAINS
            search = self.client.search.create(**search_kwargs)
            
            try:
                from cost_tracker import log_cost_event
                log_cost_event(event_type="perplexity_search", agent_name="RBI Circular Agent", metadata={"query": query[:100]})
            except Exception:
                pass
            
            results = []
            for result in search.results:
                results.append({
                    'title': result.title,
                    'url': result.url,
                    'date': result.date if hasattr(result, 'date') else None,
                    'snippet': result.snippet if hasattr(result, 'snippet') else None,
                    'content': result.content if hasattr(result, 'content') else None,
                })
            return results
        except Exception as e:
            print(f"  ⚠️ Search query failed: {str(e)[:100]}")
            return []
    
    async def search_rbi(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        Search for RBI information using Perplexity API across multiple trusted sources.
        Uses a multi-domain strategy:
        - rbi.org.in (official RBI website) for direct circulars
        - Trusted legal/financial sites (taxguru, moneycontrol, livemint, etc.) for analysis & coverage
        - Open web for regulatory timeline and evolution
        Makes 4 targeted searches, deduplicates, and sorts by date (newest first).
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
            import asyncio
            language = self._detect_language(query)
            print(f"🔍 Searching RBI website for: '{query}'")
            if provider == 'free_ollama':
                provider_label = 'Ollama free web search'
            elif provider == 'free_duckduckgo':
                provider_label = 'DuckDuckGo free web search'
            else:
                provider_label = 'Perplexity'
            print(f"🔎 Search provider: {provider_label}")
            print(f"🌐 Response language: {language.title()}")
            
            from datetime import datetime
            current_year = datetime.now().year
            current_month = datetime.now().strftime("%B %Y")
            
            query_lower = query.lower()
            recency_words = ['latest', 'recent', 'new', 'current', 'today', 'this year', 'this month', str(current_year)]
            needs_recency = any(w in query_lower for w in recency_words) or not any(str(y) in query_lower for y in range(2010, current_year + 1))
            
            topic = self._extract_topic_keywords(query)
            search_queries = self._generate_search_queries(query, topic, current_year, current_month, needs_recency)
            
            print(f"📍 Running {len(search_queries)} targeted searches for comprehensive coverage")
            print(f"📅 Recency filter: {'Yes - prioritizing ' + str(current_year) + ' results' if needs_recency else 'No - using user-specified timeframe'}")
            print(f"🎯 Core topic: '{topic}'")
            
            all_results = []
            per_search_limit = max(5, max_results // len(search_queries) + 2)
            search_tasks = []
            for sq in search_queries:
                search_tasks.append(self._execute_single_search(
                    sq['query'], 
                    max_results=per_search_limit, 
                    domain_mode=sq['domain_mode']
                ))
            
            domain_labels = {sq['domain_mode'] for sq in search_queries}
            print(f"🌐 Search domains: {', '.join(sorted(domain_labels))}")
            search_outputs = await asyncio.gather(*search_tasks, return_exceptions=True)
            
            for i, output in enumerate(search_outputs):
                if isinstance(output, Exception):
                    print(f"  ⚠️ Search {i+1} ({search_queries[i]['domain_mode']}) failed: {str(output)[:100]}")
                    continue
                print(f"  ✅ Search {i+1} ({search_queries[i]['domain_mode']}): {len(output)} results")
                all_results.extend(output)
            
            seen_urls = set()
            results = []
            for r in all_results:
                url = r.get('url', '')
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    results.append(r)
                    print(f"  ✓ {r.get('title', 'N/A')}")
                    print(f"    🔗 {url}")
                    if r.get('date'):
                        print(f"    📅 {r['date']}")
                    url_lower = url.lower()
                    if 'rbi.org.in' in url_lower:
                        r['source_type'] = 'official'
                        print(f"    ⭐ Official RBI source")
                    elif any(d in url_lower for d in ['taxguru.in', 'indiankanoon.org', 'lawstreet.co', 'barandbench.com']):
                        r['source_type'] = 'legal'
                        print(f"    📜 Trusted legal source")
                    elif any(d in url_lower for d in ['moneycontrol.com', 'livemint.com', 'economictimes.indiatimes.com']):
                        r['source_type'] = 'financial_media'
                        print(f"    📰 Trusted financial media")
                    else:
                        r['source_type'] = 'web'
                        print(f"    🌐 Web source")
            
            if needs_recency and results:
                results = self._sort_and_filter_by_date(results, current_year)
            
            print(f"✅ Found {len(results)} unique results (from {len(all_results)} total across {len(search_queries)} searches)")
            return results[:max_results]
            
        except Exception as e:
            error_msg = f"Error during Perplexity search: {str(e)}"
            print(f"❌ {error_msg}")
            return []
    
    async def get_detailed_info(self, query: str, search_results: List[Dict[str, Any]]) -> str:
        """
        Extract content from RBI links and provide detailed information based on that content.
        """
        if not self.client:
            return "Perplexity client not initialized. Please configure PERPLEXITY_API_KEY."
            
        if not search_results:
            return "No search results to analyze."
        
        try:
            language = self._detect_language(query)
            
            print(f"📥 Extracting content from {len(search_results)} RBI links...")
            
            urls = [r['url'] for r in search_results]
            
            extracted_contents = []
            for idx, result in enumerate(search_results, 1):
                url = result['url']
                print(f"  {idx}. Extracting from: {url}")
                
                try:
                    extract_query = f"Extract and provide the complete content from this RBI page: {url}"
                    
                    content_search = self.client.search.create(
                        query=extract_query,
                        max_results=1
                    )
                    
                    try:
                        from cost_tracker import log_cost_event
                        log_cost_event(event_type="perplexity_search", agent_name="RBI Circular Agent", metadata={"query": extract_query[:100]})
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
                return "Could not extract content from any of the RBI links found."
            
            print(f"✅ Successfully extracted content from {len(extracted_contents)} sources")
            
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
            
            final_query = f"""Based on the following content extracted from RBI official website pages:

{chr(10).join(formatted_contexts)}

Answer the user's question: {query}

CRITICAL REQUIREMENTS:
1. Use ONLY the information from the extracted RBI content above
2. Use professional formatting with clear structure, headings, and bullet points
3. Always include: publish date, reference number/circular ID, and key points
4. Format your response naturally based on what the user is asking
5. Use proper markdown formatting for readability
6. Maintain a professional, authoritative tone
7. EVERY point or fact MUST include an inline source link in [Title](URL) format using the source URLs above
8. Do NOT present any information without a clickable reference link

Provide a well-structured, professional response based strictly on the extracted RBI content."""
            
            if language != 'english':
                final_query += f"\n\nIMPORTANT: Respond in {language} language while maintaining professional formatting."
            
            final_search = self.client.search.create(
                query=final_query,
                max_results=1
            )
            
            if final_search.results and hasattr(final_search.results[0], 'content'):
                return final_search.results[0].content
            else:
                response = f"# Information from RBI Website\n\n"
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
