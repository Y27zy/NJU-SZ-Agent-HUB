"""Turn a long, structured Markdown document into study-sized child documents."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re


_CHAPTER_HEADING = re.compile(r"(?m)^##(?!#)\s+(.+?)\s*$")
_SECTION_HEADING = re.compile(r"(?m)^###(?!#)\s+(.+?)\s*$")
_PAGE_ANCHOR = re.compile(r"<!--\s*page\s*:\s*(\d+)\s*-->", re.IGNORECASE)
_MAJOR_SECTION = re.compile(r"^\s*(\d+)\.(\d+)(?!\.)\s*(.*)$")
_SUBSECTION = re.compile(r"^\s*(\d+)\.(\d+)\.\d+\s*(.*)$")
_NUMBERED_EXERCISE = re.compile(r"^\s*习题\s*(\d+)\.(\d+)\s*$")
_CHAPTER_EXERCISE = re.compile(r"^\s*习题\s*[一二三四五六七八九十百\d]+\s*$")

MIN_COLLECTION_PAGES = 80
MIN_COLLECTION_CHARACTERS = 100_000
MIN_SECTION_CHARACTERS = 6_000
TARGET_SECTION_CHARACTERS = 12_000
MAX_SECTION_CHARACTERS = 20_000


@dataclass(frozen=True)
class StudySection:
    section_key: str
    title: str
    group_title: str
    markdown: str
    sort_order: int
    source_start_page: int | None
    source_end_page: int | None


@dataclass(frozen=True)
class DocumentHierarchy:
    title: str
    toc_markdown: str
    sections: tuple[StudySection, ...]


@dataclass(frozen=True)
class _Unit:
    title: str
    markdown: str


def should_publish_as_collection(markdown: str, page_count: int) -> bool:
    """Only fan out genuinely long documents with a useful chapter structure."""
    chapter_count = len(_CHAPTER_HEADING.findall(markdown or ""))
    section_count = len(_SECTION_HEADING.findall(markdown or ""))
    has_structure = chapter_count >= 2 or (chapter_count == 1 and section_count >= 4)
    return has_structure and (
        int(page_count or 0) >= MIN_COLLECTION_PAGES
        or len(markdown or "") >= MIN_COLLECTION_CHARACTERS
    )


def build_document_hierarchy(markdown: str, title: str, page_count: int) -> DocumentHierarchy | None:
    """Build deterministic chapter groups and bounded study documents."""
    source = (markdown or "").strip()
    if not should_publish_as_collection(source, page_count):
        return None

    chapter_matches = list(_CHAPTER_HEADING.finditer(source))
    preamble = source[: chapter_matches[0].start()].strip()
    packed_sections: list[tuple[str, str, str]] = []

    for chapter_index, match in enumerate(chapter_matches):
        chapter_end = chapter_matches[chapter_index + 1].start() if chapter_index + 1 < len(chapter_matches) else len(source)
        group_title = _clean_heading(match.group(1))
        chapter_body = source[match.end() : chapter_end].strip()
        if chapter_index == 0 and preamble:
            chapter_body = f"{preamble}\n\n{chapter_body}".strip()

        units = _chapter_units(chapter_body, group_title)
        for unit in units:
            body = unit.markdown.strip()
            child_markdown = f"# {unit.title}\n\n## {group_title}\n\n{body}".strip()
            packed_sections.append((group_title, unit.title, child_markdown))

    seen_keys: dict[str, int] = {}
    sections: list[StudySection] = []
    for sort_order, (group_title, section_title, child_markdown) in enumerate(packed_sections, 1):
        seed = f"{_normalise_key_text(group_title)}\n{_normalise_key_text(_identity_title(section_title))}"
        occurrence = seen_keys.get(seed, 0) + 1
        seen_keys[seed] = occurrence
        section_key = hashlib.sha1(f"{seed}\n{occurrence}".encode("utf-8")).hexdigest()[:20]
        pages = [int(value) for value in _PAGE_ANCHOR.findall(child_markdown)]
        sections.append(
            StudySection(
                section_key=section_key,
                title=section_title,
                group_title=group_title,
                markdown=child_markdown,
                sort_order=sort_order,
                source_start_page=min(pages) if pages else None,
                source_end_page=max(pages) if pages else None,
            )
        )

    if len(sections) < 2:
        return None
    return DocumentHierarchy(
        title=title,
        toc_markdown=_build_toc(title, sections, page_count),
        sections=tuple(sections),
    )


def _chapter_units(body: str, group_title: str) -> list[_Unit]:
    matches = list(_SECTION_HEADING.finditer(body))
    if not matches:
        return [_Unit(group_title, body)]

    prefix = body[: matches[0].start()].strip()
    heading_units: list[_Unit] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        unit_body = body[match.start() : end].strip()
        if index == 0 and prefix:
            unit_body = f"{prefix}\n\n{unit_body}"
        heading_units.append(_Unit(_clean_heading(match.group(1)), unit_body))
    return _merge_major_sections(heading_units)


def _merge_major_sections(units: list[_Unit]) -> list[_Unit]:
    """Keep a complete x.y textbook section together, including all x.y.z headings."""
    merged: list[dict[str, str | list[str] | None]] = []
    current: dict[str, str | list[str] | None] | None = None

    def start(title: str, markdown: str, key: str | None, kind: str) -> None:
        nonlocal current
        current = {"title": title, "parts": [markdown], "key": key, "kind": kind}
        merged.append(current)

    for unit in units:
        exercise = _NUMBERED_EXERCISE.match(unit.title)
        chapter_exercise = _CHAPTER_EXERCISE.match(unit.title)
        major = _MAJOR_SECTION.match(unit.title)
        subsection = _SUBSECTION.match(unit.title)

        if exercise:
            key = f"{exercise.group(1)}.{exercise.group(2)}"
            start(f"习题 {key}", unit.markdown, key, "exercise")
            continue
        if chapter_exercise:
            start(unit.title, unit.markdown, None, "exercise")
            continue
        if major:
            key = f"{major.group(1)}.{major.group(2)}"
            if current is not None and current["key"] == key and current["kind"] == "section":
                parts = current["parts"]
                assert isinstance(parts, list)
                parts.append(unit.markdown)
            else:
                start(unit.title, unit.markdown, key, "section")
            continue
        if subsection:
            key = f"{subsection.group(1)}.{subsection.group(2)}"
            if current is not None and current["key"] is None and current["kind"] == "provisional":
                current["key"] = key
                current["title"] = f"{key} {current['title']}"
                current["kind"] = "section"
                parts = current["parts"]
                assert isinstance(parts, list)
                parts.append(unit.markdown)
            elif current is None or current["key"] != key or current["kind"] == "exercise":
                suffix = subsection.group(3).strip()
                start(f"{key} {suffix}".strip(), unit.markdown, key, "section")
            else:
                parts = current["parts"]
                assert isinstance(parts, list)
                parts.append(unit.markdown)
            continue

        if current is None:
            start(unit.title, unit.markdown, None, "section")
        elif current["kind"] == "exercise" and not unit.title.startswith("习题"):
            start(unit.title, unit.markdown, None, "provisional")
        elif current["kind"] == "provisional" or current["key"] is not None:
            parts = current["parts"]
            assert isinstance(parts, list)
            parts.append(unit.markdown)
        elif current["kind"] == "exercise":
            parts = current["parts"]
            assert isinstance(parts, list)
            parts.append(unit.markdown)
        else:
            start(unit.title, unit.markdown, None, "section")

    result: list[_Unit] = []
    for item in merged:
        parts = item["parts"]
        assert isinstance(parts, list)
        result.append(_Unit(str(item["title"]), "\n\n".join(parts)))
    return result


def _split_oversize_unit(unit: _Unit) -> list[_Unit]:
    if len(unit.markdown) <= MAX_SECTION_CHARACTERS:
        return [unit]

    matches = list(_PAGE_ANCHOR.finditer(unit.markdown))
    if len(matches) < 2:
        paragraphs = [value.strip() for value in re.split(r"\n{2,}", unit.markdown) if value.strip()]
        if len(paragraphs) < 2:
            return [unit]
        groups = _pack_markdown_blocks(paragraphs)
        if len(groups) < 2:
            return [unit]
        return [
            _Unit(unit.title if index == 0 else f"{unit.title}（续 {index + 1}）", value)
            for index, value in enumerate(groups)
        ]

    prefix = unit.markdown[: matches[0].start()].strip()
    blocks: list[str] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(unit.markdown)
        blocks.append(unit.markdown[match.start() : end].strip())
    if prefix:
        blocks[0] = f"{prefix}\n\n{blocks[0]}"

    groups = _pack_markdown_blocks(blocks)
    return [
        _Unit(unit.title if index == 0 else f"{unit.title}（续 {index + 1}）", value)
        for index, value in enumerate(groups)
    ]


def _pack_markdown_blocks(blocks: list[str]) -> list[str]:
    groups: list[str] = []
    current = ""
    for block in blocks:
        candidate = f"{current}\n\n{block}".strip() if current else block
        if current and len(candidate) > TARGET_SECTION_CHARACTERS:
            groups.append(current)
            current = block
        else:
            current = candidate
    if current:
        groups.append(current)
    if len(groups) > 1 and len(groups[-1]) < MIN_SECTION_CHARACTERS:
        candidate = f"{groups[-2]}\n\n{groups[-1]}"
        if len(candidate) <= MAX_SECTION_CHARACTERS:
            groups[-2:] = [candidate]
    return groups


def _build_toc(title: str, sections: list[StudySection], page_count: int) -> str:
    lines = [f"# {title}", "", "本资料已按章节整理为若干个可独立学习的小节文档。", ""]
    current_group = None
    for section in sections:
        if section.group_title != current_group:
            current_group = section.group_title
            lines.extend([f"## {current_group}", ""])
        page_label = ""
        if section.source_start_page is not None:
            page_label = f"（第 {section.source_start_page}–{section.source_end_page} 页）"
        lines.append(f"- {section.title}{page_label}")
    if page_count:
        lines.extend(["", f"原始资料共 {page_count} 页。"])
    return "\n".join(lines).strip()


def _clean_heading(value: str) -> str:
    return re.sub(r"\s+#+\s*$", "", value).strip() or "未命名章节"


def _normalise_key_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _identity_title(value: str) -> str:
    """Ignore a pack-size suffix so small length changes can still reuse a child ID."""
    return re.sub(r"\s+等\s+\d+\s+节$", "", value).strip()
