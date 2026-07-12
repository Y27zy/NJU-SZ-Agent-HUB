import html
import re
from urllib.parse import parse_qs, unquote, urlparse

import requests

from src.config import USE_SYSTEM_PROXY


def _direct_url(url: str) -> str:
    parsed = urlparse(html.unescape(url))
    query = parse_qs(parsed.query)
    return unquote(query.get("uddg", [url])[0])


def search_web(query: str, max_results: int = 5) -> list[dict]:
    """Lightweight public web search for Agent tools; returned snippets are untrusted evidence."""
    clean_query = query.strip()
    if not clean_query:
        return []
    session = requests.Session()
    session.trust_env = USE_SYSTEM_PROXY
    limit = max(1, min(max_results, 8))
    headers = {"User-Agent": "Mozilla/5.0 NJU-SZ-Agent-Hub/0.4"}
    errors = []

    try:
        response = session.get(
            "https://html.duckduckgo.com/html/",
            params={"q": clean_query},
            headers=headers,
            timeout=(10, 25),
        )
        response.raise_for_status()
        results = _parse_duckduckgo(response.text, limit)
        if results:
            return results
    except requests.RequestException as exc:
        errors.append(exc)

    try:
        response = session.get(
            "https://www.bing.com/search",
            params={"q": clean_query, "count": limit},
            headers=headers,
            timeout=(10, 25),
        )
        response.raise_for_status()
        results = _parse_bing(response.text, limit)
        if results:
            return results
    except requests.RequestException as exc:
        errors.append(exc)

    if errors:
        raise errors[-1]
    return []


def _strip_tags(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html.unescape(value or ""))).strip()


def _parse_duckduckgo(source: str, limit: int) -> list[dict]:
    blocks = re.findall(r'<div class="result results_links.*?</div>\s*</div>', source, flags=re.DOTALL)
    results = []
    for block in blocks:
        link = re.search(r'class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, flags=re.DOTALL)
        if not link:
            continue
        snippet = re.search(r'class="result__snippet"[^>]*>(.*?)</', block, flags=re.DOTALL)
        results.append(
            {
                "title": _strip_tags(link.group(2)),
                "url": _direct_url(link.group(1)),
                "snippet": _strip_tags(snippet.group(1) if snippet else ""),
            }
        )
        if len(results) >= limit:
            break
    return results


def _parse_bing(source: str, limit: int) -> list[dict]:
    blocks = re.findall(r'<li class="b_algo".*?</li>', source, flags=re.DOTALL)
    results = []
    for block in blocks:
        link = re.search(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, flags=re.DOTALL)
        if not link:
            continue
        snippet = re.search(r'<p[^>]*>(.*?)</p>', block, flags=re.DOTALL)
        results.append(
            {
                "title": _strip_tags(link.group(2)),
                "url": html.unescape(link.group(1)),
                "snippet": _strip_tags(snippet.group(1) if snippet else ""),
            }
        )
        if len(results) >= limit:
            break
    return results
