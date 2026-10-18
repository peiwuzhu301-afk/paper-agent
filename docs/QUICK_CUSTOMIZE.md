# Quick Customize

## 只改 5 分钟就能变成你的项目

1. `.env`
   - `PAPER_AGENT_LLM_MODE=autogen`
   - `PAPER_AGENT_SOURCE=arxiv`
   - 填模型 Key/Endpoint。
2. `frontend/src/App.vue`
   - 换默认 topic / research question。
3. `backend/paper_agent/prompts.py`
   - 改五个 Agent 的角色与输出约束。
4. `backend/paper_agent/sources.py`
   - 加你的论文来源。
5. `backend/paper_agent/rag.py`
   - 替换 demo hash embedding 为生产 embedding。

## 常见改造

### 改成“某一个研究方向的专用 Agent”

在 ReaderAgent prompt 中加入固定 schema，例如：模型架构、训练数据、损失函数、Benchmark、参数规模、推理成本、SOTA 结果。

### 改成“上传 PDF 后分析”

新增 `/api/files`，把上传 PDF 写入 `workspace/papers/`，用 `pypdf` 解析，然后直接进入 ReaderAgent，不经过 arXiv Search。

### 加 Semantic Scholar / OpenAlex

实现新的 `PaperSource.search()`，返回统一 `PaperRecord` 即可，后面的 Reader/RAG/Writer 无需改动。

### 加严格 Citation Verification

在 Reviewer 之后增加 `claim_verifier` 节点：抽取报告 claims → 对每个 claim query Chroma → 判断 support / weak / unsupported → unsupported 则回到 Writer。
