from paper_agent.html import markdown_to_html, markdown_to_html_body


def test_html_body_has_headings_table_and_math():
    markdown = "# 标题\n\n## 架构\n\n公式 $E=mc^2$。\n\n| A | B |\n|---|---|\n| 1 | 2 |\n"
    body = markdown_to_html_body(markdown)
    assert '<h1 id="h1">' in body
    assert 'data-tex="E=mc^2"' in body
    assert "<table>" in body


def test_html_document_is_self_contained():
    html = markdown_to_html("# 标题\n", "测试")
    assert html.startswith("<!doctype html>")
    assert "katex" in html.lower()
