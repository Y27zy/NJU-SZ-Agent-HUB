# NJU-SZ Agent Hub

南京大学苏州校区学生 Agent Hub

## 1. 项目简介

NJU-SZ Agent Hub 是一个面向南京大学苏州校区学生的一站式校园 Agent 平台。项目用于机器学习导论课程大项目，重点展示工程结构、Agent 思想、RAG、分层记忆、多模型 API 适配和学生场景实用性。

“NJU-SZ Agent Hub 不是一个单一问答机器人，而是一个面向学生真实场景的多功能 Agent 平台。系统围绕课程学习、科研阅读、时间管理和饮食决策四类高频需求，结合 RAG、工具调用、分层记忆、动态思维树和多模型统一接口，构建一个可扩展的校园个人 AI 助手原型。”

默认情况下，系统使用 `MockLLMProvider`，不需要任何真实 API Key，也可以离线运行基础 Demo。如果用户在页面中配置真实 API Base URL、API Key 和模型名称，则会通过统一 LLM Gateway 调用真实大模型。

## 2. 项目背景

大学生在学习和科研场景中经常需要处理课程资料、论文阅读、任务规划和生活决策。传统聊天机器人通常只提供单轮问答能力，难以组织长期偏好、外部知识库和可执行任务。本项目希望用轻量、可读、容易跑通的方式，把 Agent 系统常见组件组合成一个课程项目原型。

## 3. 为什么不是简单聊天机器人

本项目不是把所有问题都扔给一个聊天框，而是拆成多个具有明确职责的 Agent 模块：

- Course Agent 处理课程资料上传、检索、总结、练习题与参考答案。
- Paper Agent 处理论文速读、创新点提取、翻译、组会大纲和复现 checklist。
- Todo Agent 处理自然语言任务解析、任务存储和计划生成。
- Food Agent 处理食堂随机推荐和校外餐厅推荐。
- Memory Agent 维护用户偏好、会话状态和文档知识。
- LLM Gateway 统一适配 Mock、Qwen、Kimi、DeepSeek、智谱和 Custom Provider。

## 4. 功能模块

- 用户账号：注册、登录、退出登录、用户隔离数据、保存模型配置。
- 模型配置：支持用户自定义 `provider`、`api_base`、`api_key`、`model_name`。
- 课程学习：上传 PDF/PPTX/TXT/Markdown，构建课程知识库并问答。
- 科研论文：上传论文 PDF，生成摘要、创新点、组会大纲、复现 checklist。
- Todo 规划：自然语言解析任务，生成今日计划和本周计划。
- 分层记忆：Working Memory、User Memory、Knowledge Memory。
- Dynamic Thought Tree：为复杂规划任务生成候选方案、评分并选择最佳方案。
- 美食推荐：基于示例数据推荐校外餐厅或随机食堂窗口。

## 5. 系统架构图

```text
+-----------------------------+
|        Streamlit UI          |
| Login Dashboard Course Paper |
| Todo Food Memory Settings    |
+--------------+--------------+
               |
               v
+-----------------------------+
|         Agent Modules        |
| Course | Paper | Todo | Food |
+--------------+--------------+
               |
       +-------+--------+----------------+
       |                |                |
       v                v                v
+-------------+  +--------------+  +-------------+
| LLM Gateway |  | RAG Pipeline |  | Memory      |
| Mock/Real   |  | Parser/TFIDF |  | 3 Layers    |
+------+------+  +------+-------+  +------+------+
       |                |                |
       v                v                v
+-----------------------------------------------+
|              SQLite storage/app.db             |
| users configs documents chunks todos memories  |
+-----------------------------------------------+
```

## 6. 技术栈

- Python 3.10+
- Streamlit
- SQLite
- PyMuPDF
- python-pptx
- python-dotenv
- requests
- hashlib PBKDF2 password hashing
- scikit-learn `TfidfVectorizer` 轻量检索

项目不强依赖 LangChain，Agent 框架和 LLM Gateway 使用轻量手写实现，便于课程展示和后续扩展。

## 7. 项目目录结构

```text
nju-sz-agent-hub/
├── app.py
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── data/
│   ├── restaurants.json
│   ├── canteen_foods.json
│   └── sample_course.txt
├── storage/
│   ├── .gitkeep
│   └── uploads/
│       └── .gitkeep
├── src/
│   ├── __init__.py
│   ├── config.py
│   ├── database.py
│   ├── auth/
│   ├── llm/
│   ├── agent/
│   ├── memory/
│   ├── rag/
│   ├── modules/
│   └── ui/
└── scripts/
    ├── init_db.py
    ├── seed_demo.py
    ├── smoke_test.py
    └── export_readme_to_pdf.md
```

## 8. 快速开始

推荐使用课程环境：

```bash
D:\miniconda3\envs\IntroML\python.exe -m pip install -r requirements.txt
D:\miniconda3\envs\IntroML\python.exe scripts/init_db.py
D:\miniconda3\envs\IntroML\python.exe -m streamlit run app.py
```

通用命令：

```bash
pip install -r requirements.txt
python scripts/init_db.py
streamlit run app.py
```

如果 `streamlit` 命令不在 PATH 中，可以使用：

```bash
python -m streamlit run app.py
```

打开 Streamlit 页面后，先注册账号，再登录使用。

也可以生成一个带示例课程资料、Todo 和记忆的 demo 账号：

```bash
python scripts/seed_demo.py
```

默认账号：

```text
username: demo
password: password123
```

交付前可运行烟测脚本：

```bash
python scripts/smoke_test.py
```

如果修改了模型配置页或模型调用逻辑，可以运行：

```bash
python scripts/verify_model_fix.py
```

## 9. 环境变量配置

复制 `.env.example` 为 `.env` 后可按需修改：

```env
APP_NAME=NJU-SZ Agent Hub
DATABASE_URL=sqlite:///storage/app.db
DEFAULT_PROVIDER=mock
DEFAULT_MODEL=mock-agent
USE_SYSTEM_PROXY=false
```

不创建 `.env` 也可以运行，系统会使用默认配置。

## 10. 如何配置自己的大模型 API

进入侧边栏 `模型配置 Model Settings` 页面，填写：

- Provider：`openai-compatible`、`qwen`、`kimi`、`deepseek`、`zhipu` 或 `custom`
- API Base URL：例如 `https://api.example.com/v1`
- API Key：你的服务商密钥
- Model Name：例如 `deepseek-chat`、`qwen-plus` 等

当前实现统一走 OpenAI-compatible Chat Completions 风格接口：

```text
POST {api_base}/chat/completions
```

请求体：

```json
{
  "model": "model_name",
  "messages": [],
  "temperature": 0.7
}
```

注意：课程 Demo 中 API Key 暂时明文保存在本地 SQLite。正式部署时必须使用加密存储、环境变量、KMS 或后端密钥管理服务。

模型配置页会记录用户保存过的模型，用户可以在下拉框中选择任意已保存模型并设为当前使用模型，也可以点击测试连接。系统会自动修正常见 API Base 写法，例如用户填入完整的 `/chat/completions` 地址时，会自动转换为 Base URL。

如果 Windows 上出现 `WinError 10013`，通常与系统代理、杀毒软件或防火墙拦截有关。本项目默认设置 `USE_SYSTEM_PROXY=false`，避免 `requests` 自动读取错误的系统代理环境变量；如果你确实需要通过系统代理访问 API，可以在 `.env` 中设置：

```env
USE_SYSTEM_PROXY=true
```

## 11. 三层分层记忆系统说明

本项目不用简单聊天记录作为记忆，而是拆成三层：

- Working Memory：当前会话状态，例如最近输入、当前任务类型、当前文档，可放在 `st.session_state`。
- User Memory：用户长期偏好，例如常用课程、解释风格、研究兴趣、饮食偏好，存入 `memory_items`。
- Knowledge Memory：外部知识，例如课程资料 chunks、论文 chunks 和上传文档内容，存入 `document_chunks`。

这种设计的好处是：会话状态、用户偏好和外部知识具有不同生命周期和检索方式，分开管理更容易解释、调试和扩展。

## 12. Dynamic Thought Tree 设计说明

`src/agent/thought_tree.py` 实现轻量 Dynamic Thought Tree：

1. 对复杂任务生成多个候选方案。
2. 对每个方案按可执行性、时间结构和优先级表达评分。
3. 选择最高分方案。
4. 输出最终计划，并保留候选方案用于展示。

当前版本是课程项目原型，不追求复杂树搜索；它的目标是展示 Agent 在复杂规划任务中可以先生成、再评估、最后选择，而不是直接输出单个答案。

## 13. RAG 工作流说明

课程和论文模块共用轻量 RAG 流程：

```text
上传文件 -> 文档解析 -> 文本切分 -> 写入 SQLite chunks
        -> TF-IDF 检索 -> 构造上下文 -> LLM Gateway 生成回答
```

支持格式：

- PDF：PyMuPDF
- PPTX：python-pptx
- TXT/Markdown：原生文本读取

当前检索使用 `TfidfVectorizer`，后续可以把 `simple_vector_store.py` 替换为 FAISS、Chroma 或向量数据库。

## 14. 数据库表设计

`users`

- `id`
- `username`
- `password_hash`
- `created_at`

`user_model_configs`

- `id`
- `user_id`
- `provider`
- `api_base`
- `api_key`
- `model_name`
- `is_default`
- `created_at`

`documents`

- `id`
- `user_id`
- `doc_type`
- `title`
- `file_path`
- `created_at`

`document_chunks`

- `id`
- `document_id`
- `user_id`
- `doc_type`
- `chunk_index`
- `content`
- `created_at`

`todos`

- `id`
- `user_id`
- `title`
- `description`
- `deadline`
- `priority`
- `status`
- `created_at`

`todo_subtasks`

- `id`
- `todo_id`
- `user_id`
- `title`
- `status`
- `created_at`

`memory_items`

- `id`
- `user_id`
- `memory_type`
- `content`
- `importance`
- `created_at`
- `last_accessed_at`

## 15. Demo 使用流程

1. 运行 `python scripts/init_db.py` 初始化数据库。
2. 运行 `streamlit run app.py` 启动前端。
3. 注册并登录一个测试账号。
4. 进入 `课程学习 Course Agent`，上传 `data/sample_course.txt`。
5. 提问：`PCA 和 LDA 有什么区别？`
6. 点击 `生成练习题` 或 `总结重点`。
7. 进入 `Todo 规划 Todo Agent`，使用默认示例输入解析任务。
8. 点击 `生成本周计划 Dynamic Thought Tree` 查看候选方案和评分。
9. 进入 `美食推荐 Food Agent` 测试食堂随机推荐。
10. 进入 `记忆管理 Memory` 保存一个学习偏好，再检索上下文。

## 16. 后续可扩展方向

- 将 TF-IDF 检索替换为 Embedding + FAISS/Chroma。
- 对 API Key 做加密存储。
- 引入真实地图 API 或校园众包数据改进餐厅推荐。
- 增加课程表导入和日历同步。
- 增加论文 BibTeX 管理和自动引用。
- 加入多模型投票、冲突裁决和成本控制。
- 增加单元测试、端到端测试和 Docker 部署。

## 17. README 转 PDF 方法

可以使用 Pandoc：

```bash
pandoc README.md -o NJU-SZ-Agent-Hub-README.pdf
```

也可以使用 Typora、VS Code Markdown PDF 插件或浏览器打印功能导出 PDF。`scripts/export_readme_to_pdf.md` 中也记录了简要方法。

## 18. 课程项目说明

本项目是机器学习导论课程大项目原型，目标是展示一个完整但轻量的 AI Agent 系统工程结构。系统默认使用 `MockLLMProvider` 保证离线可运行；真实大模型 API 属于可选增强能力。部分数据为示例数据，不代表真实商家或校区官方信息。正式上线需要补充安全、隐私、加密、权限、稳定性和合规处理。
