"""Extraction and Markdown binding for images embedded in uploaded PDFs."""

from __future__ import annotations

import re
import json
from collections import Counter, defaultdict
from pathlib import Path

from src.config import STORAGE_DIR


ASSET_SCHEME = "asset://"
_PAGE_ANCHOR = re.compile(r"<!--\s*page\s*:\s*(\d+)\s*-->", re.IGNORECASE)
_IMAGE_LINK = re.compile(r"!\[([^\]]*)\]\(([^\s)]+)(?:\s+\"[^\"]*\")?\)")
_FIGURE_MARKER = re.compile(r"\[图\s*[：:]\s*([^\]\n]{1,180})\]")


def _is_full_page_scan(page, xref: int, threshold: float = 0.85) -> bool:
    """Reject rasterized PDF pages masquerading as embedded teaching figures."""
    page_area = max(float(page.rect.width * page.rect.height), 1.0)
    try:
        return any(float(rect.width * rect.height) / page_area >= threshold for rect in page.get_image_rects(xref))
    except Exception:
        return False


def full_page_scan_pages(source_path: str | Path) -> set[int]:
    """Return pages containing a near-full-page raster image."""
    path = Path(source_path)
    if path.suffix.lower() != ".pdf" or not path.exists():
        return set()
    import fitz

    result: set[int] = set()
    with fitz.open(path) as document:
        for page_number, page in enumerate(document, 1):
            if any(_is_full_page_scan(page, int(image[0])) for image in page.get_images(full=True)):
                result.add(page_number)
    return result


def document_asset_dir(document_id: int) -> Path:
    """Return the per-document directory used for extracted browser-safe assets."""
    return STORAGE_DIR / "document_assets" / str(int(document_id))


def document_assets_ready(document_id: int) -> bool:
    """Return whether an extraction attempt has already completed for this document."""
    return (document_asset_dir(document_id) / ".assets-ready.json").exists()


def inspect_pdf_figures(source_path: str | Path) -> dict[int, int]:
    """Count meaningful embedded figures per PDF page without writing assets.

    The document Agent receives these counts as editorial hints.  They are not a
    command to retain every image: the model still has to decide whether a
    diagram, chart, or table is useful for understanding the surrounding text.
    """
    path = Path(source_path)
    if path.suffix.lower() != ".pdf" or not path.exists():
        return {}
    import fitz

    with fitz.open(path) as document:
        xref_frequency = Counter(image[0] for page in document for image in page.get_images(full=True))
        seen_xrefs: set[int] = set()
        result: dict[int, int] = {}
        for page_number, page in enumerate(document, 1):
            count = 0
            for image in page.get_images(full=True):
                xref, width, height = int(image[0]), int(image[2]), int(image[3])
                if _is_full_page_scan(page, xref):
                    continue
                if xref in seen_xrefs or width * height < 18000 or min(width, height) < 70:
                    continue
                if xref_frequency[xref] >= 3:
                    continue
                seen_xrefs.add(xref)
                count += 1
            if count:
                result[page_number] = count
    return result


def extract_pdf_images(document_id: int, source_path: str | Path) -> dict[int, list[str]]:
    """Extract meaningful PDF figures and return page-to-asset references."""
    path = Path(source_path)
    if path.suffix.lower() != ".pdf" or not path.exists():
        return {}
    import fitz

    output_dir = document_asset_dir(document_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    page_assets: dict[int, list[str]] = defaultdict(list)
    with fitz.open(path) as document:
        xref_frequency = Counter(image[0] for page in document for image in page.get_images(full=True))
        written_xrefs: set[int] = set()
        for page_number, page in enumerate(document, 1):
            figure_index = 0
            for image in page.get_images(full=True):
                xref, width, height = int(image[0]), int(image[2]), int(image[3])
                if _is_full_page_scan(page, xref):
                    continue
                if xref in written_xrefs or width * height < 18000 or min(width, height) < 70:
                    continue
                if xref_frequency[xref] >= 3:
                    continue
                try:
                    pixmap = fitz.Pixmap(document, xref)
                    if pixmap.n - pixmap.alpha > 3:
                        pixmap = fitz.Pixmap(fitz.csRGB, pixmap)
                    figure_index += 1
                    filename = f"page-{page_number:03d}-figure-{figure_index}.png"
                    (output_dir / filename).write_bytes(pixmap.tobytes("png"))
                    page_assets[page_number].append(f"{ASSET_SCHEME}{filename}")
                    written_xrefs.add(xref)
                except Exception:
                    continue
    (output_dir / ".assets-ready.json").write_text(
        json.dumps({"source": path.name, "pages": sorted(page_assets), "count": sum(map(len, page_assets.values()))}),
        encoding="utf-8",
    )
    return dict(page_assets)


def ensure_document_images(document_id: int, source_path: str | Path, markdown: str) -> str:
    """Backfill legacy PDFs once, while keeping future workspace renders inexpensive."""
    if document_assets_ready(document_id):
        return markdown
    return bind_document_images(markdown, extract_pdf_images(document_id, source_path))


def bind_document_images(markdown: str, page_assets: dict[int, list[str]]) -> str:
    """Bind only figures explicitly retained by the document processing Agent.

    Earlier versions appended every extracted PDF image to its page.  That made
    decorative photos, probability coin illustrations, and closing-slide images
    look like course content.  A retained figure now needs either an old
    placeholder image link or the deliberate ``[图：说明]`` marker emitted by
    the reconstruction prompt.
    """
    if not markdown or not page_assets:
        return markdown
    parts = _PAGE_ANCHOR.split(markdown)
    if len(parts) == 1:
        return markdown
    output = [parts[0]]
    for index in range(1, len(parts), 2):
        page_number = int(parts[index])
        segment = parts[index + 1] if index + 1 < len(parts) else ""
        assets = list(page_assets.get(page_number) or [])
        used: list[str] = []

        def replace_placeholder(match: re.Match[str]) -> str:
            alt, source = match.group(1), match.group(2)
            normalized = source.lower()
            if ("placeholder" in normalized or normalized.startswith("file://")) and assets:
                asset = assets.pop(0)
                used.append(asset)
                return f"![{alt}]({asset})"
            if source.startswith(ASSET_SCHEME):
                used.append(source)
            return match.group(0)

        segment = _IMAGE_LINK.sub(replace_placeholder, segment)

        def replace_figure_marker(match: re.Match[str]) -> str:
            description = match.group(1).strip()
            if not assets:
                return f"[图：{description}]"
            asset = assets.pop(0)
            used.append(asset)
            return f"![{description}]({asset})"

        segment = _FIGURE_MARKER.sub(replace_figure_marker, segment)
        output.extend([f"<!-- page:{page_number} -->", segment])
    return "".join(output)
