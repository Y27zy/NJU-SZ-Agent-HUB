"""Deterministic readability fixes for already reconstructed Markdown."""

from __future__ import annotations

import re


_PAGE_BLOCK = re.compile(
    r"(<!--\s*page\s*:\s*(\d+)\s*-->)(.*?)(?=<!--\s*page\s*:\s*\d+\s*-->|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_ASSET_IMAGE = re.compile(r"!\[([^\]]*)\]\((asset://page-(\d+)-figure-\d+\.png)\)")
_DETAIL_BLOCK = re.compile(r"(<details\s+data-source-page-scan=\"true\">.*?</details>)", re.DOTALL)


def optimize_scanned_page_markdown(markdown: str, scan_pages: set[int]) -> str:
    """Flatten noisy quote blocks and hide/remove extracted full-page screenshots.

    Reconstructed text remains primary. A scan is retained behind a collapsed
    disclosure only when the page still contains an explicit ``[待核对]`` marker
    or when the scan had been embedded inline as indispensable matrix content.
    """
    source = re.sub(r"(?m)^[ \t]*>+[ \t]?", "", markdown or "")
    if not source or not scan_pages:
        return source.strip()

    def clean_page(match: re.Match[str]) -> str:
        anchor, page_text = match.group(1), match.group(3)
        page_number = int(match.group(2))
        if page_number not in scan_pages or 'data-source-page-scan="true"' in page_text:
            return f"{anchor}{page_text}"

        images = [item for item in _ASSET_IMAGE.finditer(page_text) if int(item.group(3)) in scan_pages]
        if not images:
            return f"{anchor}{page_text}"

        inline_image = any(item.group(0).strip() != page_text[item.start():item.end()].strip() or not _is_own_line(page_text, item) for item in images)
        needs_source = "[待核对]" in page_text or inline_image
        first_alt, first_source = images[0].group(1), images[0].group(2)

        def remove_image(item: re.Match[str]) -> str:
            if int(item.group(3)) not in scan_pages:
                return item.group(0)
            return "（矩阵或公式见下方原页核对）" if not _is_own_line(page_text, item) else ""

        cleaned = _ASSET_IMAGE.sub(remove_image, page_text)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).rstrip()
        if needs_source:
            label = first_alt.strip() or f"第 {page_number} 页原始内容"
            cleaned += (
                "\n\n<details data-source-page-scan=\"true\">\n"
                f"<summary>原页核对：{label}</summary>\n\n"
                f"![{label}]({first_source})\n\n"
                "</details>"
            )
        return f"{anchor}{cleaned}\n"

    cleaned = _PAGE_BLOCK.sub(clean_page, source)
    disclosures: list[str] = []
    chunks = _DETAIL_BLOCK.split(cleaned)
    for index in range(0, len(chunks), 2):
        chunk = chunks[index]

        def clean_unanchored(item: re.Match[str]) -> str:
            page_number = int(item.group(3))
            if page_number not in scan_pages:
                return item.group(0)
            if _is_own_line(chunk, item):
                return ""
            label = item.group(1).strip() or f"第 {page_number} 页原始内容"
            disclosures.append(
                "<details data-source-page-scan=\"true\">\n"
                f"<summary>原页核对：{label}</summary>\n\n"
                f"![{label}]({item.group(2)})\n\n"
                "</details>"
            )
            return "（矩阵或公式见文末原页核对）"

        chunks[index] = _ASSET_IMAGE.sub(clean_unanchored, chunk)
    cleaned = "".join(chunks)
    if disclosures:
        cleaned = f"{cleaned.rstrip()}\n\n" + "\n\n".join(disclosures)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def _is_own_line(text: str, match: re.Match[str]) -> bool:
    line_start = text.rfind("\n", 0, match.start()) + 1
    line_end = text.find("\n", match.end())
    if line_end < 0:
        line_end = len(text)
    return text[line_start:line_end].strip() == match.group(0)
