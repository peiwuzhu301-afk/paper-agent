from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from pathlib import Path

_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def find_browser() -> str | None:
    for path in _CANDIDATES:
        if Path(path).exists():
            return path
    return shutil.which("msedge") or shutil.which("chrome") or shutil.which("chromium")


def html_to_pdf(html: str) -> bytes:
    """用本机 Edge/Chrome 无头模式把 HTML 打印为 PDF。

    注意：无头浏览器会在父进程返回后才异步写出 PDF，因此这里轮询等待文件出现；
    并使用独立的 user-data-dir，避免复用已打开的浏览器实例（那样会忽略无头参数）。
    """
    browser = find_browser()
    if not browser:
        raise RuntimeError("未找到 Edge/Chrome，无法生成 PDF")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        temp_dir = Path(tmp)
        html_path = temp_dir / "report.html"
        pdf_path = temp_dir / "report.pdf"
        profile_dir = temp_dir / "profile"
        html_path.write_text(html, encoding="utf-8")
        url = html_path.as_uri()
        for headless in ("--headless=new", "--headless"):
            cmd = [
                browser,
                headless,
                "--disable-gpu",
                "--no-sandbox",
                f"--user-data-dir={profile_dir}",
                "--no-pdf-header-footer",
                "--virtual-time-budget=15000",
                f"--print-to-pdf={pdf_path}",
                url,
            ]
            try:
                subprocess.run(cmd, timeout=150, check=False, capture_output=True)
            except subprocess.TimeoutExpired:
                pass
            for _ in range(80):
                if pdf_path.exists() and pdf_path.stat().st_size > 0:
                    return pdf_path.read_bytes()
                time.sleep(0.5)
    raise RuntimeError("PDF 生成失败（无头浏览器未产出文件）")
