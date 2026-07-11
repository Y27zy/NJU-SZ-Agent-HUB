import re

from src.database import execute, fetch_all, fetch_one, now_iso
from src.llm.gateway import chat_with_user_model
from src.rag.simple_vector_store import get_document, get_document_chunks, search_document_chunks


ACTION_PROMPTS = {
    "explain": """解释选中原文。依次给出：一句话结论、直觉理解、原文中的符号或概念、逐步推理、容易误解之处。
每一步必须能从上下文核对；出现数学公式时使用规范 LaTeX。""",
    "example": """围绕选中原文设计一个最小但完整的例子。先说明设定，再给数据或条件，逐步计算或验证，最后对应回原文概念。
不要只作比喻；优先给大学课程中可手算、可复现的例子。""",
    "solve": """判断选区是否包含题目。若是题目，先列已知与目标，再逐步推导并在末尾验算；若不是题目，给出它在典型题目中的使用方式。
不得跳过关键推导，所有公式使用规范 LaTeX。""",
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
) -> str:
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

回答约束：
- 只依据资料与必要的基础知识回答，引用原文时保持原意。
- 先给读者最需要的结论，再展开推理，避免空泛复述。
- Markdown 层级从 ### 开始，不要输出一级标题。
- 行内公式使用 $...$，独立公式使用 $$...$$；不要把 LaTeX 放进代码块。
- 资料不足时明确指出，不得编造页码、实验结果或定义。"""
    answer = chat_with_user_model(
        user_id,
        "你是南京大学苏州校区学生的学术阅读导师。你严谨、清晰、重视可核对性，擅长把数学和机器学习材料讲到读者真正理解。",
        prompt,
        temperature=0.25,
    )
    x, y = _next_canvas_position(user_id, document_id)
    execute(
        """
        INSERT INTO document_questions
        (user_id, document_id, action_type, selected_text, context_mode, context_snapshot,
         answer, canvas_x, canvas_y, updated_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, document_id, action_type, selected_text, context_mode, context[:12000], answer, x, y, now_iso(), now_iso()),
    )
    return answer


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


def generate_mindmap(user_id: int, document_id: int) -> str:
    document = get_document(user_id, document_id)
    if not document:
        raise ValueError("资料不存在或无权访问。")
    context = (document.get("processed_markdown") or "")[:60000]
    content = chat_with_user_model(
        user_id,
        "你负责把大学课程与论文整理成层级严格、可复习的知识地图。",
        """根据资料生成 Markdown 层级知识地图。
要求：第一行使用 # 根主题；只使用 ##、###、#### 表示层级；节点必须是短语；
优先呈现章节关系、核心概念、方法步骤、公式之间的依赖和常见应用；不得增加资料中不存在的分支。

资料：
""" + context,
        temperature=0.15,
    )
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
