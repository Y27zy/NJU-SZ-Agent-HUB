import re


LATEX_HINTS = (
    "\\alpha",
    "\\beta",
    "\\boldsymbol",
    "\\begin",
    "\\end",
    "\\frac",
    "\\geq",
    "\\leq",
    "\\leftarrow",
    "\\mathbf",
    "\\sum",
    "\\theta",
    "\\top",
)


def normalize_markdown_math(text: str) -> str:
    """Normalize common LLM LaTeX delimiters for Streamlit Markdown rendering."""
    if not text:
        return ""

    normalized = text.replace("\\[", "$$").replace("\\]", "$$")
    normalized = normalized.replace("\\(", "$").replace("\\)", "$")

    lines = []
    in_code_block = False
    in_math_block = False
    for line in normalized.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            lines.append(line)
            continue
        if stripped == "$$":
            in_math_block = not in_math_block
            lines.append(line)
            continue
        if in_math_block:
            lines.append(line)
            continue
        if in_code_block or not stripped:
            lines.append(line)
            continue

        has_latex = any(hint in stripped for hint in LATEX_HINTS)
        already_math = "$" in stripped
        looks_like_block = stripped.startswith("[") and stripped.endswith("]")

        if has_latex and looks_like_block and not already_math:
            formula = stripped[1:-1].strip()
            lines.extend(["$$", formula, "$$"])
        elif has_latex and not already_math and not re.search(r"[\u4e00-\u9fff]", stripped):
            lines.extend(["$$", stripped, "$$"])
        else:
            lines.append(line)

    return "\n".join(lines)


def split_markdown_math_blocks(text: str) -> list[tuple[str, str]]:
    normalized = normalize_markdown_math(text)
    parts = re.split(r"\$\$(.*?)\$\$", normalized, flags=re.DOTALL)
    blocks: list[tuple[str, str]] = []
    for index, part in enumerate(parts):
        if not part:
            continue
        kind = "math" if index % 2 else "markdown"
        blocks.append((kind, part.strip() if kind == "math" else part))
    return blocks
