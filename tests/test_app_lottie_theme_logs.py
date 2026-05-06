"""Web UI Lottie 主题切换路径不应保留调试日志。"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_JS = REPO_ROOT / "static" / "js" / "app.js"


def _extract_function_body(source: str, function_name: str) -> str:
    marker = f"function {function_name}("
    start = source.find(marker)
    assert start >= 0, f"找不到 {function_name} 函数"
    brace_start = source.find("{", start)
    assert brace_start >= 0, f"找不到 {function_name} 函数体起点"

    depth = 0
    for idx in range(brace_start, len(source)):
        char = source[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[brace_start + 1 : idx]
    raise AssertionError(f"找不到 {function_name} 函数体终点")


def test_lottie_theme_update_path_has_no_console_log() -> None:
    """主题切换是普通用户路径，不应在每次切换时同步写 console。"""
    source = APP_JS.read_text(encoding="utf-8")
    body = _extract_function_body(source, "updateLottieAnimationColor")

    assert "console.log" not in body
    assert 'console.log("theme-changed event:"' not in source
