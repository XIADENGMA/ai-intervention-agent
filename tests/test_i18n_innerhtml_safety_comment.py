"""强制每处 ``.innerHTML = t(…)`` 必须带 XSS 安全注释（Batch-2 H10）。

动机：i18next 历史上两次 XSS CVE（CVE-2017-16010 / AIKIDO-2024-10543）
同根——调用方把 ``t()`` 输出当 HTML-safe 写进 ``innerHTML``。我们 ``t()``
故意不做 HTML 转义（textContent 自动转义已足够，ICU ``#`` / mustache
再做转义会双编码），与 react-intl 同契约。

调用方契约（可审计）：任何把 ``t(…)`` / ``_t(…)`` / ``hVal`` 等写入
``.innerHTML`` 的行，必须在同行或前一个连续注释块里带 ``AIIA-XSS-SAFE:``
标记（典型场景：dev-authored locale + 无用户输入；或走过
``sanitizePromptHtml``）。

范围：仅覆盖 ``static/js/**`` / ``packages/vscode/**``；排除 ``*.min.js``、
第三方库（prism/marked/mathjax/lottie）、``.vscode-test`` 解包产物。
SVG/markdown/固定 HTML 块不在本策略，交给单独 CSP 治理轨道。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET_GLOBS = [
    ROOT / "static" / "js",
    ROOT / "packages" / "vscode",
]
EXCLUDE_DIRS = {
    "node_modules",
    "vendor",
    "mathjax",
    "lottie",
    "prism-components",
    "dist",
    "test",
    "tests",
    # ``npm run vscode:check`` 会把 VSCode 解包到 .vscode-test/，属 MIT 第三方源码，不审不改
    ".vscode-test",
}
EXCLUDE_FILE_PATTERNS = (
    re.compile(r"\.min\.js$"),
    re.compile(r"^prism(\.|-)", re.IGNORECASE),
    re.compile(r"^marked", re.IGNORECASE),
    re.compile(r"^lottie", re.IGNORECASE),
    re.compile(r"^tex-mml"),
)

SAFETY_MARKER = "AIIA-XSS-SAFE:"

# i18n.js translateDOM 里 ``hEl.innerHTML = hVal``（data-i18n-html 分支）也要同样带标记，不特判
INNERHTML_T_CALL = re.compile(
    r"\.innerHTML\s*[+]?=\s*[^;]*?(?:\bt\(|\b_t\(|\bt\s*\(|\bhVal\b|\b__domSecT\b)"
)

# 空行或 ``//`` / ``/*`` / ``*`` 均视为「属于前置注释块」；marker 只要在连续注释块内出现即可
_COMMENT_LINE = re.compile(r"^\s*(?://|/\*|\*|$)")


def _iter_js_files() -> list[Path]:
    out: list[Path] = []
    for root in TARGET_GLOBS:
        for path in root.rglob("*.js"):
            rel = path.relative_to(ROOT)
            parts = set(rel.parts)
            if parts & EXCLUDE_DIRS:
                continue
            name = path.name
            if any(pat.search(name) for pat in EXCLUDE_FILE_PATTERNS):
                continue
            out.append(path)
        for path in root.rglob("*.ts"):
            rel = path.relative_to(ROOT)
            parts = set(rel.parts)
            if parts & EXCLUDE_DIRS:
                continue
            out.append(path)
    return sorted(out)


def _has_safety_marker(lines: list[str], idx: int) -> bool:
    """Return ``True`` if an ``AIIA-XSS-SAFE:`` marker is attached to
    ``lines[idx]``.

    The marker is accepted when it appears either:

    * on the assignment line itself (trailing ``// AIIA-XSS-SAFE: …``), or
    * anywhere in the contiguous comment block that directly precedes
      the assignment line. The block is the run of consecutive ``//``,
      ``/*``, ``*``, or blank lines immediately above, and stops at the
      first code line — exactly how ``eslint-disable-next-line`` would
      delimit it, generalised to multi-line rationale.
    """
    if SAFETY_MARKER in lines[idx]:
        return True
    cursor = idx - 1
    while cursor >= 0 and _COMMENT_LINE.match(lines[cursor]):
        if SAFETY_MARKER in lines[cursor]:
            return True
        cursor -= 1
    return False


class TestInnerHtmlSafetyComment(unittest.TestCase):
    def test_every_innerhtml_t_call_carries_safety_marker(self) -> None:
        offenders: list[tuple[Path, int, str]] = []
        for path in _iter_js_files():
            lines = path.read_text(encoding="utf-8").splitlines()
            for idx, line in enumerate(lines):
                if not INNERHTML_T_CALL.search(line):
                    continue
                if _has_safety_marker(lines, idx):
                    continue
                offenders.append((path.relative_to(ROOT), idx + 1, line.strip()))
        if offenders:
            formatted = [f"{p}:{ln}: {src}" for (p, ln, src) in offenders]
            self.fail(
                "Each .innerHTML write that consumes a translation must carry "
                "an 'AIIA-XSS-SAFE: <reason>' comment on the same line or in "
                "the contiguous comment block immediately above it (see "
                "docs/i18n.md § Security). Offenders:\n  " + "\n  ".join(formatted)
            )

    def test_marker_regex_does_not_trigger_on_textcontent(self) -> None:
        """自检：regex 不得命中 ``textContent = t(…)`` / ``innerText = t(…)``。"""
        safe_lines = [
            "button.textContent = t('status.copied')",
            "element.innerText = _t('page.label')",
            "span.setAttribute('aria-label', t('aria.close'))",
        ]
        for src in safe_lines:
            with self.subTest(src=src):
                self.assertIsNone(INNERHTML_T_CALL.search(src))

    def test_marker_regex_catches_the_canonical_violations(self) -> None:
        """自检：regex 必须能命中仓库真实使用到的所有模式。"""
        unsafe_lines = [
            "button.innerHTML = checkIconSvg + t('status.copied')",
            "submitBtn.innerHTML = t('status.submitting')",
            "hint.innerHTML = `${svg}${_t('page.noContent.newTasks', { count: count })}`",
            "if (hVal !== hKey) hEl.innerHTML = hVal",
            "button.innerHTML = `${copyIconSvg}${__domSecT('page.copyFailed')}`",
        ]
        for src in unsafe_lines:
            with self.subTest(src=src):
                self.assertIsNotNone(INNERHTML_T_CALL.search(src))

    def test_comment_block_walker_scans_past_multi_line_rationale(self) -> None:
        """多行 ``//`` 注释块视为一个 attached comment。"""
        block = [
            "    // AIIA-XSS-SAFE: dev-authored icon + static locale key.",
            "    // t() does not interpolate user-controlled params here.",
            "    // See docs/i18n.md § Security.",
            "    button.innerHTML = iconSvg + t('status.copied')",
        ]
        self.assertTrue(_has_safety_marker(block, 3))

    def test_comment_block_walker_rejects_detached_markers(self) -> None:
        """标记与赋值行被代码行隔开则不算数，防止陈旧 marker 掩盖新违规。"""
        block = [
            "    // AIIA-XSS-SAFE: belongs to the previous innerHTML call.",
            "    element.classList.add('loaded')",
            "    other.innerHTML = t('status.ready')",
        ]
        self.assertFalse(_has_safety_marker(block, 2))


if __name__ == "__main__":
    unittest.main()
