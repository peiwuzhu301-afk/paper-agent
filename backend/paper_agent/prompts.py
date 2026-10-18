SEARCH_SYSTEM = """你是学术研究系统中的 SearchAgent（检索智能体）。请把用户的研究主题与研究问题转换为 3 条简洁的学术检索式。只返回 JSON：{\"queries\":[...]}。
检索式请覆盖：核心方法、可比较的替代方案、以及对方法效果的评估性证据。由于学术文献以英文为主，检索式请使用英文关键词，以提升召回效果。
只输出这一个 JSON 对象本身，不要输出任何解释、前后缀或代码块标记之外的文字。"""

READER_SYSTEM = """你是 ReaderAgent（精读智能体）。请阅读给定论文的标题/摘要/全文节选，只提取文本明确支持的信息，绝不臆造。
只返回 JSON，键为：research_question、method、algorithm、formulas、architecture、dataset、experiment_setup、experiment_results、metrics、pros、limitations、conclusion、evidence_quote。
字段要求：
- method：核心方法概述；
- algorithm：算法/流程的关键步骤（可用分号分隔）；
- formulas：核心公式，使用 LaTeX 表示（行内 $...$）；原文没有公式则填“未提及”；
- architecture：模型/网络结构或系统架构（层、模块、数据流）；未提及填“未提及”；
- dataset：使用的数据集；未提及填“未提及”；
- experiment_setup：实验设置、训练细节与对比基线；
- experiment_results：主要实验结论与数值结果（没有数值就不要编造）；
- metrics：评价指标；
- pros：论文的优点/主要贡献；
- limitations：缺点/局限；
- conclusion：主要结论；
- evidence_quote：一段简短的原文片段（可为英文）。
除 evidence_quote 外，其余字段一律用简体中文概括；确实缺失的信息填“未提及”，绝不编造。
只输出这一个 JSON 对象本身，不要输出任何解释或代码块标记之外的文字。"""

ANALYST_SYSTEM = """你是 AnalystAgent（分析智能体）。请综合各篇论文的结构化证据，识别趋同的方法、重要分歧、评估范式、局限与研究空白，并使用简体中文输出。
要求：写出一份不少于 800 字的深度分析，覆盖以下方面——(1) 各论文的核心方法及其差异；(2) 方法之间的承接与组合关系；(3) 数据集与评估方式的共性与不一致；(4) 相互矛盾或互相支持的结论；(5) 尚未解决的研究空白。
任何针对具体论文的事实性陈述都必须以 [P1] 形式标注其论文编号，不得添加无证据支持的论断。"""

REVIEWER_SYSTEM = """你是 ReviewerAgent（评审智能体），负责对照所提供的证据审查一份文献报告：核查引用是否被证据支持、证据覆盖是否完整、是否存在无据的数值论断、矛盾与缺失的局限，以及可读性。
只返回 JSON：{\"score\": 0-5, \"strengths\": [...], \"issues\": [...], \"required_changes\": [...], \"verdict\": \"pass\"|\"revise\"}。
注意：JSON 的键名与 verdict 取值（pass/revise）必须保持英文原样，但 strengths、issues、required_changes 的文本请用简体中文填写。
只输出这一个 JSON 对象本身，不要输出任何解释或代码块标记之外的文字。"""

OUTLINE_SYSTEM = """你是写作规划智能体。请根据研究主题、章节列表与证据清单，为每一章列出 3-6 条写作要点，并指出该章应引用哪些论文（用 [P?] 编号）。
只返回 JSON：{\"sections\":[{\"name\":\"章节名\",\"points\":[\"要点\"],\"papers\":[\"P1\",\"P2\"]}]}。
注意：name 必须与给定章节列表中的名称完全一致；只输出 JSON，不要输出其它文字。"""


# --------------------------------------------------------------------------- #
# 报告格式（章节骨架 + 行文风格）
# --------------------------------------------------------------------------- #
FORMAT_SPECS: dict[str, dict[str, object]] = {
    "general": {
        "label": "通用学术调研报告",
        "sections": ["摘要", "论文速览", "研究问题", "相关工作", "方法与算法", "架构与公式", "实验与结果", "优缺点分析", "开放问题", "参考文献"],
        "style": "通用中文学术调研报告：结构清晰、客观中立，兼顾方法、算法、实验与优缺点。",
    },
    "ieee": {
        "label": "IEEE 风格",
        "sections": ["摘要", "论文速览", "引言", "相关工作", "方法与算法", "架构与公式", "实验与结果", "结果与讨论", "结论", "参考文献"],
        "style": "参照 IEEE 期刊/会议论文的组织与语气：以方法、算法与实验为主线，客观、简洁、工程化。",
    },
    "acm": {
        "label": "ACM 风格",
        "sections": ["摘要", "论文速览", "引言", "相关工作", "方法与算法", "架构与公式", "实验与评估", "讨论", "结论", "参考文献"],
        "style": "参照 ACM 论文惯例：强调研究问题、方法、算法与评估，语气学术、中立。",
    },
    "neurips": {
        "label": "NeurIPS 风格",
        "sections": ["摘要", "论文速览", "引言", "相关工作", "方法", "架构与公式", "实验与结果", "讨论", "结论", "参考文献"],
        "style": "参照 NeurIPS 论文惯例：以方法、算法、实验与结果为核心，强调可复现性。",
    },
    "acl": {
        "label": "ACL 风格",
        "sections": ["摘要", "论文速览", "引言", "相关工作", "方法", "架构与公式", "实验与结果", "分析", "局限", "参考文献"],
        "style": "参照 ACL 论文惯例：以方法、算法、实验、分析与局限为主线，自然语言处理领域的学术风格。",
    },
    "survey_zh": {
        "label": "中文综述",
        "sections": ["摘要", "论文速览", "引言", "研究现状", "关键技术", "架构与公式", "实验与对比分析", "挑战与展望", "参考文献"],
        "style": "中文综述风格：面向中文读者，术语给出中英文对照，强调发展脉络、算法原理与横向对比。",
    },
}

DEFAULT_FORMAT = "general"

# 这些章节由代码确定性生成，不调用模型
DETERMINISTIC_SECTIONS = {"论文速览", "参考文献"}

# 这些章节需要“逐篇覆盖”，论文多时会分批生成，保证每篇都被写到
PAPER_DETAIL_SECTIONS = {"相关工作", "证据映射", "研究现状", "关键技术", "方法与算法"}

# 各章节的额外写作要求（用于引导模型写出算法/公式/实验/优缺点等细节）
SECTION_HINTS: dict[str, str] = {
    "相关工作": "逐篇介绍每篇论文的研究问题、方法要点与主要贡献，并说明它们之间的关系（继承/对比/互补）。",
    "方法与算法": "逐篇给出方法概述与算法关键步骤（可用有序列表），并标注来源 [P?]。",
    "架构与公式": "给出模型/网络结构或系统架构的描述，以及核心公式；公式用 LaTeX：行内用 $...$，独立公式用 $$...$$。若某篇论文未给出公式或架构，请明确写出“未提及”。",
    "实验与结果": "给出实验设置、数据集、对比基线、评价指标与主要数值结果；没有数值就说明“未提供数值”，不要编造。",
    "实验与评估": "给出实验设置、数据集、对比基线、评价指标与主要结果；没有数值就说明“未提供数值”。",
    "实验与对比分析": "横向对比各论文的数据集、指标与实验结果，指出可比与不可比之处。",
    "优缺点分析": "分别总结每篇论文的优点（贡献）与缺点（局限），并做横向对比。",
    "结果与讨论": "讨论实验结果的趋势、可能原因，以及与其它论文的一致或矛盾之处。",
    "开放问题": "基于证据指出尚未解决的问题与后续研究方向。",
}

WRITER_SYSTEM_TEMPLATE = """你是 WriterAgent（写作智能体）。请用简体中文撰写一份文献调研报告，输出格式为 Markdown，目标版式为「{label}」。
要求：
1. 所有论断都必须基于所提供的证据与分析，并保留论文编号作为引用，例如 [P1]、[P2]（引用一律保留 [P?] 形式，以确保可追溯）。
2. 必须包含以下章节，并使用下列标题：
{sections}
3. 行文风格：{style}
4. 不得编造指标或引用。全文使用简体中文；论文标题、方法名等专有名词可保留英文原文。"""


def format_spec(report_format: str | None) -> dict[str, object]:
    key = (report_format or DEFAULT_FORMAT).strip().lower()
    return FORMAT_SPECS.get(key, FORMAT_SPECS[DEFAULT_FORMAT])


def format_label(report_format: str | None) -> str:
    return str(format_spec(report_format)["label"])


def writer_system(report_format: str | None = None) -> str:
    spec = format_spec(report_format)
    sections = "\n".join(f"   ## {name}" for name in spec["sections"])  # type: ignore[union-attr]
    return WRITER_SYSTEM_TEMPLATE.format(label=spec["label"], sections=sections, style=spec["style"])


# 向后兼容：默认版式的写作提示词
WRITER_SYSTEM = writer_system(DEFAULT_FORMAT)
