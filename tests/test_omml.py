import io
import xml.etree.ElementTree as ET
import zipfile

from paper_agent.docx import markdown_to_docx
from paper_agent.omml import latex_to_omml

M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"


def _wrap(fragment: str) -> str:
    return f'<root xmlns:m="{M_NS}">{fragment}</root>'


def test_omml_covers_common_structures():
    cases = {
        r"E = mc^2": "<m:sSup>",
        r"\frac{a}{b}": "<m:f>",
        r"\sqrt{x}": "<m:rad>",
        r"\sum_{i=1}^{n} x_i": "<m:nary>",
        r"\int_0^\infty e^{-x}": "<m:nary>",
        r"\alpha + \beta": "α",
        r"\mathbb{R}": "ℝ",
        r"x \leq y": "≤",
        r"\hat{y}": "<m:acc>",
    }
    for latex, marker in cases.items():
        fragment = latex_to_omml(latex)
        assert marker in fragment, f"{latex} -> {fragment}"
        ET.fromstring(_wrap(fragment))  # 必须是合法 XML


def test_docx_contains_native_math():
    markdown = "## 架构与公式\n\n注意力为 $\\mathrm{softmax}(QK^T/\\sqrt{d})V$。\n\n$$L = -\\frac{1}{N}\\sum_{i=1}^{N} y_i \\log \\hat{y}_i$$\n"
    data = markdown_to_docx(markdown, "测试")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        document = archive.read("word/document.xml")
    ET.fromstring(document)  # 含命名空间，必须合法
    assert b"<m:oMath>" in document
    assert b"<m:oMathPara>" in document
    assert b"<m:f>" in document  # 分式
    assert b"<m:nary>" in document  # 求和
