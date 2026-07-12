# NJU-SZ Agent Hub

南京大学苏州校区学生 Agent Hub，是面向学习、科研、时间管理与校园生活的一站式课程项目原型。

> “NJU-SZ Agent Hub 不是一个单一问答机器人，而是一个面向学生真实场景的多功能 Agent 平台。系统围绕课程学习、科研阅读、时间管理和饮食决策四类高频需求，结合 RAG、工具调用、分层记忆、动态思维树和多模型统一接口，构建一个可扩展的校园个人 AI 助手原型。”

当前版本只调用用户明确配置并选中的真实模型 API，不包含 Mock 回答，也不会在调用失败时静默切换模型。

## 1. 项目背景

课程资料、论文、待办和个人偏好通常分散在不同工具里。本项目把文档处理、交互式阅读、Agent 工具与 RAG 组织到同一个学生工作台中，用于展示一个结构清楚、可以继续扩展的机器学习课程大项目。

## 2. 为什么不是简单聊天机器人

- Agent 在资料原文、任务列表和用户偏好等具体场景中工作。
- 用户可在原文中划选文字，直接执行解释、举例、解题和自由提问。
- 回答可选择选区、附近段落、章节、整份文档或 RAG 检索作为上下文。
- 课程资料与论文共用统一资料库，论文仍拥有专用研读工具。
- 复杂规划使用 Dynamic Thought Tree 生成多个候选计划并评分。

## 3. 功能模块

### Agent Runtime 与领域 Agent

项目中的“Agent”不是页面名称或一段角色提示词。`src/agent/runtime.py` 提供统一的轻量执行循环：

```text
用户目标与限制
  -> 模型生成工具计划（严格 JSON）
  -> Runtime 校验工具白名单与调用次数
  -> 执行 RAG / 数据库 / 偏好记忆 / Dynamic Thought Tree / 可选网络检索
  -> 模型基于工具证据合成结果
  -> agent_runs 保存计划、工具轨迹、结果与状态
```

当前领域 Agent 包括：

- `DocumentProcessingAgent`：抽取、OCR、结构侦察、章节恢复、质量审计与修复。
- `ReadingAgent`：根据选区、段落、章节、全文或 RAG 工具完成解释、举例、解题和知识地图。
- `CourseLearningAgent`：检索课程知识库后完成问答、总结和带答案练习题。
- `PaperResearchAgent`：读取与检索论文，完成速读、方法/实验/贡献分析、术语保护翻译和复现规划。
- `TodoPlanningAgent`：识别独立成果、截止时间与依赖，把复杂任务拆成有顺序的步骤，支持按截止日期、优先级、创建时间和完成时间排序，并调用 Dynamic Thought Tree 规划。
- `FoodDataAgent`：每七天检索南京大学苏州校区及周边公开饮食线索，只写入 `pending_review`，人工审核前绝不进入推荐池。
- `FoodAgent`：理解自然语言并选择食堂、附近堂食或外卖工具；具体对象由 Python 从已审核本地数据中严格筛选和加权随机选出，模型不能编造或代替随机选择。

账号、数据库、模型配置和文件存储仍然是基础设施服务，而不是强行包装成 Agent。领域 Agent 通过受控工具使用这些能力，这样更容易审计、测试和在课程展示中解释。

普通模块仅在需要时启用联网工具。FoodDataAgent 在饮食页面打开且资料超过 7 天时后台刷新，也可手动执行：

```bash
python scripts/update_food_data.py --username your_username --force
```

正式数据位于 `data/campus_foods.json`，编辑模板位于 `data/campus_foods.template.json`，更新状态位于 `data/campus_food_update_meta.json`。联网发现只新增待审核线索；人工批准或新增的记录会标记为 `origin=manual`、`locked=true`，周更新不会覆盖。

### FoodAgent 数据维护

`campus_foods.json` 使用 schema v2，并把三类正式推荐池分开保存：

- `canteen_dishes`：真实食堂、楼层、窗口、菜品、餐次、口味和价格。
- `restaurants`：真实附近餐厅、区域、推荐菜、人均、步行时间和适用人数。
- `takeaways`：真实可配送店铺、单品、平台、实付区间和配送时间。
- `pending_review`：联网发现的名称、来源链接和摘要，不参与推荐。

可以在美食页面的“数据维护（开发）”中手工新增、启停正式记录，或审核/忽略联网线索；也可以参照模板直接编辑 JSON。正式记录必须填写真实名称和具体菜品并设置 `enabled=true`。旧版 `venues/dishes/restaurants` 会在首次读取时自动迁移：具体菜品和餐厅尽量转入正式池，只有地点名称的旧记录保留为待审核线索，原有 `manual/locked` 标记不会丢失。损坏的 JSON 会备份为 `campus_foods.corrupt-时间.json` 后以空数据库启动。

推荐流程为：FoodAgent 提取模式和约束 -> 读取用户饮食记忆 -> 调用一个 `choose_*` Python 工具 -> 严格过滤预算、距离、餐次、忌口和停用记录 -> `random.choices` 从合格记录中选一个 -> 输出一到两句话。没有候选时返回 `no_match`，不会放宽硬条件或凭模型知识补写对象。

- 公开首页与右上角登录/注册，个人模块登录后开放。
- 订阅与模型：以用户自定义 Qwen、Kimi、DeepSeek、智谱及 OpenAI-compatible API 为主，平台订阅仅展示。
- 资料库：文件夹、PDF/PPTX/TXT/Markdown 上传、结构化转换、文档索引。
- 阅读器：原文划选、解释、举例、解题、自由提问、历史记录。
- 论文研读：速读、研究问题、方法、创新点、局限、组会大纲与复现清单。
- 思维导图：根据当前文档生成 Markdown 层级导图。
- Todo Agent、Dynamic Thought Tree、内部用户偏好与美食推荐。
- 平台体验额度页面：仅展示未来付费模式，不创建订单、不执行支付。

## 4. 系统架构

```text
+---------------------- Streamlit UI -----------------------+
| Public Home | Library Hall | Reader Workspace | Todo | Food | Subscription |
+-----------------------------+-----------------------------+
                              |
              +---------------+----------------+
              |                                |
              v                                v
+---------------------------+      +-------------------------+
| Document Production       |      | Agent Modules           |
| Extract -> OCR -> Clean MD |      | Reader/Paper/Todo/Food  |
+-------------+-------------+      +------------+------------+
              |                                 |
              v                                 v
+---------------------------+      +-------------------------+
| RAG: chunks + TF-IDF      |<---->| Unified LLM Gateway     |
+-------------+-------------+      +------------+------------+
              +-------------------+-------------+
                                  v
                        +-------------------+
                        | SQLite + uploads  |
                        +-------------------+
```

## 5. 技术栈

- Python 3.10+、Streamlit、SQLite
- PyMuPDF、python-pptx、Python Markdown、项目内置 KaTeX 0.16.46
- requests、python-dotenv
- scikit-learn `TfidfVectorizer`
- PBKDF2-SHA256 密码哈希
- 原生 Streamlit Component 协议实现划词阅读器

项目不依赖 LangChain，LLM Gateway、Agent 与记忆逻辑均为轻量手写实现。

## 6. 目录结构

```text
nju-sz-agent-hub/
├── app.py
├── README.md
├── requirements.txt
├── data/
├── storage/
├── scripts/
└── src/
    ├── agent/
    ├── auth/
    ├── llm/
    ├── memory/
    ├── modules/
    │   └── library_agent.py
    ├── rag/
    │   └── document_processor.py
    └── ui/
        ├── library_page.py
        └── components/selection_reader/
```

## 7. 快速开始

```powershell
cd D:\nju-sz-agent-hub
D:\miniconda3\envs\IntroML\python.exe -m pip install -r requirements.txt
D:\miniconda3\envs\IntroML\python.exe scripts\init_db.py
D:\miniconda3\envs\IntroML\python.exe -m streamlit run app.py --server.port 8502
```

浏览器打开 `http://localhost:8502`。首页无需登录；进入资料库等个人模块时再登录。

## 8. 环境变量

复制 `.env.example` 为 `.env`：

```env
APP_NAME=NJU-SZ Agent Hub
DATABASE_URL=sqlite:///storage/app.db
DEFAULT_PROVIDER=
DEFAULT_MODEL=
USE_SYSTEM_PROXY=false
```

若模型 API 必须经过系统代理，可设置 `USE_SYSTEM_PROXY=true`。

## 9. 配置自己的模型 API

登录后进入“订阅”，在“我的模型”区域选择服务商并填写：

- API Base URL，例如 `https://api.deepseek.com`
- API Key
- Model Name，例如 `deepseek-chat`

系统统一调用：

```text
POST {api_base}/chat/completions
```

保存前必须通过连接测试。API Key 当前明文保存在本地 SQLite；正式部署必须使用加密存储或密钥管理服务。

## 10. 文档转换流水线

```text
上传原文件
  -> DocumentProcessingAgent 取得用户当前默认模型
  -> PyMuPDF/python-pptx 提取并保留分页锚点
  -> 文字不足的页面调用多模态 OCR
  -> 全文结构侦察，生成严格章节 JSON
  -> 按章节分片恢复标题、段落、表格与 LaTeX
  -> 质量审计并只返修有问题的章节
  -> 章节检查点支持超时后断点续跑
  -> 保存原始文本和结构化 Markdown
  -> chunk 与 TF-IDF 索引
```

`DocumentProcessingAgent` 位于 `src/agent/document_processing_agent.py`。上传与“重新整理”统一调用该 Agent；它不会写死 Qwen，而是动态使用当前用户在“订阅”页面选中的默认模型。扫描 PDF 要求该模型支持 OpenAI-compatible 图片输入。转换遵循“忠于原文、不总结、不补写”的提示词，但 AI 识别仍可能出错，重要公式和数据应对照原 PDF 核验。

## 11. 交互式阅读与上下文

阅读器把结构化 Markdown 渲染为浏览器 HTML，通过原生文本选区获得划词内容。模型不负责“让文字可选择”，只接收选区和上下文并生成回答。

数学公式统一使用项目本地打包的 KaTeX 渲染，支持行内 `$...$` 与独立 `$$...$$`，不依赖 CDN。Markdown 渲染前会规范化文档处理 Agent 常见的“列表项内缩进表格”，使其恢复为真正的 HTML 表格；公式源码会先被占位保护，因此表格公式中的 `|` 不会被误判为列分隔符。

上下文模式包括仅选区、附近段落、当前章节、文内 RAG 和整份资料。“当前章节”按最近标题到下一同级标题的真实边界截取，不再使用固定字符窗口。问答会保存选区、上下文快照和回答，便于复盘。

学习画布支持多个 AI 回答与思维导图节点。节点可以拖动、缩放、编辑和删除；原文区右边缘可以拖动调整宽度。划词“标记”会持久化到 `document_highlights`，重新打开资料后仍会显示。

## 12. 三层记忆

- Working Memory：当前页面、资料、最近输入输出，保存在 `session_state`。
- User Memory：解释风格、研究兴趣、饮食偏好等长期偏好。
- Knowledge Memory：资料 Markdown、chunks、论文和课程外部知识。

分层后，不同生命周期的数据可以分别检索和更新，比简单保存完整聊天记录更可控。

## 13. Dynamic Thought Tree

规划器调用当前模型生成三个不同候选方案，按可执行性、时间结构、优先级和复盘节点轻量评分，再输出最高分方案并保留候选结果。这是课程展示级动态思维树，不是复杂搜索算法。

## 14. 数据库表

- `users`、`user_model_configs`
- `library_folders`
- `documents`：原文件、原始文本、Markdown、处理状态、页数
- `document_chunks`
- `document_questions`、`document_mindmaps`
- `todos`、`todo_subtasks`
- `memory_items`
- `agent_runs`：领域 Agent 的目标、限制、计划、工具轨迹、结果和执行状态

旧版数据库会在 `init_db()` 时自动补充新列。

## 15. Demo 流程

1. 浏览公开首页，在右上角注册并登录。
2. 在“订阅”页面添加真实 API，并通过连接测试。
3. 进入“资料库”，创建文件夹并上传资料。
4. 等待提取/OCR/Markdown 整理完成。
5. 在原文中划选片段，选择解释、举例、解题或自由提问。
6. 切换上下文范围，比较回答差异。
7. 对论文使用论文研读工具，对任意资料生成思维导图。
8. 在 Todo 和美食模块体验其他学生场景。

## 16. 测试

```powershell
D:\miniconda3\envs\IntroML\python.exe scripts\smoke_test.py
D:\miniconda3\envs\IntroML\python.exe scripts\verify_model_fix.py
D:\miniconda3\envs\IntroML\python.exe -m compileall app.py src scripts
D:\miniconda3\envs\IntroML\python.exe -m unittest discover -s tests -v
```

FoodAgent 测试不会调用真实 API，覆盖三类意图路由、硬过滤、会话排除、周更新隔离、旧数据迁移和无 LLM 快捷筛选。真实模型连接请在“订阅”页面单独测试。

## 17. 后续扩展与 README 转 PDF

- OCR 任务队列、进度恢复和失败页面重试
- Markdown 人工校订与原 PDF 双栏对照
- Embedding + FAISS/Chroma
- 引用页码、图片与公式位置映射
- 南大课程公共资料、共享资料与勘误工作流
- 服务端 API 代理、额度扣减与真实支付

README 可用 Pandoc 导出：

```bash
pandoc README.md -o NJU-SZ-Agent-Hub-README.pdf
```

## 18. 课程项目说明

本项目是机器学习导论课程大项目原型，重点是展示 Agent、RAG、分层记忆、文档处理和统一模型接口的工程组合，不代表商业级产品。校外餐厅 JSON 仍是界面演示候选；校内食堂不使用预置假窗口，完全依赖带来源的联网检索。正式部署还需接入学校菜单或地图 API，并补充密钥加密、权限、隐私、并发任务、成本限制和内容审核。
