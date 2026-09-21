import asyncio
import httpx
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import json
import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple

INVENTORY_FILE = Path(__file__).parent.parent / "3gpp_inventory.json"
BASE_URL = "https://www.3gpp.org/ftp/tsg_ran/"
SUPPORTED_EXTENSIONS = ('.zip', '.txt', '.doc', '.docx', '.pdf', '.htm', '.html', '.xls', '.xlsx')
SKIP_HREFS = {'../', './', '#', 'https://www.3gpp.org/', 'https://www.3gpp.org/ftp/'}
HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; 3GPPIndexer/1.0)"}

WG_MAP = {
    'ran1': 'WG1_RL1',
    'wg1': 'WG1_RL1',
    'rl1': 'WG1_RL1',
    'ran2': 'WG2_RL2',
    'wg2': 'WG2_RL2',
    'rl2': 'WG2_RL2',
    'ran3': 'WG3_Iu',
    'wg3': 'WG3_Iu',
    'ran4': 'WG4_Radio',
    'wg4': 'WG4_Radio',
    'ran5': 'WG5_Test_ex-T1',
    'wg5': 'WG5_Test_ex-T1',
    'ran6': 'WG6_legacyRAN',
    'wg6': 'WG6_legacyRAN',
    'tsg ran': 'TSG_RAN',
    'tsg_ran': 'TSG_RAN',
    'ran plenary': 'TSG_RAN',
}

MEETING_PREFIX_MAP = {
    'WG1_RL1': 'TSGR1_',
    'WG2_RL2': 'TSGR2_',
    'WG3_Iu': 'TSGR3_',
    'WG4_Radio': 'TSGR4_',
    'WG5_Test_ex-T1': 'TSGR5_',
    'WG6_legacyRAN': 'TSGR6_',
    'TSG_RAN': 'TSGR_',
}

_build_status = {
    "building": False,
    "progress": "",
    "dirs_crawled": 0,
    "files_found": 0,
}


def is_file_link(href: str) -> bool:
    name = href.rstrip('/').rsplit('/', 1)[-1] if '/' in href else href
    _, ext = os.path.splitext(name.lower())
    return ext in SUPPORTED_EXTENSIONS


def parse_page(html: str, page_url: str) -> Tuple[List[Dict], List[Dict]]:
    soup = BeautifulSoup(html, 'html.parser')
    dirs = []
    files = []
    page_stripped = page_url.rstrip('/')

    for link in soup.find_all('a', href=True):
        href = link['href']
        if href in SKIP_HREFS or href.startswith('?') or href.startswith('mailto:'):
            continue

        full_url = href if href.startswith('http') else urljoin(page_url.rstrip('/') + '/', href)
        full_stripped = full_url.rstrip('/')

        if not full_stripped.startswith(BASE_URL.rstrip('/')):
            continue
        if len(full_stripped) <= len(page_stripped):
            continue

        if is_file_link(full_url):
            name = full_stripped.rsplit('/', 1)[-1]
            ext = os.path.splitext(name.lower())[1]
            files.append({
                'url': full_url,
                'name': name,
                'extension': ext,
            })
        else:
            dir_name = full_stripped.rsplit('/', 1)[-1]
            dirs.append({'url': full_url, 'name': dir_name})

    return dirs, files


async def build_full_inventory() -> Dict:
    global _build_status
    _build_status = {"building": True, "progress": "Starting...", "dirs_crawled": 0, "files_found": 0}

    print(f"[3GPP] Building structure index from {BASE_URL}")
    start_time = datetime.now()

    structure = {}
    top_files = []
    dirs_crawled = 0
    semaphore = asyncio.Semaphore(25)

    async def fetch_dir(client, url):
        async with semaphore:
            try:
                resp = await client.get(url, timeout=30.0)
                if resp.status_code == 200:
                    return parse_page(resp.text, url)
            except Exception as e:
                print(f"[3GPP Crawler] Error: {url}: {type(e).__name__}")
        return [], []

    async with httpx.AsyncClient(follow_redirects=True, headers=HTTP_HEADERS, limits=httpx.Limits(max_connections=25, max_keepalive_connections=10)) as client:
        top_dirs, top_lvl_files = await fetch_dir(client, BASE_URL)
        top_files.extend(top_lvl_files)
        dirs_crawled += 1

        for d in top_dirs:
            structure[d['name']] = {"url": d['url'], "meetings": {}, "files": []}

        _build_status["progress"] = f"Found {len(top_dirs)} working groups"
        print(f"[3GPP] Level 0: {len(top_dirs)} working groups")

        wg_tasks = [fetch_dir(client, d['url']) for d in top_dirs]
        wg_results = await asyncio.gather(*wg_tasks, return_exceptions=True)

        meeting_fetch_tasks = []

        for i, result in enumerate(wg_results):
            if isinstance(result, Exception):
                continue
            sub_dirs, sub_files = result
            dirs_crawled += 1
            wg_name = top_dirs[i]['name']

            for f in sub_files:
                f['path'] = f"{wg_name}/{f['name']}"
                f['keywords'] = f['name'].lower().replace('-', ' ').replace('_', ' ').replace('.', ' ')
            structure[wg_name]["files"] = sub_files
            top_files.extend(sub_files)

            for sd in sub_dirs:
                structure[wg_name]["meetings"][sd['name']] = {
                    "url": sd['url'],
                    "subfolders": [],
                    "indexed": False,
                }
                meeting_fetch_tasks.append((wg_name, sd['name'], sd['url']))

        _build_status["progress"] = f"Found {len(meeting_fetch_tasks)} meetings across all WGs"
        print(f"[3GPP] Level 1: {len(meeting_fetch_tasks)} meeting directories found")

        batch_size = 50
        for batch_start in range(0, len(meeting_fetch_tasks), batch_size):
            batch = meeting_fetch_tasks[batch_start:batch_start + batch_size]
            tasks = [fetch_dir(client, url) for _, _, url in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for j, result in enumerate(results):
                if isinstance(result, Exception):
                    continue
                wg_name, meeting_name, _ = batch[j]
                sub_dirs, sub_files = result
                dirs_crawled += 1

                for f in sub_files:
                    f['path'] = f"{wg_name}/{meeting_name}/{f['name']}"
                    f['keywords'] = f['name'].lower().replace('-', ' ').replace('_', ' ').replace('.', ' ')
                top_files.extend(sub_files)

                subfolder_names = [sd['name'] for sd in sub_dirs]
                structure[wg_name]["meetings"][meeting_name]["subfolders"] = subfolder_names
                structure[wg_name]["meetings"][meeting_name]["indexed"] = False

            _build_status["dirs_crawled"] = dirs_crawled
            _build_status["files_found"] = len(top_files)
            _build_status["progress"] = f"Crawled {dirs_crawled} dirs, found {len(top_files)} files"

    elapsed = (datetime.now() - start_time).total_seconds()

    result = {
        "metadata": {
            "base_url": BASE_URL,
            "total_files": len(top_files),
            "total_directories": dirs_crawled,
            "total_meetings": len(meeting_fetch_tasks),
            "built_at": datetime.now().isoformat(),
            "duration_seconds": round(elapsed, 1),
            "index_type": "structure_with_on_demand",
        },
        "structure": structure,
        "files": top_files,
    }

    with open(INVENTORY_FILE, 'w') as f:
        json.dump(result, f)

    file_size_mb = INVENTORY_FILE.stat().st_size / (1024 * 1024)
    print(f"[3GPP] ✅ Structure index built: {len(top_files)} files, {dirs_crawled} dirs, {len(meeting_fetch_tasks)} meetings in {elapsed:.1f}s ({file_size_mb:.1f}MB)")

    _build_status = {"building": False, "progress": "Complete", "dirs_crawled": dirs_crawled, "files_found": len(top_files)}
    return result


async def fetch_meeting_files(wg_dir: str, meeting_name: str, subfolder: Optional[str] = None) -> List[Dict]:
    url = f"{BASE_URL}{wg_dir}/{meeting_name}"
    if subfolder:
        url = f"{url}/{subfolder}"

    files = []
    semaphore = asyncio.Semaphore(10)

    async def fetch_dir(client, dir_url, rel_prefix):
        async with semaphore:
            try:
                resp = await client.get(dir_url, timeout=30.0)
                if resp.status_code != 200:
                    return []
            except Exception:
                return []

        dirs, found_files = parse_page(resp.text, dir_url)
        for f in found_files:
            f['path'] = rel_prefix + f['name']
            f['keywords'] = f['name'].lower().replace('-', ' ').replace('_', ' ').replace('.', ' ')
        return found_files

    async with httpx.AsyncClient(follow_redirects=True, headers=HTTP_HEADERS, limits=httpx.Limits(max_connections=10)) as client:
        if subfolder:
            files = await fetch_dir(client, url, f"{wg_dir}/{meeting_name}/{subfolder}/")
            if not files:
                print(f"[3GPP] Subfolder '{subfolder}' empty or not found, fetching full meeting")
                url = f"{BASE_URL}{wg_dir}/{meeting_name}"
                subfolder = None

        if not subfolder:
            try:
                resp = await client.get(url, timeout=30.0)
                if resp.status_code == 200:
                    dirs, direct_files = parse_page(resp.text, url)
                    for f in direct_files:
                        f['path'] = f"{wg_dir}/{meeting_name}/{f['name']}"
                        f['keywords'] = f['name'].lower().replace('-', ' ').replace('_', ' ').replace('.', ' ')
                    files.extend(direct_files)

                    sub_tasks = []
                    for d in dirs:
                        sub_tasks.append(fetch_dir(client, d['url'], f"{wg_dir}/{meeting_name}/{d['name']}/"))
                    sub_results = await asyncio.gather(*sub_tasks, return_exceptions=True)
                    for res in sub_results:
                        if not isinstance(res, Exception):
                            files.extend(res)
            except Exception:
                pass

    data = load_inventory()
    if data and files:
        existing_paths = {f['path'] for f in data.get('files', [])}
        new_files = [f for f in files if f['path'] not in existing_paths]
        if new_files:
            data['files'].extend(new_files)
            data['metadata']['total_files'] = len(data['files'])
            if wg_dir in data.get('structure', {}) and meeting_name in data['structure'][wg_dir].get('meetings', {}):
                data['structure'][wg_dir]['meetings'][meeting_name]['indexed'] = True

            with open(INVENTORY_FILE, 'w') as f_out:
                json.dump(data, f_out)
            print(f"[3GPP] Added {len(new_files)} new files from {wg_dir}/{meeting_name} to index (total: {data['metadata']['total_files']})")

    return files


def load_inventory() -> Optional[Dict]:
    if INVENTORY_FILE.exists():
        try:
            with open(INVENTORY_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            return None
    return None


def get_inventory_status() -> Dict:
    if _build_status["building"]:
        return {
            "exists": False,
            "building": True,
            "progress": _build_status["progress"],
            "dirs_crawled": _build_status["dirs_crawled"],
            "files_found": _build_status["files_found"],
        }

    data = load_inventory()
    if data and data.get("metadata"):
        meta = data["metadata"]
        return {
            "exists": True,
            "building": False,
            "total_files": meta.get("total_files", 0),
            "total_directories": meta.get("total_directories", 0),
            "total_meetings": meta.get("total_meetings", 0),
            "built_at": meta.get("built_at", ""),
            "duration_seconds": meta.get("duration_seconds", 0),
            "file_size_mb": round(INVENTORY_FILE.stat().st_size / (1024 * 1024), 1) if INVENTORY_FILE.exists() else 0,
        }
    return {"exists": False, "building": False}


def parse_query_context(query: str) -> Dict[str, Optional[str]]:
    q = query.lower()

    wg_dir = None
    for key, val in WG_MAP.items():
        if key in q:
            wg_dir = val
            break

    meeting_num = None
    m = re.search(r'meeting\s*(?:no\.?|number|#|num)?\s*(\d+[a-z]?)', q)
    if m:
        meeting_num = m.group(1)
    else:
        m2 = re.search(r'(?:tsgr[1-6]?_|r[1-6]-)(\d+[a-z]?)', q)
        if m2:
            meeting_num = m2.group(1)

    subfolder = None
    if any(w in q for w in ['tdoc', 'document', 'docs', 'contribution']):
        subfolder = 'Docs'
    elif 'agenda' in q:
        subfolder = 'Agenda'
    elif 'report' in q:
        subfolder = 'Report'
    elif any(w in q for w in ['liaison', 'ls ']):
        subfolder = 'LS'

    is_latest = any(w in q for w in ['latest', 'last', 'most recent', 'newest', 'current'])

    return {
        'wg_dir': wg_dir,
        'meeting_num': meeting_num,
        'subfolder': subfolder,
        'is_latest': is_latest,
        'original_query': query,
    }


def find_latest_meeting(structure: Dict, wg_dir: str, check_content: bool = True) -> Optional[str]:
    meetings = structure.get(wg_dir, {}).get('meetings', {})
    if not meetings:
        return None

    prefix = MEETING_PREFIX_MAP.get(wg_dir, 'TSGR_')

    def extract_num(name):
        m = re.search(rf'{re.escape(prefix)}(\d+)', name)
        return int(m.group(1)) if m else 0

    numbered = [(extract_num(m), m) for m in meetings if extract_num(m) > 0]
    if not numbered:
        return None

    numbered.sort(reverse=True)

    if not check_content:
        return numbered[0][1]

    for _, meeting_name in numbered[:5]:
        info = meetings.get(meeting_name, {})
        subfolders = info.get('subfolders', [])
        if 'Docs' in subfolders or 'Report' in subfolders:
            return meeting_name

    return numbered[0][1]


def find_meeting_name(structure: Dict, wg_dir: str, meeting_num: str) -> Optional[str]:
    prefix = MEETING_PREFIX_MAP.get(wg_dir, 'TSGR_')
    exact = f"{prefix}{meeting_num}"

    meetings = structure.get(wg_dir, {}).get('meetings', {})
    if exact in meetings:
        return exact

    for name in meetings:
        if name.startswith(exact + '-') or name.startswith(exact + '_') or name == exact + 'bis':
            return name
        if re.match(rf'^{re.escape(exact)}[^0-9]', name):
            return name

    return exact


async def search_index(query: str, max_results: int = 50) -> List[Dict]:
    data = load_inventory()
    if not data:
        return []

    ctx = parse_query_context(query)
    structure = data.get('structure', {})

    if ctx['wg_dir'] and ctx.get('is_latest') and not ctx['meeting_num']:
        latest = await _find_latest_meeting_with_content(data, structure, ctx['wg_dir'])
        if latest:
            print(f"[3GPP Search] Resolved 'latest' to {ctx['wg_dir']}/{latest}")
            ctx['meeting_num'] = re.search(r'(\d+)', latest).group(1) if re.search(r'(\d+)', latest) else None
            return await _fetch_meeting_files_for_query(data, ctx, latest, max_results)

    if ctx['wg_dir'] and ctx['meeting_num']:
        meeting_name = find_meeting_name(structure, ctx['wg_dir'], ctx['meeting_num'])
        return await _fetch_meeting_files_for_query(data, ctx, meeting_name, max_results)

    files = data.get("files", [])

    if ctx['wg_dir']:
        files = [f for f in files if ctx['wg_dir'].lower() in f.get('path', '').lower()]

    if ctx['subfolder']:
        sf_lower = ctx['subfolder'].lower()
        filtered = [f for f in files if f"/{sf_lower}/" in f.get('path', '').lower()]
        if filtered:
            files = filtered

    if ctx['wg_dir'] or ctx['subfolder']:
        return files[:max_results]

    query_terms = set(query.lower().replace('-', ' ').replace('_', ' ').split())
    query_terms -= {'the', 'a', 'an', 'for', 'in', 'of', 'to', 'and', 'or', 'is', 'it', 'no',
                    'item', 'find', 'list', 'show', 'get', 'what', 'how', 'all',
                    'latest', 'last', 'most', 'recent', 'newest', 'current',
                    'summarize', 'summary', 'summarise', 'give', 'me', 'provide'}

    scored = []
    for f in files:
        kw = f.get('keywords', f['name'].lower())
        path_lower = f.get('path', '').lower()
        combined = f"{kw} {path_lower}"

        score = sum(1 for t in query_terms if t in combined)
        if score > 0:
            ext = f.get('extension', '')
            if ext in ('.pdf', '.doc', '.docx'):
                score += 0.3
            scored.append((score, f))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [f for _, f in scored[:max_results]]


async def _find_latest_meeting_with_content(data: Dict, structure: Dict, wg_dir: str) -> Optional[str]:
    meetings = structure.get(wg_dir, {}).get('meetings', {})
    if not meetings:
        return None

    prefix = MEETING_PREFIX_MAP.get(wg_dir, 'TSGR_')

    def extract_num(name):
        m = re.search(rf'{re.escape(prefix)}(\d+)', name)
        return int(m.group(1)) if m else 0

    numbered = [(extract_num(m), m) for m in meetings if extract_num(m) > 0]
    numbered.sort(reverse=True)

    for _, meeting_name in numbered[:10]:
        meeting_prefix = f"{wg_dir}/{meeting_name}/"
        existing = [f for f in data.get('files', []) if f.get('path', '').startswith(meeting_prefix)]
        if len(existing) > 5:
            return meeting_name

        fetched = await fetch_meeting_files(wg_dir, meeting_name)
        data = load_inventory()
        if data:
            new_existing = [f for f in data.get('files', []) if f.get('path', '').startswith(meeting_prefix)]
            if len(new_existing) > 5:
                return meeting_name
            print(f"[3GPP Search] {wg_dir}/{meeting_name} has only {len(new_existing)} files, trying older meeting...")

    return numbered[0][1] if numbered else None


async def _fetch_meeting_files_for_query(data: Dict, ctx: Dict, meeting_name: str, max_results: int) -> List[Dict]:
    wg_dir = ctx['wg_dir']
    meeting_path_prefix = f"{wg_dir}/{meeting_name}/"

    if ctx.get('subfolder'):
        subfolder_prefix = f"{wg_dir}/{meeting_name}/{ctx['subfolder']}/"
    else:
        subfolder_prefix = None

    data = load_inventory() or data
    existing = [f for f in data.get('files', []) if f.get('path', '').startswith(meeting_path_prefix)]

    if not existing:
        print(f"[3GPP Search] Meeting files not indexed yet, fetching on-demand: {wg_dir}/{meeting_name}")
        fetched = await fetch_meeting_files(wg_dir, meeting_name, ctx.get('subfolder'))
        existing = fetched

    if subfolder_prefix:
        subfolder_files = [f for f in existing if f.get('path', '').startswith(subfolder_prefix)]
        if subfolder_files:
            existing = subfolder_files

    is_summary = ctx.get('is_latest') or any(
        kw in ctx.get('original_query', '').lower()
        for kw in ['summary', 'summarize', 'summarise', 'overview', 'highlights', 'decisions', 'outcomes']
    )

    if is_summary and len(existing) > max_results:
        def priority_score(f):
            path = f.get('path', '').lower()
            name = f.get('name', '').lower()
            if '/report/' in path or 'report' in name:
                return 3
            if '/agenda/' in path or 'agenda' in name:
                return 2
            if '/invitation/' in path or 'invite' in name:
                return 1
            if 'tdoc' in name or 'tdoc_index' in name:
                return -1
            return 0

        existing.sort(key=priority_score, reverse=True)

    return existing[:max_results]
