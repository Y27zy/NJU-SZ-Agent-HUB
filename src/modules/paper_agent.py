from pathlib import Path

from src.agent.paper_research_agent import PaperResearchAgent
from src.rag.document_processor import process_document


def ingest_paper(user_id: int, file_path: str | Path, title: str) -> int:
    return process_document(user_id, file_path, title, "paper")


def _run(user_id: int, document_id: int | None, task: str, instruction: str) -> str:
    return PaperResearchAgent(user_id, document_id).run(task, instruction).answer


def summarize_paper(user_id: int, document_id: int | None = None) -> str:
    return _run(user_id, document_id, "完成论文 5 分钟速读", "依次输出研究问题、方法、创新点、实验、局限和组会亮点，并标出证据来自哪个章节。")


def extract_research_question(user_id: int, document_id: int | None = None) -> str:
    return _run(user_id, document_id, "提取研究问题", "说明背景、现有缺口、核心挑战、研究问题和重要性。")


def extract_contributions(user_id: int, document_id: int | None = None) -> str:
    return _run(user_id, document_id, "提取论文贡献", "区分方法贡献、实验贡献和应用价值，并给出论文内证据。")


def extract_method(user_id: int, document_id: int | None = None) -> str:
    return _run(user_id, document_id, "拆解论文方法", "按输入、关键模块、训练或推理流程、输出和复杂度风险组织。")


def extract_experiment_setup(user_id: int, document_id: int | None = None) -> str:
    return _run(user_id, document_id, "提取实验设置", "整理数据集、baseline、指标、主要结果、消融实验和公平性风险，不得编造数值。")


def extract_limitations(user_id: int, document_id: int | None = None) -> str:
    return _run(user_id, document_id, "分析论文局限", "区分作者承认的局限与 Agent 推断的复现风险，并说明依据。")


def translate_text(user_id: int, text: str, target_language: str = "中文") -> str:
    return PaperResearchAgent(user_id).translate(text, target_language).answer


def generate_presentation_outline(user_id: int, document_id: int | None = None) -> str:
    return _run(user_id, document_id, "生成 10 分钟组会汇报", "按页给出标题、讲述目标、核心图表建议和时间分配。")


def generate_reproduction_checklist(user_id: int, document_id: int | None = None) -> str:
    return _run(user_id, document_id, "生成论文复现清单", "覆盖数据、环境、模型、训练、指标、对照表格、随机性和失败风险，使用可勾选列表。")
