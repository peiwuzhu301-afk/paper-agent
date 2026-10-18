"""把 LaTeX 公式转换成 Word 原生公式（OMML）。

纯标准库实现，不依赖 pandoc / latex2mathml / lxml 等外部组件。
覆盖常见公式：分式、上下标、根号、求和/连乘/积分、常用希腊字母与运算符、
\\text / \\mathrm / \\mathbf / \\mathbb、重音与上划线等。
无法解析时回退为文本，保证不丢内容。
"""

from __future__ import annotations

import re
from html import escape

M_NS = 'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"'

SYMBOLS: dict[str, str] = {
    r"\alpha": "α", r"\beta": "β", r"\gamma": "γ", r"\delta": "δ", r"\epsilon": "ϵ",
    r"\varepsilon": "ε", r"\zeta": "ζ", r"\eta": "η", r"\theta": "θ", r"\vartheta": "ϑ",
    r"\iota": "ι", r"\kappa": "κ", r"\lambda": "λ", r"\mu": "μ", r"\nu": "ν", r"\xi": "ξ",
    r"\pi": "π", r"\rho": "ρ", r"\sigma": "σ", r"\tau": "τ", r"\upsilon": "υ", r"\phi": "ϕ",
    r"\varphi": "φ", r"\chi": "χ", r"\psi": "ψ", r"\omega": "ω",
    r"\Gamma": "Γ", r"\Delta": "Δ", r"\Theta": "Θ", r"\Lambda": "Λ", r"\Xi": "Ξ",
    r"\Pi": "Π", r"\Sigma": "Σ", r"\Upsilon": "Υ", r"\Phi": "Φ", r"\Psi": "Ψ", r"\Omega": "Ω",
    r"\times": "×", r"\cdot": "⋅", r"\pm": "±", r"\mp": "∓", r"\div": "÷", r"\ast": "∗",
    r"\star": "⋆", r"\circ": "∘", r"\bullet": "•", r"\oplus": "⊕", r"\otimes": "⊗",
    r"\le": "≤", r"\leq": "≤", r"\ge": "≥", r"\geq": "≥", r"\neq": "≠", r"\ne": "≠",
    r"\approx": "≈", r"\equiv": "≡", r"\sim": "∼", r"\propto": "∝", r"\ll": "≪", r"\gg": "≫",
    r"\in": "∈", r"\notin": "∉", r"\ni": "∋", r"\subset": "⊂", r"\subseteq": "⊆",
    r"\supset": "⊃", r"\supseteq": "⊇", r"\cup": "∪", r"\cap": "∩", r"\setminus": "∖",
    r"\emptyset": "∅", r"\varnothing": "∅", r"\forall": "∀", r"\exists": "∃", r"\nexists": "∄",
    r"\infty": "∞", r"\partial": "∂", r"\nabla": "∇", r"\perp": "⊥", r"\parallel": "∥",
    r"\to": "→", r"\rightarrow": "→", r"\leftarrow": "←", r"\Rightarrow": "⇒",
    r"\Leftarrow": "⇐", r"\leftrightarrow": "↔", r"\mapsto": "↦", r"\uparrow": "↑", r"\downarrow": "↓",
    r"\ldots": "…", r"\dots": "…", r"\cdots": "⋯", r"\vdots": "⋮", r"\ddots": "⋱",
    r"\langle": "⟨", r"\rangle": "⟩", r"\lceil": "⌈", r"\rceil": "⌉", r"\lfloor": "⌊", r"\rfloor": "⌋",
    r"\%": "%", r"\#": "#", r"\&": "&", r"\_": "_", r"\$": "$", r"\{": "{", r"\}": "}",
    r"\quad": "\u2003", r"\qquad": "\u2003\u2003",
}

NARY: dict[str, str] = {
    r"\sum": "∑", r"\prod": "∏", r"\coprod": "∐", r"\int": "∫", r"\oint": "∮",
    r"\iint": "∬", r"\iiint": "∭", r"\bigcup": "⋃", r"\bigcap": "⋂",
}
LIMLOC_UNDEROVER = {"∑", "∏", "∐", "⋃", "⋂"}

FUNCS = {
    "log", "ln", "lg", "exp", "sin", "cos", "tan", "cot", "sec", "csc", "arcsin", "arccos",
    "arctan", "sinh", "cosh", "tanh", "max", "min", "arg", "det", "dim", "ker", "deg",
    "gcd", "hom", "sup", "inf", "lim", "Pr", "mod", "bmod",
}

MATHBB = {"R": "ℝ", "N": "ℕ", "Z": "ℤ", "Q": "ℚ", "C": "ℂ", "E": "𝔼", "P": "ℙ", "F": "𝔽", "1": "𝟙"}

ACCENTS = {
    r"\hat": "̂", r"\widehat": "̂", r"\bar": "̄", r"\overline": "̄", r"\vec": "⃗",
    r"\dot": "̇", r"\ddot": "̈", r"\tilde": "̃", r"\widetilde": "̃", r"\breve": "̆",
    r"\check": "̌", r"\acute": "́", r"\grave": "̀",
}

_SPECIAL_LETTERS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
_TOKEN_RE = re.compile(r"\\[a-zA-Z]+|\\.|\s+|[{}^_]|[^\s{}^_\\]")


def _t(text: str) -> str:
    return escape(text, quote=False)


def _run(text: str, *, plain: bool = False, bold: bool = False) -> str:
    if not text:
        return ""
    if plain:
        rpr = "<m:rPr><m:nor/></m:rPr>"
    elif bold:
        rpr = '<m:rPr><m:sty m:val="b"/></m:rPr>'
    else:
        rpr = ""
    return f'<m:r>{rpr}<m:t xml:space="preserve">{_t(text)}</m:t></m:r>'


def _frac(num: str, den: str) -> str:
    return f"<m:f><m:num>{num}</m:num><m:den>{den}</m:den></m:f>"


def _s_sub(base: str, sub: str) -> str:
    return f"<m:sSub><m:e>{base}</m:e><m:sub>{sub}</m:sub></m:sSub>"


def _s_sup(base: str, sup: str) -> str:
    return f"<m:sSup><m:e>{base}</m:e><m:sup>{sup}</m:sup></m:sSup>"


def _s_subsup(base: str, sub: str, sup: str) -> str:
    return f"<m:sSubSup><m:e>{base}</m:e><m:sub>{sub}</m:sub><m:sup>{sup}</m:sup></m:sSubSup>"


def _rad(inner: str, degree: str = "") -> str:
    hide = '<m:radPr><m:degHide m:val="1"/></m:radPr>' if not degree else "<m:radPr/>"
    return f"<m:rad>{hide}<m:deg>{degree}</m:deg><m:e>{inner}</m:e></m:rad>"


def _nary(char: str, sub: str, sup: str) -> str:
    limloc = "undOvr" if char in LIMLOC_UNDEROVER else "subSup"
    sub_xml = f"<m:sub>{sub}</m:sub>" if sub else "<m:sub/>"
    sup_xml = f"<m:sup>{sup}</m:sup>" if sup else "<m:sup/>"
    return (
        "<m:nary><m:naryPr>"
        f'<m:chr m:val="{char}"/><m:limLoc m:val="{limloc}"/><m:supHide m:val="0"/><m:subHide m:val="0"/>'
        "</m:naryPr>"
        f"{sub_xml}{sup_xml}<m:e/>"
        "</m:nary>"
    )


def _acc(char: str, base: str) -> str:
    return f'<m:acc><m:accPr><m:chr m:val="{char}"/></m:accPr><m:e>{base}</m:e></m:acc>'


class _Parser:
    def __init__(self, tokens: list[str]) -> None:
        self.tokens = tokens
        self.index = 0

    def _peek(self) -> str | None:
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def _next(self) -> str | None:
        token = self._peek()
        self.index += 1
        return token

    def parse_sequence(self) -> str:
        parts: list[str] = []
        while True:
            token = self._peek()
            if token is None or token == "}":
                break
            parts.append(self._parse_scripts(self._parse_base()))
        return "".join(parts)

    def _parse_group_or_atom(self) -> str:
        if self._peek() == "{":
            self._next()
            inner = self.parse_sequence()
            if self._peek() == "}":
                self._next()
            return inner
        if self._peek() is None:
            return ""
        return self._parse_scripts(self._parse_base())

    def _parse_scripts(self, base: str) -> str:
        sub = ""
        sup = ""
        while self._peek() in ("_", "^"):
            op = self._next()
            arg = self._parse_group_or_atom()
            if op == "_":
                sub = arg
            else:
                sup = arg
        if sub and sup:
            return _s_subsup(base, sub, sup)
        if sub:
            return _s_sub(base, sub)
        if sup:
            return _s_sup(base, sup)
        return base

    def _parse_base(self) -> str:
        token = self._next()
        if token is None:
            return ""
        if token == "{":
            inner = self.parse_sequence()
            if self._peek() == "}":
                self._next()
            return inner
        if token in ("}", "^", "_"):
            return _run(token, plain=True)
        if token.startswith("\\"):
            return self._parse_command(token)
        return _run(token)

    def _parse_command(self, command: str) -> str:
        if command in (r"\left", r"\right", r"\big", r"\Big", r"\bigl", r"\bigr", r"\middle", r"\limits"):
            return ""
        if command in (r"\frac", r"\dfrac", r"\tfrac"):
            return _frac(self._parse_group_or_atom(), self._parse_group_or_atom())
        if command == r"\sqrt":
            degree = ""
            if self._peek() == "[":
                self._next()
                buf: list[str] = []
                while self._peek() is not None and self._peek() != "]":
                    buf.append(self._next() or "")
                if self._peek() == "]":
                    self._next()
                degree = _Parser([t for t in _TOKEN_RE.findall("".join(buf)) if t.strip()]).parse_sequence()
            return _rad(self._parse_group_or_atom(), degree)
        if command in NARY:
            char = NARY[command]
            sub = ""
            sup = ""
            while self._peek() in ("_", "^"):
                op = self._next()
                arg = self._parse_group_or_atom()
                if op == "_":
                    sub = arg
                else:
                    sup = arg
            return _nary(char, sub, sup)
        if command in ACCENTS:
            return _acc(ACCENTS[command], self._parse_group_or_atom())
        if command in (r"\textbf", r"\mathbf", r"\boldsymbol", r"\bm", r"\bf"):
            return _run(self._raw_group(), bold=True)
        if command in (r"\textit", r"\mathit", r"\it"):
            return _run(self._raw_group(), plain=False)
        if command in (r"\text", r"\mathrm", r"\operatorname", r"\textrm", r"\mbox"):
            return _run(self._raw_group(), plain=True)
        if command == r"\mathbb":
            return _run("".join(MATHBB.get(ch, ch) for ch in self._raw_group()), plain=True)
        if command == r"\mathcal":
            return _run(self._raw_group(), plain=True)
        name = command.lstrip("\\")
        if name in FUNCS:
            return _run(name, plain=True)
        if command in SYMBOLS:
            return _run(SYMBOLS[command], plain=True)
        if len(name) == 1:
            return _run(name)
        return _run(name, plain=True)

    def _raw_group(self) -> str:
        if self._peek() != "{":
            token = self._next()
            return token or ""
        self._next()
        depth = 1
        buf: list[str] = []
        while self._peek() is not None and depth > 0:
            token = self._next() or ""
            if token == "{":
                depth += 1
            elif token == "}":
                depth -= 1
                if depth == 0:
                    break
            buf.append(token)
        return "".join(buf)


def _tokens(latex: str) -> list[str]:
    return [token for token in _TOKEN_RE.findall(latex) if token.strip()]


def latex_to_omml(latex: str) -> str:
    """返回 <m:oMath>...</m:oMath>；解析失败时回退为文本。"""
    source = (latex or "").strip()
    if source.startswith("$$") and source.endswith("$$"):
        source = source[2:-2].strip()
    elif source.startswith(r"\[") and source.endswith(r"\]"):
        source = source[2:-2].strip()
    elif source.startswith(r"\(") and source.endswith(r"\)"):
        source = source[2:-2].strip()
    elif source.startswith("$") and source.endswith("$"):
        source = source[1:-1].strip()
    try:
        body = _Parser(_tokens(source)).parse_sequence()
        if not body:
            body = _run(source, plain=True)
        return f"<m:oMath>{body}</m:oMath>"
    except Exception:  # noqa: BLE001
        return f"<m:oMath>{_run(source, plain=True)}</m:oMath>"


def omml_inline(latex: str) -> str:
    return latex_to_omml(latex)


def omml_display(latex: str) -> str:
    return f"<m:oMathPara>{latex_to_omml(latex)}</m:oMathPara>"
