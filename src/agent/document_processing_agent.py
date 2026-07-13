import json
import re
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable

import numpy as np

from src.auth.auth_service import get_default_model_config
from src.llm.gateway import chat_with_user_model
from src.llm.providers import LLMProviderError
from src.rag.document_parser import parse_document
from src.rag.text_splitter import split_text


AUDIT_SYSTEM_PROMPT = """你是学术文档数字化的质量审计 Agent。检查结构化 Markdown 是否忠于原文并适合精读。
只输出合法 JSON，不要输出代码围栏：
{"pass":true,"issues":[{"chapter_title":"章节","problem":"问题","repair_instruction":"明确返修要求"}]}
重点检查：章节边界是否合理、标题是否具体、是否残留重复页眉页脚、段落是否被错误拼接、列表与表格是否恢复、
LaTeX 是否使用 $...$ 或 $$...$$、是否出现明显乱码、是否遗漏核心定义/公式/实验段落。
只报告能够从输入中确认的问题，不要要求补写原文不存在的内容。"""

REPAIR_SYSTEM_PROMPT = r"""你是文档处理 Agent 的返修编辑。根据质量审计意见修复一个章节的 Markdown。
保留原意、页码锚点和所有有效内容；只修复指出的问题；不得总结替代正文或补充资料外知识。
章内标题从 ### 开始；公式使用 $...$ 或 $$...$$；只输出返修后的章节正文，不输出章标题和说明。"""


@dataclass
class ProcessedDocument:
    original_text: str
    markdown: str
    page_count: int
    structure_json: str
    model_name: str
    audit_issues: list[dict]


class DocumentProcessingCancelled(RuntimeError):
    """Raised when a user cancels a document processing operation."""


class DocumentProcessingAgent:
    """Agent that plans, reconstructs, audits, and repairs one complete document."""

    VERSION = "3.3"

    def __init__(self, user_id: int, progress=None, cancel_check: Callable[[], bool] | None = None):
        self.user_id = user_id
        self.progress = progress
        self.cancel_check = cancel_check
        self.model_config = get_default_model_config(user_id)
        if not self.model_config:
            raise ValueError("尚未配置默认模型，无法启动文档处理 Agent。")

    @property
    def model_name(self) -> str:
        return str(self.model_config.get("model_name") or "unknown")

    def _notify(self, current: int, total: int, message: str) -> None:
        if self.progress:
            self.progress(current, total, message)

    def _raise_if_cancelled(self) -> None:
        if self.cancel_check and self.cancel_check():
            raise DocumentProcessingCancelled("用户已取消重新整理，已保留原有资料版本。")

    def _cache_path(self, source_path: Path) -> Path:
        return source_path.with_name(f".{source_path.name}.document-agent-cache.json")

    def _cache_signature(self, source_path: Path) -> dict:
        stat = source_path.stat()
        return {
            "agent_version": self.VERSION,
            "model": self.model_name,
            "size": stat.st_size,
            "mtime": int(stat.st_mtime),
        }

    def _load_cache(self, source_path: Path) -> dict:
        cache_path = self._cache_path(source_path)
        if not cache_path.exists():
            return {}
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            return data if data.get("signature") == self._cache_signature(source_path) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_cache(self, source_path: Path, cache: dict) -> None:
        cache["signature"] = self._cache_signature(source_path)
        self._cache_path(source_path).write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

    def _load_pages(self, path: Path) -> list[str]:
        from src.rag.document_processor import _extract_pdf_pages, _ocr_page_with_model

        if path.suffix.lower() == ".pdf":
            pages = _extract_pdf_pages(path)
            sparse_indexes = [index for index, text in enumerate(pages) if len(text.replace(" ", "")) < 12]
            if len(sparse_indexes) > 8:
                pages = self._local_ocr_pages(path, pages, sparse_indexes)
            else:
                for index in sparse_indexes:
                    self._notify(index + 1, len(pages), f"第 {index + 1} 页文本过少，正在调用视觉识别")
                    try:
                        pages[index] = _ocr_page_with_model(self.user_id, path, index + 1)
                    except LLMProviderError:
                        pages[index] = pages[index] or "[该页没有可提取文本，当前模型不支持视觉识别]"
            return pages
        raw_text = parse_document(path)
        return split_text(raw_text, chunk_size=6500, overlap=0) or [raw_text]

    def _local_ocr_pages(self, path: Path, pages: list[str], sparse_indexes: list[int]) -> list[str]:
        """Run one local OCR engine for scan-heavy PDFs instead of hundreds of LLM calls."""
        try:
            from rapidocr_onnxruntime import RapidOCR
            import fitz
        except ImportError as exc:
            raise ValueError(
                "该 PDF 主要由扫描页构成，需要本地 OCR。请安装 rapidocr_onnxruntime 后重新整理。"
            ) from exc

        self._notify(0, len(sparse_indexes), f"检测到 {len(sparse_indexes)} 个扫描页，正在使用本地 OCR")
        engine = RapidOCR()
        with fitz.open(path) as document:
            for current, index in enumerate(sparse_indexes, 1):
                self._raise_if_cancelled()
                page = document[index]
                pixmap = page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6), alpha=False)
                channels = 3 if pixmap.n >= 3 else 1
                image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, pixmap.n)[..., :channels]
                result, _ = engine(image)
                if result:
                    ordered = sorted(result, key=lambda item: (min(point[1] for point in item[0]), min(point[0] for point in item[0])))
                    pages[index] = "\n".join(str(item[1]).strip() for item in ordered if str(item[1]).strip())
                self._notify(current, len(sparse_indexes), f"本地 OCR：第 {index + 1} 页")
        return pages

    @staticmethod
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

    @staticmethod
    def _local_issues(markdown: str, structure: dict) -> list[dict]:
        issues = []
        for chapter in structure.get("chapters") or []:
            heading = f"## {chapter['title']}"
            if heading not in markdown:
                issues.append(
                    {
                        "chapter_title": chapter["title"],
                        "problem": "缺少规划中的章节标题",
                        "repair_instruction": "恢复该章节标题和正文边界。",
                    }
                )
        if "<!-- page:" not in markdown:
            issues.append(
                {
                    "chapter_title": "全文",
                    "problem": "缺少页码锚点",
                    "repair_instruction": "保留输入中的 <!-- page:N --> 锚点。",
                }
            )
        if re.search(r"\\\(|\\\[", markdown):
            issues.append(
                {
                    "chapter_title": "全文",
                    "problem": "仍有非统一数学定界符",
                    "repair_instruction": "把 \\(...\\) 和 \\[...\\] 改成 $...$ 与 $$...$$。",
                }
            )
        return issues

    def _audit(self, markdown: str, structure: dict) -> list[dict]:
        prompt = f"章节规划：\n{json.dumps(structure, ensure_ascii=False)}\n\n待检查 Markdown：\n{markdown[:30000]}"
        try:
            response = chat_with_user_model(self.user_id, AUDIT_SYSTEM_PROMPT, prompt, temperature=0.0)
        except LLMProviderError:
            self._notify(4, 5, "远程质量审计暂不可用，已保留本地结构检查结果")
            return []
        try:
            data = self._extract_json(response)
            issues = data.get("issues") or []
            return [issue for issue in issues if isinstance(issue, dict)][:12]
        except (json.JSONDecodeError, TypeError, ValueError):
            return []

    @staticmethod
    def _chapter_body(markdown: str, chapter_title: str) -> str:
        pattern = re.compile(
            rf"(?ms)^##\s+{re.escape(chapter_title)}\s*$\n(.*?)(?=^##\s+|\Z)",
        )
        match = pattern.search(markdown)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _replace_chapter(markdown: str, chapter_title: str, repaired_body: str) -> str:
        pattern = re.compile(
            rf"(?ms)(^##\s+{re.escape(chapter_title)}\s*$\n)(.*?)(?=^##\s+|\Z)",
        )
        return pattern.sub(lambda match: f"{match.group(1)}\n{repaired_body.strip()}\n\n", markdown, count=1)

    def _repair(self, markdown: str, issues: list[dict]) -> str:
        repaired = markdown
        chapter_issues: dict[str, list[str]] = {}
        for issue in issues:
            title = str(issue.get("chapter_title") or "").strip()
            if title and title != "全文":
                chapter_issues.setdefault(title, []).append(str(issue.get("repair_instruction") or issue.get("problem") or ""))
        for index, (title, instructions) in enumerate(chapter_issues.items(), 1):
            body = self._chapter_body(repaired, title)
            if not body:
                continue
            self._notify(index, len(chapter_issues), f"质量返修：{title}")
            prompt = f"章节：{title}\n审计意见：\n- " + "\n- ".join(instructions) + f"\n\n当前正文：\n{body[:26000]}"
            try:
                fixed = chat_with_user_model(self.user_id, REPAIR_SYSTEM_PROMPT, prompt, temperature=0.05).strip()
            except LLMProviderError:
                self._notify(index, len(chapter_issues), f"返修请求失败，保留原章节：{title}")
                continue
            if fixed:
                repaired = self._replace_chapter(repaired, title, fixed)
        return repaired

    @staticmethod
    def _cached_result(data: dict) -> ProcessedDocument | None:
        """Restore a completed result from a matching cache entry."""
        result = data.get("result")
        if not isinstance(result, dict):
            return None
        try:
            return ProcessedDocument(
                original_text=str(result["original_text"]),
                markdown=str(result["markdown"]),
                page_count=int(result["page_count"]),
                structure_json=str(result["structure_json"]),
                model_name=str(result["model_name"]),
                audit_issues=list(result.get("audit_issues") or []),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def run(self, path: str | Path, title: str, doc_type: str, force: bool = False) -> ProcessedDocument:
        from src.rag.document_processor import (
            _clean_chapter,
            _clean_complete_document,
            _classify_document_pages,
            _deduplicate_markdown,
            _document_profile,
            _plan_structure,
            _remove_non_learning_markdown,
            _structure_from_page_headings,
            _structure_from_pdf_bookmarks,
            _structure_from_markdown,
        )
        from src.rag.document_assets import inspect_pdf_figures

        source_path = Path(path)
        self._raise_if_cancelled()
        cache = self._load_cache(source_path)
        cached_result = self._cached_result(cache)
        if cached_result and not force:
            self._notify(5, 5, "已读取同一文件与模型的完整处理结果")
            return cached_result
        self._notify(0, 5, f"文档处理 Agent 已启动：{self.model_name}")
        cached_pages = cache.get("pages")
        if isinstance(cached_pages, list) and cached_pages:
            pages = [str(page) for page in cached_pages]
            self._notify(0, 5, "已恢复已完成的文本提取与 OCR 结果")
        else:
            pages = self._load_pages(source_path)
            # OCR is the most expensive local stage for scanned textbooks.  Keep
            # its result so a later model-network retry does not repeat it.
            cache["pages"] = pages
            self._save_cache(source_path, cache)
        self._raise_if_cancelled()
        if not pages:
            raise ValueError("文档没有可处理的正文。")

        profile = _document_profile(pages, title, doc_type)
        figure_hints = inspect_pdf_figures(source_path)
        page_roles = _classify_document_pages(pages)
        cache["profile"] = profile
        self._notify(1, 5, f"文档画像完成，采用 {profile['strategy']} 策略")

        if profile["strategy"] == "compact_complete":
            markdown = cache.get("complete_markdown")
            if not markdown:
                self._notify(2, 5, "正在一次性恢复完整短文档，避免章节重叠")
                markdown = _clean_complete_document(self.user_id, title, pages, figure_hints, page_roles)
                self._raise_if_cancelled()
                cache["complete_markdown"] = markdown
                self._save_cache(source_path, cache)
            structure = _structure_from_markdown(markdown, title, len(pages), doc_type)
        else:
            self._notify(1, 5, "正在读取教材书签与章节标题，规划真实主章节")
            structure = cache.get("structure")
            if not structure:
                structure = _structure_from_pdf_bookmarks(source_path, title, doc_type, pages, page_roles)
                if structure:
                    cache["planning_source"] = "pdf_bookmarks"
                    self._notify(1, 5, "已从 PDF 书签恢复章节，跳过整书目录猜测")
                else:
                    structure = _structure_from_page_headings(title, doc_type, pages, page_roles)
                    if structure:
                        cache["planning_source"] = "page_headings"
                        self._notify(1, 5, "已从正文主标题恢复章节，跳过整书目录猜测")
                if not structure:
                    self._notify(1, 5, "未找到可靠书签，正在由 Agent 规划主章节")
                    structure = _plan_structure(self.user_id, title, doc_type, pages, page_roles)
                    cache["planning_source"] = "agent_planning"
                self._raise_if_cancelled()
                cache["structure"] = structure
                cache["chapters"] = {}
                self._save_cache(source_path, cache)
            markdown_sections = [f"# {structure['document_title']}"]
            chapters = structure["chapters"]
            for index, chapter in enumerate(chapters, 1):
                cache_key = f"{chapter['start_page']}:{chapter['end_page']}:{chapter['title']}"
                chapter_markdown = (cache.get("chapters") or {}).get(cache_key)
                if chapter_markdown:
                    self._notify(index, len(chapters), f"读取已完成章节 {index}/{len(chapters)}：{chapter['title']}")
                else:
                    self._notify(index, len(chapters), f"重建主章节 {index}/{len(chapters)}：{chapter['title']}")
                    chapter_markdown = _clean_chapter(
                        self.user_id,
                        chapter,
                        pages,
                        chapter["title"],
                        figure_hints,
                        page_roles,
                    )
                    self._raise_if_cancelled()
                    cache.setdefault("chapters", {})[cache_key] = chapter_markdown
                    self._save_cache(source_path, cache)
                markdown_sections.append(chapter_markdown)
            markdown = "\n\n".join(markdown_sections)

        markdown = _remove_non_learning_markdown(_deduplicate_markdown(markdown))

        self._notify(4, 5, "正在执行本地完整性、重复内容与公式定界检查")
        issues = self._local_issues(markdown, structure)
        # Remote auditing used to add another full-document call and could cascade
        # into many repair calls. Deterministic checks now handle routine quality
        # control; the model is asked to repair only a concrete detected issue.
        if issues:
            markdown = self._repair(markdown, issues)
            self._raise_if_cancelled()
            markdown = _remove_non_learning_markdown(_deduplicate_markdown(markdown))

        structure["processing"] = {
            "agent": "DocumentProcessingAgent",
            "version": self.VERSION,
            "model": self.model_name,
            "strategy": profile["strategy"],
            "character_count": profile["character_count"],
            "audit_issue_count": len(issues),
            "learning_page_count": sum(role == "content" for role in page_roles.values()),
            "outline_page_count": sum(role == "outline" for role in page_roles.values()),
            "skipped_page_count": sum(role == "skip" for role in page_roles.values()),
            "structure_source": cache.get("planning_source", "cached"),
        }
        original = "\n\n".join(f"[PAGE {index}]\n{text}" for index, text in enumerate(pages, 1))
        self._notify(5, 5, "章节化文档已通过处理流水线")
        result = ProcessedDocument(
            original_text=original,
            markdown=markdown,
            page_count=len(pages),
            structure_json=json.dumps(structure, ensure_ascii=False),
            model_name=self.model_name,
            audit_issues=issues,
        )
        cache["result"] = {
            "original_text": result.original_text,
            "markdown": result.markdown,
            "page_count": result.page_count,
            "structure_json": result.structure_json,
            "model_name": result.model_name,
            "audit_issues": result.audit_issues,
        }
        self._save_cache(source_path, cache)
        return result
