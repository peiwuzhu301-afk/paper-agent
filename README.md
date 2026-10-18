# Paper-Agent — 智能调研与报告生成系统（Complete Demo）

这是一个按“**搜索 → 阅读 → 分析 → 写作 → 审查 → 人工确认**”构建的完整论文调研 Demo，重点展示：

- **LangGraph**：状态机、Checkpoint、Interrupt/Resume、可恢复工作流
- **AutoGen AgentChat**：Search / Reader / Analyst / Writer / Reviewer 五类 Agent
- **RAG + ChromaDB**：结构化论文 Evidence 持久化与 Top-K 检索
- **FastAPI + SSE**：任务 API、实时节点 Trace、人工审核接口
- **Vue 3**：启动任务、查看执行轨迹、审核报告、查看最终 Markdown
- **零 Key Demo**：默认 `mock + sample`，无需模型 API、无需联网即可演示核心流程（安装依赖本身仍需要联网）
- **真实模式**：切换 `autogen + arxiv` 后使用真实论文搜索与 LLM Agent

> 这个仓库的目标是：你改 `.env`、研究主题和少量 Prompt，就能直接变成自己的项目 Demo。它不会伪造简历中的 82% Top-5 命中率、90% 解析率或 4.1/5 人工评分；仓库提供了评测入口，让你用自己的真实实验数据重新测。

---

## 1. 30 秒快速运行

### Windows PowerShell

```powershell
.\scripts\setup.ps1
& .\.venv\Scripts\Activate.ps1
paper-agent demo
```

### macOS / Linux

```bash
bash scripts/setup.sh
source .venv/bin/activate
paper-agent demo
```

默认 Demo 会：

1. 从 `data/sample_papers.json` 同类的内置论文数据中搜索；
2. ReaderAgent 结构化抽取 `research question / method / dataset / metrics / conclusion / limitation`；
3. 写入 ChromaDB；
4. Top-K RAG 检索；
5. AnalystAgent 综合；
6. WriterAgent 输出 Markdown；
7. ReviewerAgent 做确定性审查；
8. 保存到 `workspace/reports/`。

---

## 2. 启动 Web Demo

终端 1：

```bash
source .venv/bin/activate     # Windows: .\.venv\Scripts\Activate.ps1
paper-agent serve
```

终端 2：

```bash
cd frontend
npm run dev
```

浏览器打开：

```text
http://127.0.0.1:5173
```

UI 能看到实时 SSE Trace，并在 `require_human_review=true` 时暂停到 Human-in-the-Loop 节点，让你选择：

- Approve：生成最终报告
- Revise：把人工意见送回 WriterAgent，重新写作 + 再审查
- Reject：结束任务

---

## 3. 切换到真实论文 + AutoGen

复制环境变量：

```bash
cp .env.example .env
```

修改：

```env
PAPER_AGENT_LLM_MODE=autogen
PAPER_AGENT_SOURCE=arxiv
OPENAI_API_KEY=你的key
OPENAI_MODEL=gpt-4.1-mini
```

然后：

```bash
paper-agent run \
  --topic "Agentic RAG for scientific literature review" \
  --question "How do iterative retrieval and verifier loops improve grounded report generation?" \
  --source arxiv \
  --max-papers 6 \
  --human-review
```

如果你使用 vLLM / LM Studio / 其他 OpenAI-compatible Endpoint：

```env
OPENAI_BASE_URL=http://127.0.0.1:8001/v1
OPENAI_API_KEY=placeholder
OPENAI_MODEL=your-model-name
MODEL_SUPPORTS_FUNCTION_CALLING=true
MODEL_SUPPORTS_JSON=true
MODEL_SUPPORTS_STRUCTURED_OUTPUT=true
```

---

## 4. 项目架构

```text
User / Vue3
    │
    ├──────────── SSE Trace ─────────────┐
    │                                    │
    ▼                                    │
FastAPI Task API                         │
    │                                    │
    ▼                                    │
LangGraph StateGraph + SQLite Checkpoint │
    │                                    │
    ├─ SearchAgent  ── arXiv/sample      │
    ├─ ReaderAgent  ── structured paper evidence
    │        │
    │        └────────► ChromaDB Evidence Store
    │                         │
    ├─ AnalystAgent ◄─────────┘ Top-K RAG
    ├─ WriterAgent
    ├─ ReviewerAgent
    └─ Human Gate ── interrupt / resume / revise
             │
             ▼
      workspace/reports/*.md
```

LangGraph 负责“**流程与状态**”，AutoGen 负责“**Agent 角色推理**”，ChromaDB 负责“**Evidence Retrieval**”。这三个职责刻意分开，方便面试时解释，也方便后续替换框架。

---

## 5. 目录结构

```text
Paper_Agent_Complete_Demo/
├── backend/paper_agent/
│   ├── api.py              # FastAPI + SSE
│   ├── cli.py              # paper-agent 命令行
│   ├── graph.py            # LangGraph 主工作流 / HITL / Checkpoint
│   ├── llm.py              # 5 类 AutoGen Agent + zero-key mock
│   ├── sources.py          # sample / arXiv
│   ├── rag.py              # ChromaDB Evidence Store
│   ├── schemas.py          # State / API / Evidence schema
│   ├── eval.py             # deterministic report metrics
│   └── ...
├── frontend/               # Vue 3 + Vite
├── config/settings.yaml
├── data/
├── tests/
├── docs/
├── scripts/
└── workspace/
    ├── checkpoints/        # LangGraph SQLite
    ├── chroma/             # Chroma persistent data
    ├── reports/            # final Markdown
    ├── runs/               # run snapshots
    └── papers/
```

---

## 6. 最常改的 4 个地方

### A. 改研究业务

前端默认主题：`frontend/src/App.vue`

CLI：直接传 `--topic` / `--question`。

### B. 改 Agent 行为

`backend/paper_agent/prompts.py`

你可以重点改：

- `SEARCH_SYSTEM`
- `READER_SYSTEM`
- `ANALYST_SYSTEM`
- `WRITER_SYSTEM`
- `REVIEWER_SYSTEM`

### C. 改论文来源

`backend/paper_agent/sources.py`

目前有：

- `SamplePaperSource`
- `ArxivPaperSource`

你可以按同一个 `PaperSource` 接口加入 Semantic Scholar、OpenAlex、Crossref、企业内部论文库等。

### D. 改向量模型

`backend/paper_agent/rag.py`

为了做到“拿到即跑”，Demo 使用本地 deterministic feature-hashing embedding，不会偷偷下载 embedding 模型。生产化时建议换成你自己的 embedding 服务或模型。

---

## 7. 状态持久化、失败恢复、人机协同

每个任务都用 `task_id` 作为 LangGraph `thread_id`，状态落到：

```text
workspace/checkpoints/langgraph.sqlite
```

Human Gate 使用 `interrupt()`；恢复时使用同一个 `thread_id` 和 `Command(resume=...)`。因此“暂停 → 人工审核 → 继续”不是前端假暂停，而是工作流本身真的停止和恢复。

同时 Search / Reader 的外部访问使用 retry/backoff；执行轨迹通过 SSE 推到 Vue 页面。

---

## 8. RAG 数据结构

每篇论文抽取：

```json
{
  "paper_id": "P1",
  "title": "...",
  "research_question": "...",
  "method": "...",
  "dataset": "...",
  "metrics": "...",
  "conclusion": "...",
  "limitations": "...",
  "evidence_quote": "...",
  "url": "..."
}
```

然后作为 Evidence 写入 ChromaDB。AnalystAgent 不直接读取所有长文本，而是围绕当前研究问题做 Top-K retrieval 后再综合。

---

## 9. Evaluation

完成一个任务后：

```bash
paper-agent eval <task_id>
```

会输出：

- `structured_parse_rate`
- `citation_coverage`
- `section_coverage`
- `reviewer_score`
- `report_chars`

这些只是 Demo 的确定性工程指标。若你要在简历上写 Top-5 Hit Rate / 人工综合评分 / 端到端时延，请使用真实标注集和真实人工评分重新跑实验。

---

## 10. Open-source 设计参考

这个 Demo 没有直接复制第三方项目源码，而是参考了这些开源系统的公开设计思想：

- LangGraph：stateful graph、checkpoint、interrupt/resume
- Microsoft AutoGen：AgentChat / role agents
- Chroma：persistent vector collection / query
- FutureHouse PaperQA2：scientific agentic RAG、evidence-grounded answers
- Stanford STORM / Co-STORM：research → knowledge curation → long-form report + human collaboration
- GPT Researcher：planner/researcher/report synthesis pipeline

完整链接见 `docs/OPEN_SOURCE_REFERENCES.md`。

---

## 11. 常见问题

**Q：不配 API Key 能跑吗？**  
能。默认 `mock + sample`，就是为现场 Demo 和代码讲解准备的。

**Q：这样算真的用了 AutoGen 吗？**  
真实模式 `PAPER_AGENT_LLM_MODE=autogen` 会创建 AutoGen `AssistantAgent` 执行五种角色；默认 mock 只是为了让项目在没有模型 Key 的情况下也能完整跑通工作流。

**Q：为什么不用 AutoGen 自己编排全部流程？**  
这里刻意用 LangGraph 做 outer orchestration，AutoGen 做 role-level intelligence。这样 checkpoint/HITL/流程边界更清晰，也更贴近简历里“LangGraph + AutoGen 编排”的叙述。

**Q：为什么默认不下载论文 PDF？**  
现场 Demo 要稳定。设置 `ARXIV_DOWNLOAD_PDFS=true` 后 ReaderAgent 会尝试下载 PDF 并用 `pypdf` 读取部分全文；失败会降级为 abstract。

---

## 12. 面试现场 3 分钟 Demo

```bash
paper-agent doctor
paper-agent demo
```

然后打开：

1. `backend/paper_agent/graph.py`：解释 LangGraph state + Human Gate；
2. `backend/paper_agent/llm.py`：解释 AutoGen 五类 Agent；
3. `backend/paper_agent/rag.py`：解释 Chroma Evidence Store；
4. `workspace/reports/*.md`：展示最终报告；
5. Web UI：现场做一次 `revise`，展示 interrupt/resume。

这样你讲的重点不是“我调了五次 LLM”，而是：**长链路 Agent Workflow 如何做到状态可追踪、失败可恢复、证据可检索、人工可介入。**

## 13. Tiny retrieval sanity benchmark

为了让你能直接展示“检索评测怎么做”，项目带了一个很小的示例标注集：

```bash
paper-agent benchmark --top-k 5
```

它会计算 Hit@K，但这只是验证评测代码链路的小样本，**不要把这个数字直接写进简历**。真正的 82% 等指标必须来自你自己构建的足量人工标注测试集。
