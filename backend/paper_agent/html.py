"""Markdown -> 自包含 HTML（用于网页导出与 PDF 生成）。

公式通过内联的 KaTeX 渲染：优先内联 frontend/node_modules/katex 里的 CSS/JS/字体，
保证离线也能正确显示；找不到时回退到 CDN。
"""

from __future__ import annotations

import base64
import re
from html import escape
from pathlib import Path

KATEX_DIST = Path(__file__).resolve().parents[2] / "frontend" / "node_modules" / "katex" / "dist"

_INLINE_RE = re.compile(
    r"(\*\*[^*]+\*\*|`[^`]+`|\$[^$\n]+\$|\\\([^)]+\\\)|\*[^*\n]+\*|\[[^\]]+\]\(https?:[^)\s]+\))"
)
_MATH_RE = re.compile(r"(\$\$[^$]+\$\$|\$[^$\n]+\$|\\\[[^\]]+\\\]|\\\([^)]+\\\))")


def _esc(text: str) -> str:
    return escape(text, quote=False)


def _attr(text: str) -> str:
    return escape(text, quote=True)


def _split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _inline(text: str) -> str:
    store: list[str] = []

    def stash(match: re.Match[str]) -> str:
        store.append(match.group(0))
        return f"\u0000M{len(store) - 1}\u0000"

    protected = _MATH_RE.sub(stash, text)
    out = _esc(protected)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(^|[^*])\*([^*\n]+)\*", r"\1<em>\2</em>", out)
    out = re.sub(
        r"\[([^\]]+)\]\((https?:[^)\s]+)\)",
        r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>',
        out,
    )
    out = re.sub(r"\[(P\d+)\]", r'<span class="cite">[\1]</span>', out)

    def restore(match: re.Match[str]) -> str:
        raw = store[int(match.group(1))]
        display = False
        latex = raw
        if raw.startswith("$$") and raw.endswith("$$"):
            display, latex = True, raw[2:-2]
        elif raw.startswith(r"\[") and raw.endswith(r"\]"):
            display, latex = True, raw[2:-2]
        elif raw.startswith(r"\(") and raw.endswith(r"\)"):
            latex = raw[2:-2]
        elif raw.startswith("$") and raw.endswith("$"):
            latex = raw[1:-1]
        css = "math-block" if display else "math-tex"
        return f'<span class="{css}" data-tex="{_attr(latex.strip())}"></span>'

    return re.sub(r"\u0000M(\d+)\u0000", restore, out)


def markdown_to_html_body(markdown: str) -> str:
    lines = (markdown or "").replace("\r\n", "\n").split("\n")
    out: list[str] = []
    index = 0
    heading_seq = 0
    in_code = False
    code_buf: list[str] = []
    list_type: str | None = None

    def close_list() -> None:
        nonlocal list_type
        if list_type:
            out.append(f"</{list_type}>")
            list_type = None

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if stripped.startswith("```"):
            if in_code:
                out.append(f"<pre><code>{_esc(chr(10).join(code_buf))}</code></pre>")
                code_buf = []
                in_code = False
            else:
                in_code = True
                close_list()
            index += 1
            continue
        if in_code:
            code_buf.append(line)
            index += 1
            continue
        if not stripped:
            close_list()
            index += 1
            continue

        if stripped.startswith("|") and index + 1 < len(lines) and re.match(
            r"^\|?[\s:|-]+\|?$", lines[index + 1].strip()
        ):
            close_list()
            header = _split_row(stripped)
            rows = []
            index += 2
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append(_split_row(lines[index].strip()))
                index += 1
            html = "<table><thead><tr>" + "".join(f"<th>{_inline(c)}</th>" for c in header) + "</tr></thead><tbody>"
            html += "".join(
                "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row) + "</tr>" for row in rows
            )
            html += "</tbody></table>"
            out.append(html)
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            close_list()
            level = len(heading.group(1))
            heading_seq += 1
            out.append(f'<h{level} id="h{heading_seq}">{_inline(heading.group(2))}</h{level}>')
            index += 1
            continue

        block_math = re.match(r"^\$\$(.+)\$\$$", stripped) or re.match(r"^\\\[(.+)\\\]$", stripped)
        if block_math:
            close_list()
            out.append(f'<div class="math-block" data-tex="{_attr(block_math.group(1).strip())}"></div>')
            index += 1
            continue

        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            close_list()
            out.append("<hr/>")
            index += 1
            continue

        if stripped.startswith(">"):
            close_list()
            out.append(f"<blockquote>{_inline(stripped.lstrip('>').strip())}</blockquote>")
            index += 1
            continue

        bullet = re.match(r"^[-*+]\s+(.*)$", stripped)
        if bullet:
            if list_type != "ul":
                close_list()
                out.append("<ul>")
                list_type = "ul"
            out.append(f"<li>{_inline(bullet.group(1))}</li>")
            index += 1
            continue

        ordered = re.match(r"^\d+[.)]\s+(.*)$", stripped)
        if ordered:
            if list_type != "ol":
                close_list()
                out.append("<ol>")
                list_type = "ol"
            out.append(f"<li>{_inline(ordered.group(1))}</li>")
            index += 1
            continue

        close_list()
        out.append(f"<p>{_inline(stripped)}</p>")
        index += 1

    if in_code and code_buf:
        out.append(f"<pre><code>{_esc(chr(10).join(code_buf))}</code></pre>")
    close_list()
    return "\n".join(out)


_CSS = """
:root{--brand:#4f46e5}
*{box-sizing:border-box}
body{font-family:"Microsoft YaHei","PingFang SC",Calibri,system-ui,sans-serif;line-height:1.75;
 color:#1f2937;max-width:900px;margin:0 auto;padding:48px 28px 80px;background:#fff}
h1{font-size:28px;border-bottom:2px solid #e5eaf3;padding-bottom:12px}
h2{font-size:21px;color:var(--brand);margin-top:32px}
h3{font-size:17px;margin-top:22px}
table{border-collapse:collapse;width:100%;margin:16px 0;font-size:13.5px}
th,td{border:1px solid #d3dbe9;padding:8px 10px;text-align:left;vertical-align:top}
th{background:#eef0ff;color:#3730a3}
tr:nth-child(even) td{background:#fafbff}
code{background:#f1f4fa;border-radius:6px;padding:1.5px 6px;font-family:Consolas,monospace;font-size:13px}
pre{background:#0f172a;color:#e2e8f0;border-radius:12px;padding:16px 18px;overflow:auto}
pre code{background:transparent;color:inherit;padding:0}
blockquote{margin:12px 0;padding:8px 16px;border-left:4px solid var(--brand);background:#f7f8ff;color:#475569}
a{color:var(--brand);text-decoration:none}
.cite{display:inline-block;background:#eef0ff;color:var(--brand);border-radius:6px;padding:0 6px;
 font-size:12px;font-weight:700;margin:0 1px}
.math-block{display:block;text-align:center;margin:16px 0}
@media print{body{padding:0;max-width:none}}
"""


def _katex_assets() -> tuple[str, str]:
    css_path = KATEX_DIST / "katex.min.css"
    js_path = KATEX_DIST / "katex.min.js"
    if not css_path.exists() or not js_path.exists():
        return "", ""
    css = css_path.read_text(encoding="utf-8")

    def to_data_uri(match: re.Match[str]) -> str:
        raw = match.group(1).strip().strip("'\"")
        name = raw.split("/")[-1]
        font_path = KATEX_DIST / "fonts" / name
        if not font_path.exists():
            return match.group(0)
        mime = "font/woff2" if name.endswith(".woff2") else "font/woff"
        payload = base64.b64encode(font_path.read_bytes()).decode("ascii")
        return f"url(data:{mime};base64,{payload})"

    css = re.sub(r"url\(([^)]+)\)", to_data_uri, css)
    js = js_path.read_text(encoding="utf-8")
    return css, js


def markdown_to_html(markdown: str, title: str = "") -> str:
    body = markdown_to_html_body(markdown)
    css, js = _katex_assets()
    if css and js:
        head_assets = f"<style>{css}</style>\n<style>{_CSS}</style>"
        math_script = (
            "<script>document.addEventListener('DOMContentLoaded',function(){"
            "document.querySelectorAll('[data-tex]').forEach(function(el){"
            "var t=el.getAttribute('data-tex')||'';"
            "try{katex.render(t,el,{throwOnError:false,displayMode:el.classList.contains('math-block')});}"
            "catch(e){el.textContent=t;}});});</script>"
        )
        # 先加载 KaTeX，再执行渲染脚本
        scripts = f"<script>{js}</script>\n{math_script}"
    else:
        head_assets = (
            '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">'
            f"<style>{_CSS}</style>"
        )
        scripts = (
            '<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>'
            '<script>document.addEventListener("DOMContentLoaded",function(){'
            'function r(){document.querySelectorAll("[data-tex]").forEach(function(el){'
            'var t=el.getAttribute("data-tex")||"";try{katex.render(t,el,{throwOnError:false,'
            'displayMode:el.classList.contains("math-block")});}catch(e){el.textContent=t;}});}'
            'if(window.katex){r();}else{window.addEventListener("load",r);}});</script>'
        )
    safe_title = escape(title or "Paper-Agent 报告")
    return (
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><title>{safe_title}</title>"
        f"{head_assets}</head><body>{body}{scripts}</body></html>"
    )
