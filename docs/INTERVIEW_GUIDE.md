# Paper-Agent 面试讲解速记

## 60 秒项目介绍

Paper-Agent 是一个面向论文调研的可恢复多 Agent 工作流。用户给出研究主题后，LangGraph 负责维护完整任务状态并依次调度 Search、Reader、Analyst、Writer、Reviewer 五类角色；角色推理由 AutoGen AgentChat 承担。Reader 会把论文中的研究问题、方法、数据集、指标、结论和局限抽成结构化 Evidence，再写入 ChromaDB。Analyst 只读取与当前问题最相关的 Top-K Evidence，而不是把所有论文全文塞进上下文。Writer 生成带论文 ID 引用的 Markdown 报告，Reviewer 检查 citation coverage、unsupported claims 和结构完整性。需要人工审核时，LangGraph interrupt 真正暂停流程，用户可以 approve、revise 或 reject；revise 会回到 Writer 节点重新生成并再次审查。FastAPI + SSE 把节点级状态实时推到 Vue3 前端，因此整个长链路是可观测、可中断、可恢复的。

## 高频追问

### 为什么 LangGraph 和 AutoGen 同时用？

LangGraph 管 durable workflow/state，AutoGen 管 role-level agent reasoning。把二者职责分开后，Checkpoint、HITL、重试和流程边界不用依赖 Prompt，自定义 Agent 也更容易替换。

### 为什么要 ChromaDB？

论文调研不是一次性上下文问题。结构化 Evidence 可以跨节点复用，Top-K retrieval 让 Analyst/Writer 只拿当前问题最相关的信息，也为 citation verification 和增量知识库留下接口。

### 为什么不直接让一个 Agent 读完全部论文？

单 Agent 同时负责检索、阅读、比较、写作、审查容易造成上下文膨胀、错误难定位、任务失败后只能全链路重跑。拆分角色后每个阶段有明确输入输出 schema，状态和错误边界也更清晰。

### 怎么做失败恢复？

外部搜索/PDF 下载有 retry + backoff；工作流状态通过 LangGraph SQLite Checkpoint 持久化；HITL 使用 interrupt/resume；Writer revision 是显式图循环，不是把“请重新写”塞回一段长对话。

### 简历里的 Top-5 Hit Rate 怎么测？

准备人工标注 query → relevant paper/evidence 的 benchmark；对每个 query 执行 Top-K retrieval，统计 Hit@5 / Recall@5。不要用 Reviewer 主观分数替代检索指标。

### 结构化解析成功率怎么测？

定义 schema 完整性 + 字段可验证性，例如 method/dataset/metrics/conclusion 是否成功解析且能回指原文。成功率应在固定测试集上统计，不能只看 JSON 是否能 parse。
