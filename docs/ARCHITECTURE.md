# Architecture

## Responsibility split

| Layer | Implementation | Responsibility |
|---|---|---|
| UI | Vue 3 | Task form, trace, HITL decisions, report display |
| API | FastAPI | Task lifecycle, state query, SSE, resume |
| Orchestration | LangGraph | State transitions, checkpoint, interrupt/resume, revision loop |
| Role intelligence | AutoGen AgentChat | Search, Read, Analyze, Write, Review reasoning |
| Retrieval | ChromaDB | Persistent evidence index and Top-K query |
| Paper source | sample / arXiv | Candidate discovery and optional PDF text |
| Artifacts | SQLite / JSON / Markdown | Durable state, run snapshots, final reports |

## Graph

```text
START
  │
  ▼
SearchAgent
  │
  ▼
ReaderAgent ──► ChromaDB
  │               │
  ▼               │
AnalystAgent ◄────┘
  │
  ▼
WriterAgent
  │
  ▼
ReviewerAgent
  │
  ▼
Human Gate ── approve ─► Finalize ─► END
    │
    ├─ revise ─────────► WriterAgent
    └─ reject ─────────► Rejected ─► END
```

## Why LangGraph + AutoGen together?

LangGraph is used as the durable process/state layer. AutoGen is used as a role-level agent runtime. This avoids delegating persistence and HITL semantics to prompt text and makes the workflow observable and resumable.

## State boundaries

The graph stores compact structured state rather than raw PDF history. Full paper text is transient during reading; evidence is converted into structured records and persisted to ChromaDB. This limits long-context growth and makes downstream report generation reproducible.
