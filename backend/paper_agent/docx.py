"""把 Markdown 报告转换成真正的 .docx（OOXML）。

只依赖标准库：用 ``zipfile`` 直接打包 WordprocessingML，避免引入 python-docx
等新依赖（在本机的网络环境下安装并不稳定）。
"""

from __future__ import annotations

import io
import re
import zipfile
from html import escape

from .omml import M_NS, omml_display, omml_inline

W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

_ASCII_FONT = "Calibri"
_EA_FONT = "Microsoft YaHei"
_MONO_FONT = "Consolas"

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    "</Types>"
)

_ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="word/document.xml"/>'
    "</Relationships>"
)

_INLINE_RE = re.compile(
    r"(\*\*[^*]+\*\*|`[^`]+`|\$[^$\n]+\$|\\\([^)]+\\\)|\*[^*\n]+\*|\[[^\]]+\]\(https?:[^)\s]+\))"
)


def _esc(text: str) -> str:
    return escape(text, quote=False)


def _run(
    text: str,
    *,
    bold: bool = False,
    italic: bool = False,
    code: bool = False,
    size: int | None = None,
    color: str | None = None,
) -> str:
    if code:
        fonts = (
            f'<w:rFonts w:ascii="{_MONO_FONT}" w:hAnsi="{_MONO_FONT}" w:eastAsia="{_EA_FONT}"/>'
        )
    else:
        fonts = f'<w:rFonts w:ascii="{_ASCII_FONT}" w:hAnsi="{_ASCII_FONT}" w:eastAsia="{_EA_FONT}"/>'
    props = [fonts]
    if bold:
        props.append("<w:b/>")
    if italic:
        props.append("<w:i/>")
    if code:
        props.append('<w:shd w:val="clear" w:fill="F1F4FA"/>')
    if size:
        props.append(f'<w:sz w:val="{size}"/>')
    if color:
        props.append(f'<w:color w:val="{color}"/>')
    return f'<w:r><w:rPr>{"".join(props)}</w:rPr><w:t xml:space="preserve">{_esc(text)}</w:t></w:r>'


def _runs(text: str) -> str:
    """解析行内 **粗体**、*斜体*、`代码` 与 [文字](链接)。"""
    out: list[str] = []
    for part in _INLINE_RE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            out.append(_run(part[2:-2], bold=True))
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            out.append(_run(part[1:-1], code=True))
        elif part.startswith("$") and part.endswith("$") and len(part) > 2:
            out.append(omml_inline(part))
        elif part.startswith("\\(") and part.endswith("\\)") and len(part) > 4:
            out.append(omml_inline(part))
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            out.append(_run(part[1:-1], italic=True))
        else:
            link = re.match(r"^\[([^\]]+)\]\((https?:[^)\s]+)\)$", part)
            if link:
                out.append(_run(f"{link.group(1)}（{link.group(2)}）"))
            else:
                out.append(_run(part))
    return "".join(out) if out else _run("")


def _p(
    runs: str,
    *,
    spacing_before: int = 0,
    spacing_after: int = 120,
    indent: int | None = None,
    hanging: int | None = None,
) -> str:
    props = [
        f'<w:spacing w:before="{spacing_before}" w:after="{spacing_after}" w:line="320" w:lineRule="auto"/>'
    ]
    if indent is not None:
        hang = f' w:hanging="{hanging}"' if hanging else ""
        props.append(f'<w:ind w:left="{indent}"{hang}/>')
    return f'<w:p><w:pPr>{"".join(props)}</w:pPr>{runs}</w:p>'


def _heading(text: str, level: int) -> str:
    sizes = {1: 36, 2: 30, 3: 26, 4: 24, 5: 22, 6: 22}
    colors = {1: "1F2937", 2: "4F46E5", 3: "334155"}
    runs = _run(text, bold=True, size=sizes.get(level, 22), color=colors.get(level, "334155"))
    return _p(runs, spacing_before=280 if level <= 2 else 180, spacing_after=120)


def _bullet(text: str, marker: str) -> str:
    return _p(_run(f"{marker} ") + _runs(text), indent=420, hanging=240, spacing_after=60)


def _quote(text: str) -> str:
    runs = _run(text, italic=True, color="475569")
    return _p(runs, indent=360, spacing_after=120)


def _code_block(lines: list[str]) -> str:
    return "".join(_p(_run(line or " ", code=True), spacing_after=0) for line in lines) or _p(_run(""))


def _hr() -> str:
    return (
        "<w:p><w:pPr>"
        '<w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" w:color="D3DBE9"/></w:pBdr>'
        '<w:spacing w:before="120" w:after="120"/>'
        "</w:pPr></w:p>"
    )


def _tc(text: str, *, header: bool, width: int) -> str:
    runs = _run(text, bold=header)
    shd = '<w:shd w:val="clear" w:fill="EEF0FF"/>' if header else ""
    return (
        "<w:tc><w:tcPr>"
        f'<w:tcW w:w="{width}" w:type="dxa"/>{shd}<w:vAlign w:val="center"/>'
        "</w:tcPr>"
        + _p(runs, spacing_after=20)
        + "</w:tc>"
    )


def _table(rows: list[list[str]], header_rows: int = 1) -> str:
    columns = max(len(row) for row in rows)
    width = max(1200, 9000 // max(1, columns))
    borders = (
        "<w:tblBorders>"
        '<w:top w:val="single" w:sz="4" w:space="0" w:color="D3DBE9"/>'
        '<w:left w:val="single" w:sz="4" w:space="0" w:color="D3DBE9"/>'
        '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="D3DBE9"/>'
        '<w:right w:val="single" w:sz="4" w:space="0" w:color="D3DBE9"/>'
        '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="D3DBE9"/>'
        '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="D3DBE9"/>'
        "</w:tblBorders>"
    )
    grid = "".join(f'<w:gridCol w:w="{width}"/>' for _ in range(columns))
    body = []
    for index, row in enumerate(rows):
        cells = "".join(
            _tc(row[col] if col < len(row) else "", header=index < header_rows, width=width)
            for col in range(columns)
        )
        body.append(f"<w:tr>{cells}</w:tr>")
    return (
        "<w:tbl><w:tblPr>"
        '<w:tblW w:w="0" w:type="auto"/><w:tblLayout w:type="autofit"/>'
        + borders
        + "</w:tblPr>"
        f"<w:tblGrid>{grid}</w:tblGrid>"
        + "".join(body)
        + "</w:tbl>"
        + _p(_run(""), spacing_after=80)
    )


def _split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


_SEPARATOR_RE = re.compile(r"^\|?[\s:|-]+\|?$")


def markdown_to_docx(markdown: str, title: str = "") -> bytes:
    lines = (markdown or "").replace("\r\n", "\n").split("\n")
    body: list[str] = []
    in_code = False
    code_buf: list[str] = []
    index = 0

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if stripped.startswith("```"):
            if in_code:
                body.append(_code_block(code_buf))
                code_buf = []
                in_code = False
            else:
                in_code = True
            index += 1
            continue
        if in_code:
            code_buf.append(line)
            index += 1
            continue

        if not stripped:
            index += 1
            continue

        # 表格
        if (
            stripped.startswith("|")
            and index + 1 < len(lines)
            and _SEPARATOR_RE.match(lines[index + 1].strip())
            and "-" in lines[index + 1]
        ):
            rows = [_split_row(stripped)]
            index += 2
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append(_split_row(lines[index].strip()))
                index += 1
            body.append(_table(rows))
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            body.append(_heading(heading.group(2).strip(), len(heading.group(1))))
            index += 1
            continue

        block_math = re.match(r"^\$\$(.+)\$\$$", stripped) or re.match(r"^\\\[(.+)\\\]$", stripped)
        if block_math:
            body.append(omml_display(block_math.group(1).strip()))
            index += 1
            continue

        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            body.append(_hr())
            index += 1
            continue

        if stripped.startswith(">"):
            body.append(_quote(stripped.lstrip(">").strip()))
            index += 1
            continue

        bullet = re.match(r"^[-*+]\s+(.*)$", stripped)
        if bullet:
            body.append(_bullet(bullet.group(1), "•"))
            index += 1
            continue

        ordered = re.match(r"^(\d+)[.)]\s+(.*)$", stripped)
        if ordered:
            body.append(_bullet(ordered.group(2), f"{ordered.group(1)}."))
            index += 1
            continue

        body.append(_p(_runs(stripped), spacing_after=120))
        index += 1

    if in_code and code_buf:
        body.append(_code_block(code_buf))

    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f"<w:document {W_NS} {M_NS}><w:body>"
        + "".join(body)
        + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>'
        "</w:body></w:document>"
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _ROOT_RELS)
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()
