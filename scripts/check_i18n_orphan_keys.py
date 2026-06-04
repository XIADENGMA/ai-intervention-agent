#!/usr/bin/env python3
"""L4·G1 – i18n 孤儿 key 扫描（warn 级 CI gate）。

「孤儿」= locale JSON 里存在但下列 surface 都没引用：
  * ``templates/web_ui.html`` 的 ``data-i18n[-*]="..."`` 属性；
  * ``static/js/**/*.js`` 的 ``t('key')`` / ``__…T('key')`` 调用（跳过 vendor/min）；
  * ``packages/vscode/{webview-ui.js, webview-settings-ui.js,
    webview-notify-core.js, webview.ts, extension.ts}`` 同款。

刻意不挂 CI：``tests/test_runtime_behavior.py`` 已经是强制线。此脚本 warn
级输出（exit 0），允许短暂 unlink 下游 gate 继续跑，贡献者本地 rename 时
也能直接看 diff。需要强制时用 ``--strict``（dev-only）。

用法：
    python scripts/check_i18n_orphan_keys.py           # warn
    python scripts/check_i18n_orphan_keys.py --strict  # 命中任一孤儿即 exit 1
    python scripts/check_i18n_orphan_keys.py --json    # 机读

Exit：``0`` 扫完（warn）或无孤儿（strict）；``1`` strict 下有孤儿 / 扫描错误。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

WEB_LOCALES_DIR = ROOT / "src" / "ai_intervention_agent" / "static" / "locales"
VSCODE_LOCALES_DIR = ROOT / "packages" / "vscode" / "locales"
WEB_TEMPLATES_DIR = ROOT / "src" / "ai_intervention_agent" / "templates"
WEB_JS_DIR = ROOT / "src" / "ai_intervention_agent" / "static" / "js"
VSCODE_PKG_DIR = ROOT / "packages" / "vscode"

# Extraction regexes. Must stay in lockstep with
# ``tests/test_runtime_behavior.py`` — if that file expands the set of
# wrapper function names (e.g. a new ``__fooT``), add it here too.
DATA_I18N_RE = re.compile(
    r"""data-i18n(?:-(?:html|title|placeholder|alt|aria-label|value))?\s*=\s*"([^"]+)\"""",
)
# Match ``t('key')``, ``_t('key')``, ``tl('key')``, ``hostT('key')``,
# ``__vuT('key')``, ``__domSecT('key')``, ``__ncT('key')``. The negative
# lookbehind ``(?<![.\w])`` suppresses property-access false positives
# like ``obj.t('x')``. The ``\(\s*`` (rather than the historically tighter
# ``\(``) tolerates Prettier multi-line formatting of the form ::
#
#     _tl(
#       "settings.openConfigInIdeOpened",
#       "Opened with {editor}.",
#     )
#
# Without the ``\s*`` the scanner would silently miss those call sites
# whenever Prettier (or any future formatter) decides to break the
# argument list across lines, making truly-used keys look like dead
# orphans and producing false positives in the strict gate. Must stay
# in sync with ``tests/test_runtime_behavior.py::_JS_T_CALL_RE``.
JS_T_CALL_RE = re.compile(
    # cr40 cycle health-fix #3：加 ``AIIA_I18N.t(...)`` 命名空间识别
    # ——同 ``tests/test_runtime_behavior.py::_JS_T_CALL_RE`` 同步更新。
    # multi_task.js 用 ``window.AIIA_I18N.t("page.taskTabCopyHint")``
    # 调用 i18n，原正则因 ``(?<![.\w])`` 排除 dot-access 而漏识别。
    r"""(?:(?<![.\w])(?:_?tl?|hostT|__vuT|__domSecT|__ncT)|AIIA_I18N\.t)\(\s*['"]([a-zA-Z][a-zA-Z0-9_.]+)['"]\s*[,)]""",
)

# 源码注释剥离：与 ``check_i18n_param_signatures.py::_strip_source_comments``
# 保持语义一致（同一 i18n key 扫描族），避免一个脚本剥注释、另一个不剥
# 造成同一份代码上 ``used_keys`` 数值漂移。历史教训：v1.5 时期
# ``packages/vscode/extension.ts`` 的 banner 注释里写了示例 ``hostT('statusBar.unkown')``
# （故意拼错让 tsc 挂掉），结果本扫描器把注释字符串当成真实引用，导致
# ``used > total`` 的假信号——而 param_signatures 因为已经剥注释看到的是
# 干净结果。两边修法 must stay in lockstep。
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def _strip_source_comments(text: str) -> str:
    """Zero out ``//`` line comments and ``/* ... */`` block comments while
    preserving line offsets so ``find()``-based offsets in callers stay
    accurate. Keep semantics aligned with ``check_i18n_param_signatures.py``.

    Pass order matters: line comments are blanked **before** block
    comments. Otherwise patterns like ``// see locales/*.json`` get
    mis-parsed because the bare ``/*`` inside the *line* comment is read
    as a block-comment opener that swallows hundreds of subsequent lines.
    Stripping line comments first turns the whole ``//`` tail into spaces
    and the orphan ``/*`` disappears with it.

    We replace with space so byte offsets are preserved exactly."""

    def _blank_block(m: re.Match[str]) -> str:
        s = m.group(0)
        return "".join("\n" if ch == "\n" else " " for ch in s)

    out_lines: list[str] = []
    for line in text.split("\n"):
        # 第一步：line comment（``//`` 之后）整段替成空格。
        # Naive ``//`` line-comment strip. Imperfect when ``//`` appears
        # inside string literals (e.g. URL literals), but those never
        # also contain a ``t('key')`` shape so the regex misses them
        # naturally — same trade-off ``check_i18n_param_signatures`` makes.
        idx = line.find("//")
        out_lines.append(line if idx == -1 else line[:idx] + " " * (len(line) - idx))
    intermediate = "\n".join(out_lines)
    # 第二步：剥 block comments。已经在前面剥了 line comments，所以
    # ``// ... locales/*.json`` 这类伪 ``/*`` 起点被一并清空，不会再出现
    # "block comment 跨吞数百行真代码" 的灾难。
    return _BLOCK_COMMENT_RE.sub(_blank_block, intermediate)


# Vendor / min'd JS that we don't own and don't want to treat as call sites.
VENDOR_JS = {
    "mathjax-loader.js",
    "tex-mml-chtml.js",
    "lottie.min.js",
}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _flatten_keys(data: Any, prefix: str = "") -> set[str]:
    out: set[str] = set()
    if isinstance(data, dict):
        for k, v in data.items():
            p = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                out |= _flatten_keys(v, p)
            else:
                out.add(p)
    return out


def _collect_web_used() -> set[str]:
    """Scan HTML templates + static JS for every referenced i18n key.

    HTML 不剥注释（``data-i18n="..."`` 不会出现在 ``<!-- ... -->`` 注释里
    的 attribute slot；浏览器解析约束保证）；JS 先剥源码注释再扫，避免把
    docstring/banner 里的示例当真实引用。
    """
    used: set[str] = set()
    template = WEB_TEMPLATES_DIR / "web_ui.html"
    if template.is_file():
        html = template.read_text(encoding="utf-8", errors="ignore")
        used.update(DATA_I18N_RE.findall(html))
    if WEB_JS_DIR.is_dir():
        for js in sorted(WEB_JS_DIR.glob("*.js")):
            if ".min." in js.name or js.name in VENDOR_JS:
                continue
            src = _strip_source_comments(
                js.read_text(encoding="utf-8", errors="ignore")
            )
            used.update(JS_T_CALL_RE.findall(src))
    return used


def _collect_vscode_used() -> set[str]:
    """Scan packages/vscode/{ui,core,ts} for every referenced i18n key.

    Only the specific surface files are scanned — avoid walking the
    whole directory, because it would false-positive on e.g. locale
    JSON or build output and make the gate noisy.

    源码注释先被剥成空格再扫描，使 banner / docstring 里的示例（含故意
    拼错的反例）不被当作真实引用——这与 ``check_i18n_param_signatures``
    的语义保持一致。"""
    used: set[str] = set()
    targets = (
        "webview-ui.js",
        "webview-settings-ui.js",
        "webview-notify-core.js",
        "webview.ts",
        "extension.ts",
        "notification-providers.ts",
        "applescript-executor.ts",
    )
    for name in targets:
        path = VSCODE_PKG_DIR / name
        if path.is_file():
            text = _strip_source_comments(
                path.read_text(encoding="utf-8", errors="ignore")
            )
            used.update(JS_T_CALL_RE.findall(text))
    return used


def scan() -> dict[str, dict]:
    """Return a structured report for both surfaces.

    Shape::

        {
          'web':    { 'orphans': [...], 'total_keys': N, 'used_keys': M },
          'vscode': { 'orphans': [...], 'total_keys': N, 'used_keys': M },
        }
    """
    # cr40 cycle health-fix #3 — dynamic-key 豁免集合。同步 tests/
    # test_runtime_behavior.py::TestI18nDeadKeys._PRE_RESERVED_KEYS。
    # 这些 keys 在代码里以 ``let msgKey = "..."``变量赋值方式构造，
    # 后面 ``t(msgKey)`` 才用 — 正则无法 trace dynamic key。
    _WEB_RESERVED_DYNAMIC: set[str] = {
        "settings.customSound.errors.generic",
        "settings.customSound.errors.invalidMime",
        "settings.customSound.errors.tooLarge",
        "settings.customSound.errors.readFailed",
        "settings.customSound.errors.storageFailed",
        "settings.customSound.errors.decodeFailed",
        "settings.customSound.errors.durationTooLong",
        "settings.customSound.uploaded",
    }

    report: dict[str, dict] = {}

    web_used = _collect_web_used()
    web_en = WEB_LOCALES_DIR / "en.json"
    if web_en.is_file():
        web_total = _flatten_keys(_load_json(web_en))
        report["web"] = {
            "orphans": sorted(web_total - web_used - _WEB_RESERVED_DYNAMIC),
            "total_keys": len(web_total),
            "used_keys": len(web_used),
        }

    vscode_used = _collect_vscode_used()
    vscode_en = VSCODE_LOCALES_DIR / "en.json"
    if vscode_en.is_file():
        vscode_total = _flatten_keys(_load_json(vscode_en))
        report["vscode"] = {
            "orphans": sorted(vscode_total - vscode_used),
            "total_keys": len(vscode_total),
            "used_keys": len(vscode_used),
        }

    return report


def _format_human(report: dict[str, dict]) -> str:
    lines: list[str] = []
    for label, data in report.items():
        orphans = data["orphans"]
        header = (
            f"[{label}] {len(orphans)} orphan key(s) "
            f"({data['used_keys']} used / {data['total_keys']} total)"
        )
        lines.append(header)
        for k in orphans[:30]:
            lines.append(f"  • {k}")
        if len(orphans) > 30:
            lines.append(f"  ...({len(orphans) - 30} more)")
    return "\n".join(lines) if lines else "No locales scanned."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 if any orphan is found (default: warn-only, exit 0).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of a human-readable report.",
    )
    args = parser.parse_args(argv)

    try:
        report = scan()
    except Exception as exc:
        print(f"check_i18n_orphan_keys: scan failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(_format_human(report))

    total_orphans = sum(len(d["orphans"]) for d in report.values())
    if total_orphans > 0 and args.strict:
        return 1
    # Warn-level default: always 0 so ci_gate keeps flowing.
    return 0


if __name__ == "__main__":
    sys.exit(main())
