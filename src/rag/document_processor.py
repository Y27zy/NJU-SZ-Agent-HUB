import base64
import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from src.database import execute, now_iso
from src.llm.gateway import chat_with_user_messages, chat_with_user_model
from src.rag.document_parser import parse_document
from src.rag.document_assets import bind_document_images, extract_pdf_images
from src.rag.simple_vector_store import (
    create_document_record,
    fail_document_processing,
    finish_document_processing,
    get_document,
)
from src.rag.text_splitter import split_text


ProgressCallback = Callable[[int, int, str], None]
MAX_STRUCTURE_INPUT = 52000
# Keep each long-document request small enough to finish reliably on hosted
# OpenAI-compatible endpoints. Chapters can span many parts and are resumed
# part by part by DocumentProcessingAgent.
MAX_CHAPTER_INPUT = 4500


def _retry_attempts_for_part(character_count: int, chapter_part_count: int) -> int:
    """Allocate a bounded retry budget from the amount of chapter work at risk."""
    if character_count >= 14000 or chapter_part_count >= 8:
        return 6
    if character_count >= 9000 or chapter_part_count >= 4:
        return 5
    return 4
_PAGE_ANCHOR = re.compile(r"<!--\s*page\s*:\s*(\d+)\s*-->", re.IGNORECASE)
_FRONT_MATTER_TERMS = (
    "版权所有", "copyright", "出版社", "出版发行", "出版者", "出版日期", "印刷", "印次",
    "isbn", "cip", "图书在版编目", "责任编辑", "装帧设计", "定价", "版次", "编著", "主编",
    "译者", "作者简介", "内容简介", "preface", "foreword", "前言", "序言", "序 ",
)
_OUTLINE_TERMS = ("目录", "contents", "目 录")

STRUCTURE_SYSTEM_PROMPT = """你是大学教材与学术论文的结构化编辑。你的任务不是总结内容，而是恢复整份文档的真实目录结构。
请综合所有分页片段，识别封面、目录、章、节、附录和参考文献，并合并重复页眉页脚。
输入中会把封面、版权/出版信息、前言、目录标成“仅结构参考”或“跳过正文”。这些页面可用于判断章节名称，
但不得成为章节正文；同样排除纯致谢、课程结束、欢迎提问、Thank You、Questions/Q&A、联系方式、纯装饰页和无学习信息的过场页。
只输出一个合法 JSON 对象，不要使用 Markdown 代码围栏。格式必须是：
{"document_title":"标题","document_kind":"course|paper|other","chapters":[{"title":"章节标题","start_page":1,"end_page":3,"summary":"一句话说明本章内容","key_terms":["术语"]}]}
要求：chapters 按页码递增；页码范围覆盖正文；章节标题简洁、具体、不得使用“第1部分”这类空泛名称；
论文优先识别 Abstract、Introduction、Related Work、Method、Experiments、Conclusion、References；
课件优先依据页内大标题和主题转折划分，不能把每一页机械地当成一章。
同一页上的多个目录项或小标题属于章内层级，不能分别输出为多个重叠章节；每个 start_page 只能对应一个章节。"""

CHAPTER_SYSTEM_PROMPT = r"""你是南京大学课程资料的数字化排版编辑。把给定章节恢复成忠于原文、适合网页精读的 Markdown 正文。
严格要求：
1. 不总结替代原文，不添加资料中不存在的事实；去除重复页眉、页脚、页码噪声和 OCR 重复文本。
   输入若注明“跳过正文”或“仅结构参考”，不得把该页内容写入 Markdown；封面、作者、出版社、版权、版次、前言、目录
   都不能成为学习正文。目录项仅可帮助理解层级，不能作为知识内容重复输出。
2. 不输出本章的二级标题，调用方会统一添加；章内主题使用 ###，更细层级使用 ####。
3. 修复 PDF 造成的断行、连字符、项目符号和中英文空格，使段落完整，禁止把整章挤成一个段落。
4. 定义、定理、结论、注意事项使用引用块；步骤和并列关系使用列表；表格恢复为 Markdown 表格。
5. 所有数学表达必须恢复为 LaTeX：行内公式使用 $...$，独立公式使用 $$...$$。不要使用 \(...\)、\[...\] 或裸露反斜杠公式。
6. 保留输入中的 <!-- page:N --> 页码锚点，并把它放在对应页面内容之前。
7. 只保留能帮助理解概念、推导、流程、实验结果或表格数据的图。若输入在页尾提示“可用原图 N 张”，
   且该页确有必要保留的图，请在对应位置写唯一标记 [图：简短且具体的图示说明]；系统会把标记绑定为原始 PDF 图片。
   不要保留装饰图、学校/品牌 Logo、教师照片、课堂致辞页、Thank You、欢迎提问、纯抛硬币/骰子等已被正文充分表达的直观配图。
   不要生成 ![](...)、placeholder、file:// 或任何虚构图片链接。
8. 纯致谢、课程结束、欢迎提问、Thank You、Questions/Q&A、联系方式和无学习信息的过场内容必须删除，
   即使它们出现在输入中也不要输出。
9. 无法可靠识别的字符写成 [待核对]，不要凭空猜测。
只输出 Markdown 正文。"""

COMPLETE_DOCUMENT_SYSTEM_PROMPT = r"""你是文档数字化处理 Agent。输入是一份较短的完整资料，而不是需要扩写的提纲。
请逐页恢复为忠于原文、适合网页精读的 Markdown，并遵守：
1. 保留全部有效信息，不总结、不扩写、不补充外部知识。
   输入若注明“跳过正文”或“仅结构参考”，不得把该页内容写入 Markdown；封面、作者、出版社、版权、版次、前言、目录
   均不属于学习正文，目录项只能帮助恢复后续标题层级。
2. 目录或总览只保留一次；绝不能在每个主题前重复考试说明、摘要、作者或目录。
3. 根据原文层级使用 ##、###、#### 标题；同一页可有多个章内标题，不要为了每个目录词复制页面正文。
4. 保留 <!-- page:N --> 锚点。修复 PDF 断行、项目符号和中英文空格；代码使用带语言标识的代码块。
5. 表格恢复为 Markdown 表格；数学表达使用 $...$ 或 $$...$$，不用 \(...\) 或 \[...\]。
6. 只保留能帮助理解概念、推导、流程、实验结果或表格数据的图。输入在页尾可能标注“可用原图 N 张”；
   只有需要保留时才写 [图：简短且具体的图示说明]，系统会自动绑定 PDF 原图。不得保留装饰图、Logo、教师照片、
   致谢/结束/提问页，或已被正文充分表达的简单抛硬币、骰子等直观配图；不可臆造图中内容，也绝不生成 placeholder、file:// 或虚构图片链接。
7. 删除纯致谢、课程结束、欢迎提问、Thank You、Questions/Q&A、联系方式和无学习信息的过场内容。
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


def _page_role(page_text: str, page_number: int, page_count: int) -> str:
    """Classify non-learning textbook pages without relying on a brittle title list."""
    text = " ".join(page_text.split())
    lowered = text.lower()
    compact = re.sub(r"[\W_]+", "", lowered, flags=re.UNICODE)
    if any(term.replace(" ", "") in compact for term in _CLOSING_PAGE_TERMS):
        return "skip"
    if page_number <= min(page_count, 32):
        if any(term.replace(" ", "") in compact for term in _OUTLINE_TERMS):
            return "outline"
        has_front_matter = any(term.replace(" ", "") in compact for term in _FRONT_MATTER_TERMS)
        # A real textbook first chapter can mention an author or edition in a
        # sentence.  Only short, metadata-shaped front pages are omitted.
        metadata_shaped = len(compact) <= 2100 or sum(marker in text for marker in ("ISBN", "ISBN", "Copyright", "版权所有")) >= 1
        if has_front_matter and metadata_shaped:
            return "skip"
        has_teaching_signal = bool(re.search(r"第\s*[一二三四五六七八九十0-9]+\s*章|chapter\s*\d|定义|定理|函数|算法|实验", text, re.IGNORECASE))
        if page_number <= 3 and len(compact) <= 550 and not has_teaching_signal:
            return "skip"
    return "content"


def _classify_document_pages(pages: list[str]) -> dict[int, str]:
    """Return per-page editorial roles used by planning and reconstruction."""
    return {number: _page_role(text, number, len(pages)) for number, text in enumerate(pages, 1)}


_CHAPTER_HEADING = re.compile(
    r"(?i)^(?:第\s*[一二三四五六七八九十百零〇0-9]+\s*章\s*.*|chapter\s+\d+\b.*)$"
)


def _structure_from_chapter_starts(
    title: str,
    doc_type: str,
    page_count: int,
    starts: list[tuple[str, int]],
    page_roles: dict[int, str],
) -> dict | None:
    """Build a coarse, reliable chapter plan from bookmarks or page headings."""
    deduplicated: list[tuple[str, int]] = []
    seen_pages: set[int] = set()
    seen_headings: set[str] = set()
    seen_chapter_numbers: set[str] = set()
    for heading, page in sorted(starts, key=lambda item: item[1]):
        cleaned = re.sub(r"\s+", " ", heading).strip(" -_:：")
        heading_key = re.sub(r"[\W_]+", "", cleaned, flags=re.UNICODE).lower()
        lowered = cleaned.lower()
        chapter_match = re.match(r"^第\s*([〇一二三四五六七八九十百零0-9]+)\s*章", cleaned)
        chapter_number = chapter_match.group(1) if chapter_match else ""
        # Answer keys and self-tests are useful source material, but are not
        # part of the explanatory textbook body shown in the study reader.
        non_body_heading = any(
            marker in lowered
            for marker in (
                "习题答案",
                "参考答案",
                "习题解答",
                "自测题",
                "答案与提示",
                "exercise answers",
                "exercises answers",
                "answer key",
                "solutions",
            )
        )
        # Scanned textbooks often OCR a running chapter header at the top of
        # every page.  A repeated heading is not a new chapter boundary.
        if (
            page in seen_pages
            or not cleaned
            or not heading_key
            or heading_key in seen_headings
            or non_body_heading
            or (chapter_number and chapter_number in seen_chapter_numbers)
            or page_roles.get(page, "content") != "content"
        ):
            continue
        deduplicated.append((cleaned[:120], page))
        seen_pages.add(page)
        seen_headings.add(heading_key)
        if chapter_number:
            seen_chapter_numbers.add(chapter_number)
    if not deduplicated:
        return None
    chapters = []
    for index, (heading, page) in enumerate(deduplicated):
        end = deduplicated[index + 1][1] - 1 if index + 1 < len(deduplicated) else page_count
        chapters.append({"title": heading, "start_page": page, "end_page": max(page, end), "summary": "", "key_terms": []})
    return _normalize_structure(
        {"document_title": title, "document_kind": doc_type, "chapters": chapters},
        title,
        page_count,
        doc_type,
        page_roles,
    )


def _structure_from_pdf_bookmarks(
    path: str | Path,
    title: str,
    doc_type: str,
    pages: list[str],
    page_roles: dict[int, str],
) -> dict | None:
    """Use trustworthy PDF chapter bookmarks before asking a model to infer them."""
    path = Path(path)
    if path.suffix.lower() != ".pdf" or not path.exists():
        return None
    import fitz

    try:
        with fitz.open(path) as document:
            toc = document.get_toc(simple=True)
    except Exception:
        return None
    starts = []
    for level, heading, page in toc:
        normalized = str(heading).strip()
        if not _CHAPTER_HEADING.match(normalized):
            continue
        # Some badly-bookmarked scans use one numeric bookmark per page.  A
        # chapter title must carry more information than just a page number.
        if re.fullmatch(r"\d+", normalized):
            continue
        starts.append((normalized, int(page)))
    return _structure_from_chapter_starts(title, doc_type, len(pages), starts, page_roles)


def _structure_from_page_headings(
    title: str,
    doc_type: str,
    pages: list[str],
    page_roles: dict[int, str],
) -> dict | None:
    """Find chapter-opening headings when a PDF has no usable bookmark outline."""
    starts: list[tuple[str, int]] = []
    for page_number, page_text in enumerate(pages, 1):
        if page_roles.get(page_number, "content") != "content":
            continue
        for line in page_text.splitlines()[:24]:
            candidate = re.sub(r"\s+", " ", line).strip()
            if _CHAPTER_HEADING.match(candidate):
                starts.append((candidate, page_number))
                break
    return _structure_from_chapter_starts(title, doc_type, len(pages), starts, page_roles)


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


def _structure_source(pages: list[str], page_roles: dict[int, str] | None = None) -> str:
    page_roles = page_roles or {}
    if len(pages) > 80:
        # A book-scale input cannot fit every page in one planning request.
        # Keep any early outline pages and evenly sample the learning pages so
        # later chapters are visible instead of being swallowed by chapter one.
        learning = [number for number in range(1, len(pages) + 1) if page_roles.get(number, "content") == "content"]
        samples = min(34, len(learning))
        evenly_spaced = {
            learning[round(index * (len(learning) - 1) / max(1, samples - 1))]
            for index in range(samples)
        }
        outline_pages = {number for number in range(1, min(len(pages), 36) + 1) if page_roles.get(number) == "outline"}
        selected_pages = sorted(evenly_spaced | outline_pages)
    else:
        selected_pages = list(range(1, len(pages) + 1))
    budget_per_page = max(700, min(2400, MAX_STRUCTURE_INPUT // max(1, len(selected_pages))))
    parts = []
    for page_number in selected_pages:
        text = pages[page_number - 1]
        compact = re.sub(r"\n{3,}", "\n\n", text.strip())
        role = page_roles.get(page_number, "content")
        label = {
            "skip": "跳过正文",
            "outline": "仅结构参考",
            "content": "知识正文",
        }.get(role, "知识正文")
        parts.append(f"[PAGE {page_number} | {label}]\n{compact[:budget_per_page]}")
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


def _normalize_structure(
    data: dict,
    title: str,
    page_count: int,
    doc_type: str,
    page_roles: dict[int, str] | None = None,
) -> dict:
    page_roles = page_roles or {}
    learning_pages = [page for page in range(1, page_count + 1) if page_roles.get(page, "content") == "content"]
    if not learning_pages:
        learning_pages = list(range(1, page_count + 1))

    def first_learning_page(start: int, end: int) -> int | None:
        return next((page for page in learning_pages if start <= page <= end), None)

    def last_learning_page(start: int, end: int) -> int | None:
        return next((page for page in reversed(learning_pages) if start <= page <= end), None)

    chapters = []
    for item in data.get("chapters") or []:
        try:
            raw_start = max(1, min(page_count, int(item.get("start_page", 1))))
            raw_end = max(raw_start, min(page_count, int(item.get("end_page", raw_start))))
        except (TypeError, ValueError):
            continue
        start = first_learning_page(raw_start, raw_end)
        end = last_learning_page(raw_start, raw_end)
        if start is None or end is None:
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
    chapters = list(unique_starts.values())[: max(1, min(page_count, 32))]
    used_titles: Counter[str] = Counter()
    for chapter in chapters:
        used_titles[chapter["title"]] += 1
        if used_titles[chapter["title"]] > 1:
            chapter["title"] = f"{chapter['title']}（续）"
    chapters[0]["start_page"] = learning_pages[0]
    for index in range(len(chapters) - 1):
        chapters[index]["end_page"] = max(chapters[index]["start_page"], chapters[index + 1]["start_page"] - 1)
    chapters[-1]["end_page"] = learning_pages[-1]
    return {
        "document_title": str(data.get("document_title") or title).strip()[:200],
        "document_kind": doc_type,
        "chapters": chapters,
    }


def _plan_structure(
    user_id: int,
    title: str,
    doc_type: str,
    pages: list[str],
    page_roles: dict[int, str] | None = None,
) -> dict:
    prompt = f"文档名：{title}\n资料类型：{doc_type}\n总页数：{len(pages)}\n\n分页内容：\n{_structure_source(pages, page_roles)}"
    response = chat_with_user_model(user_id, STRUCTURE_SYSTEM_PROMPT, prompt, temperature=0.05)
    try:
        data = _extract_json(response)
    except (json.JSONDecodeError, TypeError, ValueError):
        data = _fallback_structure(title, len(pages), doc_type)
    return _normalize_structure(data, title, len(pages), doc_type, page_roles)


def _chapter_parts(
    pages: list[str],
    start_page: int,
    end_page: int,
    figure_hints: dict[int, int] | None = None,
    page_roles: dict[int, str] | None = None,
) -> list[str]:
    figure_hints = figure_hints or {}
    page_roles = page_roles or {}
    page_blocks = []
    for page_number in range(start_page, end_page + 1):
        if page_roles.get(page_number, "content") != "content":
            continue
        figure_hint = figure_hints.get(page_number, 0)
        suffix = f"\n\n[系统提示：本页可用原图 {figure_hint} 张，请仅按教学必要性决定是否输出 [图：说明]。]" if figure_hint else ""
        page_blocks.append(f"<!-- page:{page_number} -->\n\n{pages[page_number - 1]}{suffix}")
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


def _clean_chapter(
    user_id: int,
    chapter: dict,
    pages: list[str],
    progress_text: str,
    figure_hints: dict[int, int] | None = None,
    page_roles: dict[int, str] | None = None,
    part_cache: dict[str, str] | None = None,
    on_part_complete: Callable[[str, str], None] | None = None,
    before_part: Callable[[], None] | None = None,
    on_part_progress: Callable[[int, int], None] | None = None,
    on_part_error: Callable[[str, int, int, Exception], None] | None = None,
) -> str:
    """Rebuild one chapter with resumable, content-addressed part calls."""
    outputs = []
    if part_cache is None:
        part_cache = {}
    parts = _chapter_parts(pages, chapter["start_page"], chapter["end_page"], figure_hints, page_roles)
    for part_index, part in enumerate(parts, 1):
        if before_part:
            before_part()
        if on_part_progress:
            on_part_progress(part_index, len(parts))
        part_key = f"{part_index}:{hashlib.sha1(part.encode('utf-8')).hexdigest()[:16]}"
        cached_output = str(part_cache.get(part_key) or "").strip()
        if cached_output:
            outputs.append(cached_output)
            continue
        prompt = f"""章节标题：{chapter['title']}
章节摘要：{chapter.get('summary', '')}
关键词：{'、'.join(chapter.get('key_terms') or [])}
这是本章第 {part_index}/{len(parts)} 个连续片段。请恢复为结构清晰的 Markdown。

{part}"""
        try:
            output = chat_with_user_model(
                user_id,
                CHAPTER_SYSTEM_PROMPT,
                prompt,
                temperature=0.05,
                max_attempts=_retry_attempts_for_part(len(part), len(parts)),
            ).strip()
        except Exception as exc:
            if on_part_error:
                on_part_error(part_key, part_index, len(parts), exc)
            raise
        if before_part:
            before_part()
        if output:
            outputs.append(output)
            if on_part_complete:
                on_part_complete(part_key, output)
    body = "\n\n".join(output for output in outputs if output)
    return f"## {chapter['title']}\n\n{body}".strip()


def _clean_complete_document(
    user_id: int,
    title: str,
    pages: list[str],
    figure_hints: dict[int, int] | None = None,
    page_roles: dict[int, str] | None = None,
) -> str:
    """Reconstruct a short complete document in one model call to avoid overlap."""
    figure_hints = figure_hints or {}
    page_roles = page_roles or {}
    source = "\n\n".join(
        f"<!-- page:{page_number} -->\n\n{text}"
        + (f"\n\n[系统提示：本页可用原图 {figure_hints[page_number]} 张，请仅按教学必要性决定是否输出 [图：说明]。]" if page_number in figure_hints else "")
        for page_number, text in enumerate(pages, 1)
        if page_roles.get(page_number, "content") == "content"
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


_CLOSING_PAGE_TERMS = (
    "本讲结束",
    "本节结束",
    "课程结束",
    "欢迎提问",
    "谢谢观看",
    "谢谢聆听",
    "感谢聆听",
    "感谢观看",
    "thank you",
    "thanks",
    "questions",
    "q&a",
)


def _remove_non_learning_markdown(markdown: str) -> str:
    """Remove isolated presentation-closing content after model reconstruction.

    This is deliberately conservative: a page is removed only when its complete
    textual payload is a short closing message.  Normal teaching pages that
    merely contain a final ""欢迎提问"" line retain their substantive content.
    """
    parts = _PAGE_ANCHOR.split(markdown)
    if len(parts) == 1:
        return markdown
    output = [parts[0]]
    for index in range(1, len(parts), 2):
        page_number = parts[index]
        segment = parts[index + 1] if index + 1 < len(parts) else ""
        plain = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", segment)
        plain = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", plain)
        plain = re.sub(r"[\W_]+", "", plain, flags=re.UNICODE).lower()
        has_closing = any(term.replace(" ", "") in plain for term in _CLOSING_PAGE_TERMS)
        without_closing = plain
        for term in _CLOSING_PAGE_TERMS:
            without_closing = without_closing.replace(term.replace(" ", ""), "")
        if has_closing and len(without_closing) <= 8:
            continue
        cleaned_blocks = []
        for block in re.split(r"\n{2,}", segment):
            block_plain = re.sub(r"[\W_]+", "", block, flags=re.UNICODE).lower()
            is_short_closing = (
                len(block_plain) <= 52
                and any(term.replace(" ", "") in block_plain for term in _CLOSING_PAGE_TERMS)
            )
            if not is_short_closing:
                cleaned_blocks.append(block)
        output.extend([f"<!-- page:{page_number} -->", "\n\n".join(cleaned_blocks)])
    return "".join(output).strip()


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


def _should_resume_processing(document: dict) -> bool:
    """Resume the last failed/cancelled run; rebuild a clean ready document."""
    status = str(document.get("processing_status") or "ready").lower()
    return status != "ready" or bool(str(document.get("processing_error") or "").strip())


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
        markdown = bind_document_images(markdown, extract_pdf_images(document_id, path))
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
    resume_from_cache = _should_resume_processing(document)
    visible_status = "ready" if document.get("processed_markdown") else "processing"
    execute(
        "UPDATE documents SET processing_status = ?, processing_error = NULL, updated_at = ? WHERE id = ? AND user_id = ?",
        (visible_status, now_iso(), document_id, user_id),
    )
    try:
        original, markdown, page_count, structure_json = _process_file(
            user_id,
            path,
            document["title"],
            document["doc_type"],
            progress,
            force=not resume_from_cache,
            cancel_check=cancel_check,
        )
        markdown = bind_document_images(markdown, extract_pdf_images(document_id, path))
        chunks = split_text(markdown, chunk_size=1200, overlap=180)
        finish_document_processing(user_id, document_id, original, markdown, chunks, page_count, structure_json)
        return document_id
    except Exception as exc:
        from src.agent.document_processing_agent import DocumentProcessingCancelled

        if isinstance(exc, DocumentProcessingCancelled):
            execute(
                """
                UPDATE documents
                SET processing_status = ?, processing_error = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                ("ready" if document.get("processed_markdown") else "error", str(exc), now_iso(), document_id, user_id),
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
