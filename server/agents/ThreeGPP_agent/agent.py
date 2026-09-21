import asyncio
import re
from typing import Dict, Any, Optional, List
from datetime import datetime

from .ai_service import ai_service
from .tools.inventory_builder import load_inventory, search_index, get_inventory_status, build_full_inventory, parse_query_context, find_latest_meeting
from .tools.inventory_search import search_inventory
from .tools.file_downloader import download_multiple


def is_listing_query(query: str) -> bool:
    q = query.lower()
    return any(kw in q for kw in ['list tdoc', 'list all', 'show tdoc', 'list document', 'how many tdoc', 'all tdocs'])


def is_agenda_item_query(query: str) -> bool:
    q = query.lower()
    return bool(re.search(r'agenda\s*item\s*\d', q)) or bool(re.search(r'ai[\s#]*\d', q))


def is_summary_query(query: str) -> bool:
    q = query.lower()
    return any(w in q for w in ['summarize', 'summary', 'summarise', 'overview', 'highlights', 'what happened', 'key decisions', 'outcomes'])


class ThreeGPPAgent:
    def __init__(self):
        self.ai = ai_service
        self.conversation_history: Dict[str, List[Dict[str, Any]]] = {}

        status = get_inventory_status()
        if status.get("exists"):
            print(f"📡 3GPP Agent initialized - Index: {status['total_files']} files, {status['total_directories']} dirs ({status.get('file_size_mb', 0)}MB)")
        else:
            print("📡 3GPP Agent initialized - No index built yet. Use /api/3gpp/build-inventory to build.")

    async def process_query(self, query: str, session_id: str = "default") -> Dict[str, Any]:
        thinking_steps = []
        start_time = datetime.now()

        thinking_steps.append({
            "type": "thinking",
            "content": f"📡 Analyzing 3GPP query: \"{query}\""
        })

        status = get_inventory_status()
        if not status.get("exists"):
            if status.get("building"):
                return {
                    "success": False,
                    "response": f"The 3GPP file index is currently being built. Progress: {status.get('progress', 'in progress')} — {status.get('files_found', 0)} files found so far. Please try again in a few minutes.",
                    "thinking_steps": thinking_steps
                }

            thinking_steps.append({
                "type": "thinking",
                "content": "No index found. Building full 3GPP FTP index (this is a one-time process)..."
            })

            asyncio.create_task(build_full_inventory())

            return {
                "success": False,
                "response": "I'm building the 3GPP specification file index for the first time. This crawls the entire 3GPP FTP repository to create a searchable directory of all specification files. It typically takes a few minutes. Please try again shortly!",
                "thinking_steps": thinking_steps
            }

        thinking_steps.append({
            "type": "tool_call",
            "content": f"Searching through {status['total_files']} indexed files",
            "tool_name": "index_search",
            "tool_input": query
        })

        listing_mode = is_listing_query(query)
        agenda_item_mode = is_agenda_item_query(query)
        max_results = 50 if listing_mode else 20
        relevant_files = await search_index(query, max_results=max_results)

        if agenda_item_mode and relevant_files:
            thinking_steps.append({
                "type": "thinking",
                "content": "Agenda item query detected — fetching agenda document first to identify topic details"
            })

            ctx = parse_query_context(query)
            agenda_files = [f for f in relevant_files if 'agenda' in f.get('name', '').lower() or 'agenda' in f.get('path', '').lower()]

            if not agenda_files and ctx['wg_dir'] and ctx['meeting_num']:
                from .tools.inventory_builder import find_meeting_name
                data = load_inventory()
                if data:
                    meeting_name = find_meeting_name(data.get('structure', {}), ctx['wg_dir'], ctx['meeting_num'])
                    agenda_search = await search_index(f"{ctx['wg_dir']} {meeting_name} agenda", max_results=10)
                    agenda_files = [f for f in agenda_search if 'agenda' in f.get('name', '').lower() or 'agenda' in f.get('path', '').lower()]

            if not agenda_files:
                agenda_search = await search_index(f"agenda {query}", max_results=10)
                agenda_files = [f for f in agenda_search if 'agenda' in f.get('name', '').lower() or 'agenda' in f.get('path', '').lower()]

            if agenda_files:
                agenda_urls = {f.get('url') for f in agenda_files}
                other_files = [f for f in relevant_files if f.get('url') not in agenda_urls]
                relevant_files = agenda_files[:2] + other_files[:18]

        if not relevant_files:
            thinking_steps.append({
                "type": "tool_result",
                "content": "No matching files found in the index",
                "tool_name": "index_search"
            })

            history = self.conversation_history.get(session_id, [])
            context = ""
            if history:
                last = history[-1]
                context = f"\n\nPrevious context:\nQ: {last.get('query', '')}\nA: {last.get('response', '')[:500]}"

            prompt = f"""You are a 3GPP telecommunications standards expert. The user asked a question but no directly matching files were found in the 3GPP TSG RAN FTP index ({status['total_files']} files indexed).

User Question: {query}
{context}

Provide a helpful response based on your knowledge of 3GPP standards. Explain relevant concepts, point to likely specification numbers (TS/TR documents), and suggest how to find the information in the 3GPP repository at https://www.3gpp.org/ftp/tsg_ran/

Be specific about which Working Groups (WG1-WG5) and which specification series might contain the answer."""

            response_text = await self.ai.generate(prompt)
            self._update_history(session_id, query, response_text)
            return {
                "success": True,
                "response": response_text,
                "thinking_steps": thinking_steps
            }

        thinking_steps.append({
            "type": "tool_result",
            "content": f"Found {len(relevant_files)} matching files",
            "tool_name": "index_search"
        })

        if listing_mode:
            return await self._handle_listing(query, relevant_files, thinking_steps, session_id, start_time)
        else:
            return await self._handle_content_query(query, relevant_files, thinking_steps, session_id, start_time)

    async def _handle_listing(self, query, files, thinking_steps, session_id, start_time):
        file_listing = "\n".join(
            f"  {i+1}. [{f['name']}]({f['url']})"
            for i, f in enumerate(files)
        )

        thinking_steps.append({
            "type": "thinking",
            "content": f"Generating listing of {len(files)} files..."
        })

        prompt = f"""You are a 3GPP telecommunications standards expert. The user wants a listing of files from the 3GPP FTP repository.

**User Question:** {query}

**Files Found ({len(files)} total):**
{file_listing}

**Instructions:**
1. Present the file listing in a clear, organized format
2. Group files logically if possible (by type, topic, or document number)
3. Include the download links for each file
4. Add a brief summary of what these files likely contain based on 3GPP naming conventions (e.g., R1-XXXXXXX = RAN1 tdoc)
5. If the user asked about a specific agenda item, note that agenda item mapping requires examining the agenda or tdoc allocation file
6. Mention the total count of files found

Provide a well-organized response."""

        response_text = await self.ai.generate(prompt, max_tokens=8192)

        elapsed = (datetime.now() - start_time).total_seconds()
        thinking_steps.append({
            "type": "thinking",
            "content": f"Response generated in {elapsed:.1f}s"
        })

        self._update_history(session_id, query, response_text)
        return {
            "success": True,
            "response": response_text,
            "thinking_steps": thinking_steps
        }

    async def _handle_content_query(self, query, relevant_files, thinking_steps, session_id, start_time):
        if is_agenda_item_query(query):
            agenda_files = [f for f in relevant_files if 'agenda' in f.get('name', '').lower()]
            other_files = [f for f in relevant_files if 'agenda' not in f.get('name', '').lower()]
            best_files = agenda_files[:2] + search_inventory(other_files, query, top_k=3)
            if not best_files:
                best_files = relevant_files[:5]
        elif is_summary_query(query):
            def priority_score(f):
                name = f.get('name', '').lower()
                path = f.get('path', '').lower()
                if 'report' in path.split('/')[-2:] or 'report' in name:
                    return 0
                if 'agenda' in path or 'agenda' in name:
                    return 1
                if 'invitation' in path or 'invitation' in name:
                    return 2
                return 3
            sorted_files = sorted(relevant_files, key=priority_score)
            best_files = sorted_files[:5]
            thinking_steps.append({
                "type": "thinking",
                "content": f"Summary query — prioritizing Report/Agenda files: {', '.join(f['name'] for f in best_files[:3])}"
            })
        else:
            best_files = search_inventory(relevant_files, query, top_k=5)
            if not best_files:
                best_files = relevant_files[:5]

        thinking_steps.append({
            "type": "tool_call",
            "content": f"Downloading and extracting content from {len(best_files)} files",
            "tool_name": "file_downloader",
            "tool_input": ", ".join(f['name'] for f in best_files)
        })

        extracted = await download_multiple(best_files, max_files=5)

        total_content_len = sum(len(e.get('text', '')) for e in extracted)
        thinking_steps.append({
            "type": "tool_result",
            "content": f"Extracted {total_content_len:,} characters from {len(extracted)} files",
            "tool_name": "file_downloader"
        })

        file_contents = []
        for i, ext in enumerate(extracted):
            source = ext.get('url', 'unknown')
            text = ext.get('text', '')[:15000]
            file_contents.append(f"### Source {i+1}: {source}\n{text}")

        combined_content = "\n\n---\n\n".join(file_contents)
        if len(combined_content) > 60000:
            combined_content = combined_content[:60000] + "\n\n[Content truncated for processing]"

        all_file_listing = "\n".join(
            f"  {i+1}. [{f['name']}]({f['url']})"
            for i, f in enumerate(relevant_files[:10])
        )

        history = self.conversation_history.get(session_id, [])
        context = ""
        if history:
            recent = history[-2:]
            context = "\n\nConversation context:\n" + "\n".join(
                f"Q: {h['query']}\nA: {h['response'][:300]}..." for h in recent
            )

        thinking_steps.append({
            "type": "thinking",
            "content": "Generating comprehensive response from extracted content..."
        })

        prompt = f"""You are a 3GPP telecommunications standards expert analyzing specification documents from the 3GPP TSG RAN FTP repository.

**User Question:** {query}
{context}

**Relevant Files Found:**
{all_file_listing}

**Extracted Content from Top Files:**
{combined_content}

**Instructions:**
1. Analyze the extracted content thoroughly to answer the user's question
2. Reference specific document names, section numbers, and clause IDs when available
3. If the content contains technical specifications, explain them clearly
4. Include direct links to the source files using their URLs
5. If the extracted content doesn't fully answer the question, acknowledge what's available and suggest which additional 3GPP specs might help
6. Structure your response with clear headings and bullet points
7. At the end, list all referenced source files with their URLs

Provide a comprehensive, well-structured response."""

        response_text = await self.ai.generate(prompt, max_tokens=8192)

        elapsed = (datetime.now() - start_time).total_seconds()
        thinking_steps.append({
            "type": "thinking",
            "content": f"Response generated in {elapsed:.1f}s"
        })

        self._update_history(session_id, query, response_text)

        return {
            "success": True,
            "response": response_text,
            "thinking_steps": thinking_steps
        }

    def _update_history(self, session_id: str, query: str, response: str):
        if session_id not in self.conversation_history:
            self.conversation_history[session_id] = []
        self.conversation_history[session_id].append({
            "query": query,
            "response": response,
            "timestamp": datetime.now().isoformat()
        })
        if len(self.conversation_history[session_id]) > 10:
            self.conversation_history[session_id] = self.conversation_history[session_id][-10:]
