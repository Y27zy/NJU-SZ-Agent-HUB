import base64
import json
import math
import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from src.database import execute, now_iso
from src.llm.gateway import chat_with_user_messages, chat_with_user_model
from src.rag.document_parser import parse_document
from src.rag.simple_vector_store import (
    create_document_record,
    fail_document_processing,
    finish_document_processing,
    get_document,
)
from src.rag.text_splitter import split_text


ProgressCallback = Callable[[int, int, str], None]
MAX_STRUCTURE_INPUT = 52000
MAX_CHAPTER_INPUT = 18000

STRUCTURE_SYSTEM_PROMPT = """你是大学教材与学术论文的结构化编辑。你的任务不是总结内容，而是恢复整份文档的真实目录结构。
请综合所有分页片段，识别封面、目录、章、节、附录和参考文献，并合并重复页眉页脚。
只输出一个合法 JSON 对象，不要使用 Markdown 代码围栏。格式必须是：
{"document_title":"标题","document_kind":"course|paper|other","chapters":[{"title":"章节标题","start_page":1,"end_page":3,"summary":"一句话说明本章内容","key_terms":["术语"]}]}
要求：chapters 按页码递增；页码范围覆盖正文；章节标题简洁、具体、不得使用“第1部分”这类空泛名称；
论文优先识别 Abstract、Introduction、Related Work、Method、Experiments、Conclusion、References；
课件优先依据页内大标题和主题转折划分，不能把每一页机械地当成一章。
同一页上的多个目录项或小标题属于章内层级，不能分别输出为多个重叠章节；每个 start_page 只能对应一个章节。"""

CHAPTER_SYSTEM_PROMPT = r"""你是南京大学课程资料的数字化排版编辑。把给定章节恢复成忠于原文、适合网页精读的 Markdown 正文。
严格要求：
1. 不总结替代原文，不添加资料中不存在的事实；去除重复页眉、页脚、页码噪声和 OCR 重复文本。
2. 不输出本章的二级标题，调用方会统一添加；章内主题使用 ###，更细层级使用 ####。
3. 修复 PDF 造成的断行、连字符、项目符号和中英文空格，使段落完整，禁止把整章挤成一个段落。
4. 定义、定理、结论、注意事项使用引用块；步骤和并列关系使用列表；表格恢复为 Markdown 表格。
5. 所有数学表达必须恢复为 LaTeX：行内公式使用 $...$，独立公式使用 $$...$$。不要使用 \(...\)、\[...\] 或裸露反斜杠公式。
6. 保留输入中的 <!-- page:N --> 页码锚点，并把它放在对应页面内容之前。
7. 无法可靠识别的字符写成 [待核对]，不要凭空猜测。
只输出 Markdown 正文。"""

COMPLETE_DOCUMENT_SYSTEM_PROMPT = r"""你是文档数字化处理 Agent。输入是一份较短的完整资料，而不是需要扩写的提纲。
请逐页恢复为忠于原文、适合网页精读的 Markdown，并遵守：
1. 保留全部有效信息，不总结、不扩写、不补充外部知识。
2. 目录或总览只保留一次；绝不能在每个主题前重复考试说明、摘要、作者或目录。
3. 根据原文层级使用 ##、###、#### 标题；同一页可有多个章内标题，不要为了每个目录词复制页面正文。
4. 保留 <!-- page:N --> 锚点。修复 PDF 断行、项目符号和中英文空格；代码使用带语言标识的代码块。
5. 表格恢复为 Markdown 表格；数学表达使用 $...$ 或 $$...$$，不用 \(...\) 或 \[...\]。
6. 图片无法转写时保留简短的 [图：原图说明]，不可臆造图中内容。
只输出正文 Markdown，不要输出文档一级标题，也不要解释处理过程。"""


def _extract_json(text: str) -> dict:
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        cleaned = fenced.group(1)
    else:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
    return json.loads(cleaned)


def _normalize_repeated_line(line: str) -> str:
    """Normalize a line for conservative cross-page boilerplate detection."""
    return re.sub(r"[\W_]+", "", line, flags=re.UNICODE).lower()


def _order_pdf_blocks(blocks: list[tuple], page_width: float) -> list[tuple]:
    """Restore a practical reading order for both one- and two-column pages."""
    usable = [block for block in blocks if str(block[4]).strip()]
    narrow = [block for block in usable if (block[2] - block[0]) < page_width * 0.72]
    left = [block for block in narrow if (block[0] + block[2]) / 2 < page_width * 0.48]
    right = [block for block in narrow if (block[0] + block[2]) / 2 > page_width * 0.52]
    is_two_column = len(left) >= 2 and len(right) >= 2
    if not is_two_column:
        return sorted(usable, key=lambda block: (round(block[1], 1), round(block[0], 1)))

    wide = [block for block in usable if block not in narrow]
    ordered: list[tuple] = []
    remaining = list(narrow)
    for separator in sorted(wide, key=lambda block: block[1]):
        before = [block for block in remaining if block[1] < separator[1]]
        ordered.extend(sorted((block for block in before if (block[0] + block[2]) / 2 < page_width / 2), key=lambda b: b[1]))
        ordered.extend(sorted((block for block in before if (block[0] + block[2]) / 2 >= page_width / 2), key=lambda b: b[1]))
        remaining = [block for block in remaining if block not in before]
        ordered.append(separator)
    ordered.extend(sorted((block for block in remaining if (block[0] + block[2]) / 2 < page_width / 2), key=lambda b: b[1]))
    ordered.extend(sorted((block for block in remaining if (block[0] + block[2]) / 2 >= page_width / 2), key=lambda b: b[1]))
    return ordered


def _remove_repeated_page_noise(pages: list[str]) -> list[str]:
    """Remove recurring headers/footers after their first meaningful occurrence."""
    if len(pages) < 3:
        return pages
    page_lines = [[line.strip() for line in page.splitlines() if line.strip()] for page in pages]
    frequencies: Counter[str] = Counter()
    for lines in page_lines:
        frequencies.update(set(_normalize_repeated_line(line) for line in lines if 3 <= len(line) <= 100))
    threshold = max(3, math.ceil(len(pages) * 0.6))
    repeated = {key for key, count in frequencies.items() if key and count >= threshold}
    if not repeated:
        return pages
    seen: set[str] = set()
    cleaned: list[str] = []
    for lines in page_lines:
        kept = []
        for line in lines:
            key = _normalize_repeated_line(line)
            if key in repeated and key in seen:
                continue
            kept.append(line)
            if key in repeated:
                seen.add(key)
        cleaned.append("\n".join(kept))
    return cleaned


def _extract_pdf_pages(path: Path) -> list[str]:
    """Extract pages with column-aware ordering and conservative boilerplate removal."""
    import fitz

    pages: list[str] = []
    with fitz.open(path) as document:
        for page in document:
            blocks = _order_pdf_blocks(page.get_text("blocks"), page.rect.width)
            text = "\n".join(str(block[4]).strip() for block in blocks if str(block[4]).strip())
            pages.append(text)
    return _remove_repeated_page_noise(pages)


def _document_profile(pages: list[str], title: str, doc_type: str) -> dict:
    """Classify the document so the agent can choose an efficient processing route."""
    joined = "\n".join(pages)
    lowered = joined[:14000].lower()
    paper_markers = sum(marker in lowered for marker in ("abstract", "introduction", "related work", "references"))
    paper = paper_markers >= 2 or doc_type.lower() in {"paper", "论文"}
    compact = not paper and len(pages) <= 10 and len(joined) <= 18000
    return {
        "kind": "paper" if paper else ("course" if doc_type.lower() in {"course", "课程"} else "other"),
        "strategy": "compact_complete" if compact else "chapter_reconstruction",
        "page_count": len(pages),
        "character_count": len(joined),
        "title": title,
    }


def _ocr_page_with_model(user_id: int, path: Path, page_number: int) -> str:
    import fitz

    with fitz.open(path) as document:
        page = document[page_number - 1]
        pixmap = page.get_pixmap(matrix=fitz.Matrix(1.7, 1.7), alpha=False)
    image_data = base64.b64encode(pixmap.tobytes("jpeg")).decode("ascii")
    messages = [
        {"role": "system", "content": CHAPTER_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": f"识别第 {page_number} 页，保留阅读顺序、公式和结构，输出 Markdown。"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}},
            ],
        },
    ]
    return chat_with_user_messages(user_id, messages, temperature=0.05).strip()


def _structure_source(pages: list[str]) -> str:
    budget_per_page = max(700, min(2400, MAX_STRUCTURE_INPUT // max(1, len(pages))))
    parts = []
    for page_number, text in enumerate(pages, 1):
        compact = re.sub(r"\n{3,}", "\n\n", text.strip())
        parts.append(f"[PAGE {page_number}]\n{compact[:budget_per_page]}")
    return "\n\n".join(parts)[:MAX_STRUCTURE_INPUT]


def _fallback_structure(title: str, page_count: int, doc_type: str) -> dict:
    step = 8 if page_count > 16 else max(1, page_count)
    chapters = []
    for start in range(1, page_count + 1, step):
        end = min(page_count, start + step - 1)
        chapters.append(
            {
                "title": "正文" if len(chapters) == 0 and end == page_count else f"第 {start}-{end} 页",
                "start_page": start,
                "end_page": end,
                "summary": "按原始页码整理的正文。",
                "key_terms": [],
            }
        )
    return {"document_title": title, "document_kind": doc_type, "chapters": chapters}


def _normalize_structure(data: dict, title: str, page_count: int, doc_type: str) -> dict:
    chapters = []
    for item in data.get("chapters") or []:
        try:
            start = max(1, min(page_count, int(item.get("start_page", 1))))
            end = max(start, min(page_count, int(item.get("end_page", start))))
        except (TypeError, ValueError):
            continue
        chapter_title = str(item.get("title") or "正文").strip().lstrip("#").strip()
        chapters.append(
            {
                "title": chapter_title[:120] or "正文",
                "start_page": start,
                "end_page": end,
                "summary": str(item.get("summary") or "").strip()[:300],
                "key_terms": [str(term).strip()[:60] for term in (item.get("key_terms") or []) if str(term).strip()][:10],
            }
        )
    chapters.sort(key=lambda item: (item["start_page"], item["end_page"]))
    if not chapters:
        return _fallback_structure(title, page_count, doc_type)
    # A model may mistake every item on a contents page for a top-level chapter.
    # Keep one chapter boundary per physical page and make titles unique.
    unique_starts: dict[int, dict] = {}
    for chapter in chapters:
        current = unique_starts.get(chapter["start_page"])
        if current is None:
            unique_starts[chapter["start_page"]] = chapter
        else:
            current["end_page"] = max(current["end_page"], chapter["end_page"])
            current["key_terms"] = list(dict.fromkeys(current["key_terms"] + [chapter["title"]] + chapter["key_terms"]))[:10]
    chapters = list(unique_starts.values())[: max(1, min(page_count, 16))]
    used_titles: Counter[str] = Counter()
    for chapter in chapters:
        used_titles[chapter["title"]] += 1
        if used_titles[chapter["title"]] > 1:
            chapter["title"] = f"{chapter['title']}（续）"
    chapters[0]["start_page"] = 1
    for index in range(len(chapters) - 1):
        chapters[index]["end_page"] = max(chapters[index]["start_page"], chapters[index + 1]["start_page"] - 1)
    chapters[-1]["end_page"] = page_count
    return {
        "document_title": str(data.get("document_title") or title).strip()[:200],
        "document_kind": doc_type,
        "chapters": chapters,
    }


def _plan_structure(user_id: int, title: str, doc_type: str, pages: list[str]) -> dict:
    prompt = f"文档名：{title}\n资料类型：{doc_type}\n总页数：{len(pages)}\n\n分页内容：\n{_structure_source(pages)}"
    response = chat_with_user_model(user_id, STRUCTURE_SYSTEM_PROMPT, prompt, temperature=0.05)
    try:
        data = _extract_json(response)
    except (json.JSONDecodeError, TypeError, ValueError):
        data = _fallback_structure(title, len(pages), doc_type)
    return _normalize_structure(data, title, len(pages), doc_type)


def _chapter_parts(pages: list[str], start_page: int, end_page: int) -> list[str]:
    page_blocks = [f"<!-- page:{page_number} -->\n\n{pages[page_number - 1]}" for page_number in range(start_page, end_page + 1)]
    parts: list[str] = []
    current = ""
    for block in page_blocks:
        if current and len(current) + len(block) > MAX_CHAPTER_INPUT:
            parts.append(current)
            current = block
        else:
            current = f"{current}\n\n{block}".strip()
    if current:
        parts.append(current)
    return parts


def _clean_chapter(user_id: int, chapter: dict, pages: list[str], progress_text: str) -> str:
    outputs = []
    parts = _chapter_parts(pages, chapter["start_page"], chapter["end_page"])
    for part_index, part in enumerate(parts, 1):
        prompt = f"""章节标题：{chapter['title']}
章节摘要：{chapter.get('summary', '')}
关键词：{'、'.join(chapter.get('key_terms') or [])}
这是本章第 {part_index}/{len(parts)} 个连续片段。请恢复为结构清晰的 Markdown。

{part}"""
        outputs.append(chat_with_user_model(user_id, CHAPTER_SYSTEM_PROMPT, prompt, temperature=0.05).strip())
    body = "\n\n".join(output for output in outputs if output)
    return f"## {chapter['title']}\n\n{body}".strip()


def _clean_complete_document(user_id: int, title: str, pages: list[str]) -> str:
    """Reconstruct a short complete document in one model call to avoid overlap."""
    source = "\n\n".join(
        f"<!-- page:{page_number} -->\n\n{text}" for page_number, text in enumerate(pages, 1)
    )
    prompt = f"文档标题：{title}\n总页数：{len(pages)}\n\n完整分页原文：\n{source}"
    body = chat_with_user_model(user_id, COMPLETE_DOCUMENT_SYSTEM_PROMPT, prompt, temperature=0.03).strip()
    fenced = re.fullmatch(r"```(?:markdown|md)?\s*(.*?)\s*```", body, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        body = fenced.group(1).strip()
    body = re.sub(rf"(?i)^#\s+{re.escape(title)}\s*\n+", "", body, count=1).strip()
    if not re.search(r"(?m)^##\s+", body):
        body = f"## 正文\n\n{body}"
    return f"# {title}\n\n{body}".strip()


def _deduplicate_markdown(markdown: str) -> str:
    """Drop exact repeated prose blocks while preserving headings and page anchors."""
    blocks = re.split(r"\n{2,}", markdown.strip())
    seen: set[str] = set()
    output: list[str] = []
    for block in blocks:
        normalized = re.sub(r"\s+", "", re.sub(r"<!--.*?-->", "", block)).lower()
        protected = block.lstrip().startswith(("#", "<!-- page:", "```", "|"))
        if not protected and len(normalized) >= 30 and normalized in seen:
            continue
        output.append(block.strip())
        if len(normalized) >= 30:
            seen.add(normalized)
    result = "\n\n".join(output)
    result = re.sub(r"\\\((.+?)\\\)", r"$\1$", result, flags=re.DOTALL)
    result = re.sub(r"\\\[(.+?)\\\]", r"$$\1$$", result, flags=re.DOTALL)
    return result.strip()


def _structure_from_markdown(markdown: str, title: str, page_count: int, doc_type: str) -> dict:
    """Build navigation metadata from a complete reconstructed Markdown document."""
    headings = [match.group(1).strip() for match in re.finditer(r"(?m)^##\s+(.+?)\s*$", markdown)]
    if not headings:
        headings = ["正文"]
    # Compact documents are reconstructed as one continuous source. Page ranges are
    # intentionally not invented from heading positions that the model cannot prove.
    return {
        "document_title": title,
        "document_kind": doc_type,
        "chapters": [{
            "title": headings[0],
            "start_page": 1,
            "end_page": page_count,
            "summary": "按完整原文一次性重建，章内标题保留在正文中。",
            "key_terms": headings[1:10],
        }],
    }


def _process_pages(
    user_id: int,
    title: str,
    doc_type: str,
    pages: list[str],
    progress: ProgressCallback | None,
) -> tuple[str, str, int, str]:
    if not pages:
        raise ValueError("文档没有可处理的正文。")
    if progress:
        progress(0, len(pages) + 1, "正在识别整份资料的章节结构")
    structure = _plan_structure(user_id, title, doc_type, pages)
    markdown_sections = [f"# {structure['document_title']}"]
    chapters = structure["chapters"]
    for index, chapter in enumerate(chapters, 1):
        if progress:
            progress(index, len(chapters), f"正在整理章节 {index}/{len(chapters)}：{chapter['title']}")
        markdown_sections.append(_clean_chapter(user_id, chapter, pages, chapter["title"]))
    original = "\n\n".join(f"[PAGE {index}]\n{text}" for index, text in enumerate(pages, 1))
    return original, "\n\n".join(markdown_sections), len(pages), json.dumps(structure, ensure_ascii=False)


def _process_file(
    user_id: int,
    path: Path,
    title: str,
    doc_type: str,
    progress: ProgressCallback | None,
    force: bool = False,
    cancel_check: Callable[[], bool] | None = None,
) -> tuple[str, str, int, str]:
    from src.agent.document_processing_agent import DocumentProcessingAgent

    result = DocumentProcessingAgent(user_id, progress=progress, cancel_check=cancel_check).run(path, title, doc_type, force=force)
    return result.original_text, result.markdown, result.page_count, result.structure_json


def process_document(
    user_id: int,
    file_path: str | Path,
    title: str,
    doc_type: str,
    folder_id: int | None = None,
    progress: ProgressCallback | None = None,
    library_scope: str = "custom",
    is_global: bool = False,
) -> int:
    """Plan the whole document, clean it chapter by chapter, then rebuild its local index."""
    path = Path(file_path)
    document_id = create_document_record(
        user_id,
        doc_type,
        title,
        str(path),
        folder_id,
        path.suffix.lower().lstrip("."),
        library_scope,
        is_global,
    )
    try:
        original, markdown, page_count, structure_json = _process_file(user_id, path, title, doc_type, progress)
        chunks = split_text(markdown, chunk_size=1200, overlap=180)
        finish_document_processing(user_id, document_id, original, markdown, chunks, page_count, structure_json)
        return document_id
    except Exception as exc:
        fail_document_processing(user_id, document_id, str(exc))
        raise


def reprocess_document(
    user_id: int,
    document_id: int,
    progress: ProgressCallback | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> int:
    """Rebuild an existing document in place with the currently selected model."""
    document = get_document(user_id, document_id)
    if not document:
        raise ValueError("资料不存在或无权访问。")
    path = Path(document.get("file_path") or "")
    if not path.exists():
        raise FileNotFoundError(f"原始文件不存在：{path}")
    execute(
        "UPDATE documents SET processing_status = 'processing', processing_error = NULL, updated_at = ? WHERE id = ? AND user_id = ?",
        (now_iso(), document_id, user_id),
    )
    try:
        original, markdown, page_count, structure_json = _process_file(
            user_id,
            path,
            document["title"],
            document["doc_type"],
            progress,
            force=True,
            cancel_check=cancel_check,
        )
        chunks = split_text(markdown, chunk_size=1200, overlap=180)
        finish_document_processing(user_id, document_id, original, markdown, chunks, page_count, structure_json)
        return document_id
    except Exception as exc:
        from src.agent.document_processing_agent import DocumentProcessingCancelled

        if isinstance(exc, DocumentProcessingCancelled):
            execute(
                """
                UPDATE documents
                SET processing_status = 'ready', processing_error = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (str(exc), now_iso(), document_id, user_id),
            )
            raise
        if document.get("processed_markdown"):
            execute(
                "UPDATE documents SET processing_status = 'ready', processing_error = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                (str(exc)[:1000], now_iso(), document_id, user_id),
            )
        else:
            fail_document_processing(user_id, document_id, str(exc))
        raise
