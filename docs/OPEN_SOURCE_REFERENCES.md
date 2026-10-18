# Open-source references

本 Demo 只借鉴公开架构思想，不直接复制第三方源码。

- LangGraph — stateful multi-actor workflow, persistence, interrupt/resume  
  https://github.com/langchain-ai/langgraph
- Microsoft AutoGen — AgentChat and multi-agent applications  
  https://github.com/microsoft/autogen
- Chroma — open-source embedding/vector database  
  https://github.com/chroma-core/chroma
- PaperQA2 — agentic RAG for scientific literature  
  https://github.com/Future-House/paper-qa
- STORM / Co-STORM — knowledge curation and long-form report generation  
  https://github.com/stanford-oval/storm
- GPT Researcher — planner/research/report pipeline  
  https://github.com/assafelovic/gpt-researcher

## 本 Demo 对应关系

- PaperQA2：借鉴 scientific evidence / grounded retrieval 的产品方向。
- STORM：借鉴“先调研再结构化合成报告”和 human collaboration 的思路。
- GPT Researcher：借鉴 research planner 与 report synthesis 解耦。
- LangGraph：真正落地状态持久化与中断恢复。
- AutoGen：真正落地五种角色 Agent。
- Chroma：真正落地 Evidence RAG。
