import re
from collections.abc import Callable

from src.database import execute, fetch_all, fetch_one, now_iso
from src.agent.reading_agent import ReadingAgent
from src.rag.simple_vector_store import get_document, get_document_chunks, search_document_chunks


ACTION_PROMPTS = {
    "explain": """解释选中原文。依次给出：一句话结论、直觉理解、原文中的符号或概念、逐步推理、容易误解之处。
每一步必须能从上下文核对；出现数学公式时使用规范 LaTeX。""",
    "example": """围绕选中原文设计一个最小但完整的例子。先说明设定，再给数据或条件，逐步计算或验证，最后对应回原文概念。
不要只作比喻；优先给大学课程中可手算、可复现的例子。""",
    "solve": """判断选区是否包含题目。若是题目，先列已知与目标，再逐步推导并在末尾验算；若不是题目，给出它在典型题目中的使用方式。
不得跳过关键推导，所有公式使用规范 LaTeX。""",
    "variable": """解释选区中每个关键符号或变量。依次说明：对象类型、取值范围、在当前公式中的作用、与相邻符号的关系。
若同一符号可能有多种含义，只采用当前上下文能支持的解释。""",
    "why": """回答“为什么这一步成立”。明确指出使用的定义、定理、假设或变换规则，并逐步检查适用条件。
若原文省略了中间步骤，补全推导；若条件不足，指出还缺什么。""",
    "socratic": """使用苏格拉底式辅导，不要直接灌输完整结论。先判断读者当前理解，提出一个最关键且可回答的问题；
根据资料给出必要提示，并说明回答后下一步应检查什么。一次只推进一个认知台阶。""",
    "question": "回答用户关于选中内容的问题。先直接回答，再用原文证据和必要推导支撑；资料不足时明确说明缺失信息。",
}

CONTEXT_LABELS = {
    "selection": "仅使用划选文字",
    "paragraph": "划选文字所在段落及相邻段落",
    "section": "从最近的章节标题到下一同级章节之前",
    "rag": "从整份资料检索最相关的 5 个片段",
    "document": "使用整份资料（过长时截取前 60000 字符）",
}


def list_folders(user_id: int) -> list[dict]:
    return [dict(row) for row in fetch_all("SELECT * FROM library_folders WHERE user_id = ? ORDER BY name", (user_id,))]


def ensure_default_folders(user_id: int) -> list[dict]:
    """Create the small set of top-level library folders used by the upload dialog."""
    folders = list_folders(user_id)
    existing = {str(folder["name"]).strip() for folder in folders if folder.get("parent_id") is None}
    for name in ("课程资料", "论文研读", "其他资料"):
        if name not in existing:
            create_folder(user_id, name)
    return list_folders(user_id)


def create_folder(user_id: int, name: str, parent_id: int | None = None) -> int:
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("文件夹名称不能为空。")
    return execute(
        "INSERT INTO library_folders (user_id, name, parent_id, created_at) VALUES (?, ?, ?, ?)",
        (user_id, clean_name, parent_id, now_iso()),
    )


def _find_selection(markdown: str, selected_text: str) -> int:
    location = markdown.find(selected_text)
    if location >= 0:
        return location
    probe = re.sub(r"\s+", " ", selected_text).strip()[:100]
    if not probe:
        return -1
    pattern = r"\s+".join(re.escape(part) for part in probe.split())
    match = re.search(pattern, markdown, flags=re.DOTALL)
    return match.start() if match else -1


def _paragraph_context(markdown: str, selected_text: str) -> str:
    blocks = [block.strip() for block in re.split(r"\n\s*\n", markdown) if block.strip()]
    normalized = re.sub(r"\s+", " ", selected_text).strip()
    index = next(
        (
            index
            for index, block in enumerate(blocks)
            if normalized and normalized[:80] in re.sub(r"\s+", " ", block)
        ),
        -1,
    )
    if index < 0:
        return selected_text
    return "\n\n".join(blocks[max(0, index - 1) : min(len(blocks), index + 2)])


def _section_context(markdown: str, selected_text: str) -> str:
    location = _find_selection(markdown, selected_text)
    if location < 0:
        return _paragraph_context(markdown, selected_text)
    headings = list(re.finditer(r"(?m)^(#{1,4})\s+(.+?)\s*$", markdown))
    preceding = [match for match in headings if match.start() <= location]
    if not preceding:
        return markdown[: min(len(markdown), 7000)]
    start_heading = preceding[-1]
    level = len(start_heading.group(1))
    end = len(markdown)
    for match in headings:
        if match.start() > start_heading.start() and len(match.group(1)) <= level:
            end = match.start()
            break
    return markdown[start_heading.start() : end][:14000]


def build_reading_context(user_id: int, document_id: int, selected_text: str, mode: str) -> str:
    document = get_document(user_id, document_id)
    if not document:
        raise ValueError("资料不存在或无权访问。")
    markdown = document.get("processed_markdown") or document.get("original_text") or ""
    if mode == "selection":
        return selected_text
    if mode == "paragraph":
        return _paragraph_context(markdown, selected_text)
    if mode == "section":
        return _section_context(markdown, selected_text)
    if mode == "document":
        return markdown[:60000]
    if mode == "rag":
        matches = search_document_chunks(user_id, document_id, selected_text, top_k=5)
        return "\n\n".join(f"[相关片段 {index}]\n{item['content']}" for index, item in enumerate(matches, 1)) or selected_text
    return selected_text


def _next_canvas_position(user_id: int, document_id: int) -> tuple[int, int]:
    question_count = fetch_one(
        "SELECT COUNT(*) AS count FROM document_questions WHERE user_id = ? AND document_id = ?",
        (user_id, document_id),
    )
    mindmap_count = fetch_one(
        "SELECT COUNT(*) AS count FROM document_mindmaps WHERE user_id = ? AND document_id = ?",
        (user_id, document_id),
    )
    count = int(question_count["count"] if question_count else 0) + int(mindmap_count["count"] if mindmap_count else 0)
    return 28 + (count % 4) * 34, 72 + (count % 6) * 38


def ask_about_selection(
    user_id: int,
    document_id: int,
    selected_text: str,
    action_type: str,
    context_mode: str,
    custom_question: str = "",
    cancel_check: Callable[[], bool] | None = None,
    *,
    anchor_start: int | None = None,
    anchor_end: int | None = None,
    parent_question_id: int | None = None,
    learning_prompt: str = "",
) -> dict:
    document = get_document(user_id, document_id)
    if not document:
        raise ValueError("资料不存在或无权访问。")
    context = build_reading_context(user_id, document_id, selected_text, context_mode)
    instruction = ACTION_PROMPTS.get(action_type, ACTION_PROMPTS["question"])
    question = custom_question.strip() or instruction
    prompt = f"""# 阅读任务
资料：{document['title']}
上下文策略：{CONTEXT_LABELS.get(context_mode, context_mode)}

## 可用上下文
{context}

## 用户划选原文
{selected_text}

## 具体任务
{question}

## 读者偏好的讲解方式
{learning_prompt.strip() or "未设置，使用清晰、循序渐进的大学课程讲解风格。"}

回答约束：
- 只依据资料与必要的基础知识回答，引用原文时保持原意。
- 先给读者最需要的结论，再展开推理，避免空泛复述。
- Markdown 层级从 ### 开始，不要输出一级标题。
- 行内公式使用 $...$，独立公式使用 $$...$$；不要把 LaTeX 放进代码块。
- 资料不足时明确指出，不得编造页码、实验结果或定义。"""
    def context_loader(_args: dict) -> dict:
        return {
            "title": document["title"],
            "context_mode": context_mode,
            "selected_text": selected_text,
            "content": context,
        }

    def document_loader(_args: dict) -> dict:
        markdown = document.get("processed_markdown") or document.get("original_text") or ""
        return {"title": document["title"], "content": markdown[:60000]}

    answer = ReadingAgent(user_id, document_id, context_loader, document_loader).answer(prompt, context_mode).answer
    if cancel_check and cancel_check():
        return answer
    x, y = _next_canvas_position(user_id, document_id)
    if cancel_check and cancel_check():
        return answer
    question_id = execute(
        """
        INSERT INTO document_questions
        (user_id, document_id, action_type, selected_text, context_mode, context_snapshot,
         answer, anchor_start, anchor_end, parent_question_id, canvas_x, canvas_y, updated_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            document_id,
            action_type,
            selected_text,
            context_mode,
            context[:12000],
            answer,
            anchor_start,
            anchor_end,
            parent_question_id,
            x,
            y,
            now_iso(),
            now_iso(),
        ),
    )
    return {"id": question_id, "answer": answer}


def list_document_questions(user_id: int, document_id: int) -> list[dict]:
    return [
        dict(row)
        for row in fetch_all(
            "SELECT * FROM document_questions WHERE user_id = ? AND document_id = ? ORDER BY id",
            (user_id, document_id),
        )
    ]


def list_document_mindmaps(user_id: int, document_id: int) -> list[dict]:
    return [
        dict(row)
        for row in fetch_all(
            "SELECT * FROM document_mindmaps WHERE user_id = ? AND document_id = ? ORDER BY id",
            (user_id, document_id),
        )
    ]


def add_canvas_note(user_id: int, document_id: int, title: str, content: str, action_type: str = "note") -> int:
    x, y = _next_canvas_position(user_id, document_id)
    return execute(
        """
        INSERT INTO document_questions
        (user_id, document_id, action_type, selected_text, context_mode, context_snapshot,
         answer, canvas_x, canvas_y, updated_at, created_at)
        VALUES (?, ?, ?, '', 'document', '', ?, ?, ?, ?, ?)
        """,
        (user_id, document_id, action_type, content, x, y, now_iso(), now_iso()),
    )


def generate_mindmap(
    user_id: int,
    document_id: int,
    cancel_check: Callable[[], bool] | None = None,
    source_text: str = "",
) -> str:
    document = get_document(user_id, document_id)
    if not document:
        raise ValueError("资料不存在或无权访问。")
    def document_loader(_args: dict) -> dict:
        markdown = document.get("processed_markdown") or document.get("original_text") or ""
        return {"title": document["title"], "content": (source_text.strip() or markdown)[:60000]}

    content = ReadingAgent(user_id, document_id, document_loader, document_loader).mindmap().answer
    if cancel_check and cancel_check():
        return content
    x, y = _next_canvas_position(user_id, document_id)
    execute(
        """
        INSERT INTO document_mindmaps
        (user_id, document_id, title, content, canvas_x, canvas_y, updated_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, document_id, document["title"], content, x, y, now_iso(), now_iso()),
    )
    return content


def add_highlight(user_id: int, document_id: int, selected_text: str, note: str = "") -> int:
    text = selected_text.strip()
    if not text:
        raise ValueError("请先划选要标记的原文。")
    existing = fetch_one(
        "SELECT id FROM document_highlights WHERE user_id = ? AND document_id = ? AND selected_text = ?",
        (user_id, document_id, text),
    )
    if existing:
        return int(existing["id"])
    return execute(
        "INSERT INTO document_highlights (user_id, document_id, selected_text, note, color, created_at) VALUES (?, ?, ?, ?, 'yellow', ?)",
        (user_id, document_id, text, note.strip(), now_iso()),
    )


def toggle_highlight_anchor(
    user_id: int,
    document_id: int,
    selected_text: str,
    anchor_start: int,
    anchor_end: int,
    context_prefix: str = "",
    context_suffix: str = "",
) -> tuple[bool, int | None]:
    """Toggle one exact rendered-text range instead of guessing by repeated text."""
    text = selected_text.strip()
    if not text or anchor_start < 0 or anchor_end <= anchor_start:
        raise ValueError("请选择有效的原文范围。")
    existing = fetch_one(
        """
        SELECT id FROM document_highlights
        WHERE user_id = ? AND document_id = ? AND anchor_start = ? AND anchor_end = ?
        """,
        (user_id, document_id, anchor_start, anchor_end),
    )
    if existing:
        highlight_id = int(existing["id"])
        delete_highlight(user_id, highlight_id)
        return False, highlight_id
    highlight_id = execute(
        """
        INSERT INTO document_highlights
        (user_id, document_id, selected_text, note, color, anchor_start, anchor_end,
         context_prefix, context_suffix, created_at)
        VALUES (?, ?, ?, '', 'yellow', ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            document_id,
            text,
            anchor_start,
            anchor_end,
            context_prefix[-120:],
            context_suffix[:120],
            now_iso(),
        ),
    )
    return True, highlight_id


def toggle_highlight(user_id: int, document_id: int, selected_text: str) -> bool:
    """Return True when a highlight is added, False when the existing one is removed."""
    text = selected_text.strip()
    if not text:
        raise ValueError("请先划选要标记的原文。")
    existing = fetch_one(
        "SELECT id FROM document_highlights WHERE user_id = ? AND document_id = ? AND selected_text = ?",
        (user_id, document_id, text),
    )
    if existing:
        delete_highlight(user_id, int(existing["id"]))
        return False
    add_highlight(user_id, document_id, text)
    return True


def list_highlights(user_id: int, document_id: int) -> list[dict]:
    return [
        dict(row)
        for row in fetch_all(
            "SELECT * FROM document_highlights WHERE user_id = ? AND document_id = ? ORDER BY id",
            (user_id, document_id),
        )
    ]


def delete_highlight(user_id: int, highlight_id: int) -> None:
    execute("DELETE FROM document_highlights WHERE id = ? AND user_id = ?", (highlight_id, user_id))


def delete_canvas_node(user_id: int, node_type: str, node_id: int) -> None:
    table = "document_questions" if node_type == "question" else "document_mindmaps"
    execute(f"DELETE FROM {table} WHERE id = ? AND user_id = ?", (node_id, user_id))


def update_canvas_node(
    user_id: int,
    node_type: str,
    node_id: int,
    *,
    content: str | None = None,
    x: int | None = None,
    y: int | None = None,
    width: int | None = None,
    height: int | None = None,
) -> None:
    table = "document_questions" if node_type == "question" else "document_mindmaps"
    content_column = "answer" if node_type == "question" else "content"
    assignments = ["updated_at = ?"]
    params: list[object] = [now_iso()]
    values = {
        content_column: content,
        "canvas_x": x,
        "canvas_y": y,
        "canvas_width": width,
        "canvas_height": height,
    }
    for column, value in values.items():
        if value is not None:
            assignments.append(f"{column} = ?")
            params.append(value)
    params.extend([node_id, user_id])
    execute(f"UPDATE {table} SET {', '.join(assignments)} WHERE id = ? AND user_id = ?", tuple(params))
