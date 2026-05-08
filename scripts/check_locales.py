#!/usr/bin/env python3
"""Locale 文件一致性校验：确保 en.json 和 zh-CN.json 的 key 完全对齐。

可集成到 CI Gate，也可单独运行：
    uv run python scripts/check_locales.py

退出码
------
- 0：所有 locale 文件键集合一致；跨端 ``aiia.*`` namespace 对齐。
- 1：至少一个一致性问题；逐项输出错误列表。
- 2：配置错误（核心 locale 目录或文件解析后指向不存在的位置）。
  R102 之前这条路径返回 0（silent skip），与 R76 重布局后 R88/R100/
  R101 修过的同款 silent-broken 风险一致；改为 fail-loud 让 reviewer
  立刻看到漂移。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def flatten_keys(obj: dict, prefix: str = "") -> set[str]:
    """递归展平 JSON 对象为 dot-separated key 集合。"""
    keys: set[str] = set()
    for k, v in obj.items():
        full_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            keys |= flatten_keys(v, full_key)
        else:
            keys.add(full_key)
    return keys


def check_locale_pair(dir_path: Path, label: str) -> list[str]:
    """校验一对 locale 文件（en.json + zh-CN.json），返回错误列表。"""
    errors: list[str] = []
    en_file = dir_path / "en.json"
    zh_file = dir_path / "zh-CN.json"

    if not en_file.exists():
        errors.append(f"[{label}] 缺少 en.json: {en_file}")
        return errors
    if not zh_file.exists():
        errors.append(f"[{label}] 缺少 zh-CN.json: {zh_file}")
        return errors

    try:
        en_data = json.loads(en_file.read_text(encoding="utf-8"))
        zh_data = json.loads(zh_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        errors.append(f"[{label}] JSON 解析失败: {e}")
        return errors

    en_keys = flatten_keys(en_data)
    zh_keys = flatten_keys(zh_data)

    missing_in_zh = sorted(en_keys - zh_keys)
    missing_in_en = sorted(zh_keys - en_keys)

    for key in missing_in_zh:
        errors.append(f"[{label}] zh-CN.json 缺少 key: {key}")
    for key in missing_in_en:
        errors.append(f"[{label}] en.json 缺少 key: {key}")

    return errors


def check_nls_pair(dir_path: Path) -> list[str]:
    """校验 VS Code package.nls.json 和 package.nls.zh-CN.json。"""
    errors: list[str] = []
    en_file = dir_path / "package.nls.json"
    zh_file = dir_path / "package.nls.zh-CN.json"

    if not en_file.exists() or not zh_file.exists():
        return errors

    try:
        en_data = json.loads(en_file.read_text(encoding="utf-8"))
        zh_data = json.loads(zh_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        errors.append(f"[package.nls] JSON 解析失败: {e}")
        return errors

    en_keys = set(en_data.keys())
    zh_keys = set(zh_data.keys())

    for key in sorted(en_keys - zh_keys):
        errors.append(f"[package.nls] zh-CN 缺少 key: {key}")
    for key in sorted(zh_keys - en_keys):
        errors.append(f"[package.nls] en 缺少 key: {key}")

    return errors


def check_cross_platform_aiia_parity(web_dir: Path, vscode_dir: Path) -> list[str]:
    """跨端 ``aiia.*`` namespace 必须在 Web UI 和 VSCode 插件之间完全对齐。

    命名规则（内联契约）：
      - ``aiia.*`` 是「跨端共享」命名空间，所有 key 必须在 Web UI
        (``static/locales/*.json``) 与 VSCode 插件 (``packages/vscode/locales/*.json``)
        的 4 个 locale 文件里一字不差，便于未来抽取共享 locale 模块时零改引用。
      - 其他顶层 namespace（``page``/``settings``/``ui``/``status``/``statusBar`` 等）
        两端各自独立，不受本检查约束——两端 UI 结构不同，没有对齐价值。
      - ``aiia`` 完全缺席时（两端都还没引入共享 key），本检查默认通过；
        它只在至少一端开始引入 ``aiia.*`` key 后才起作用（默认安全 + 渐进约束）。
    """
    errors: list[str] = []
    for locale in ("en.json", "zh-CN.json"):
        web_file = web_dir / locale
        vscode_file = vscode_dir / locale
        if not web_file.exists() or not vscode_file.exists():
            continue
        try:
            web_data = json.loads(web_file.read_text(encoding="utf-8"))
            vscode_data = json.loads(vscode_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue

        web_aiia_block = web_data.get("aiia")
        vscode_aiia_block = vscode_data.get("aiia")
        if not isinstance(web_aiia_block, dict):
            web_aiia_block = {}
        if not isinstance(vscode_aiia_block, dict):
            vscode_aiia_block = {}

        web_aiia_keys = flatten_keys(web_aiia_block, prefix="aiia")
        vscode_aiia_keys = flatten_keys(vscode_aiia_block, prefix="aiia")

        for key in sorted(web_aiia_keys - vscode_aiia_keys):
            errors.append(f"[cross-platform {locale}] VSCode 缺少 aiia.* key: {key}")
        for key in sorted(vscode_aiia_keys - web_aiia_keys):
            errors.append(f"[cross-platform {locale}] Web UI 缺少 aiia.* key: {key}")

    return errors


def main() -> int:
    root = Path(__file__).resolve().parent.parent

    web_locales_dir = root / "src" / "ai_intervention_agent" / "static" / "locales"
    vscode_locales_dir = root / "packages" / "vscode" / "locales"
    vscode_dir = root / "packages" / "vscode"

    # R102：layer-0 path-drift sanity check —— 4 个核心 locale 资源必须
    # 真实存在，缺失即 fail-loud (exit 2) 而非 silent skip 返回 0。
    # ``check_locales.py`` 之前用嵌套 ``if X.exists():`` 守护每个分支：
    #   - locale_dirs / vscode_dir / cross-platform 任一漂移 → 对应分支
    #     silent 0 coverage；
    #   - ``check_nls_pair`` 内部 ``if not en or not zh: return []`` 也是
    #     silent skip（vscode_dir 存在但 ``package.nls.json`` 缺失时）；
    #   - ``check_cross_platform_aiia_parity`` 内部同款 silent ``continue``。
    # R76 重布局把 ``static/`` 挪进 ``src/`` 包内时让 R66 brand-color
    # guard silently broken（R88 修），R100/R101 把同款修复 port 到 HTML
    # coverage 和 ts/js no-cjk 扫描器，R102 收尾把它从最后一个 i18n 一致
    # 性扫描器里也清出去。
    required_paths = [
        (web_locales_dir / "en.json", "Web UI 源 locale"),
        (web_locales_dir / "zh-CN.json", "Web UI zh-CN locale"),
        (vscode_locales_dir / "en.json", "VS Code 源 locale"),
        (vscode_locales_dir / "zh-CN.json", "VS Code zh-CN locale"),
        (vscode_dir / "package.nls.json", "VS Code package.nls 源"),
        (vscode_dir / "package.nls.zh-CN.json", "VS Code package.nls zh-CN"),
    ]
    missing = [(path, label) for path, label in required_paths if not path.exists()]
    if missing:
        print(
            "ERROR: missing required locale resources (configuration drift, "
            "not 'OK' — failing loud per R102, mirrors R88/R100/R101):",
            file=sys.stderr,
        )
        for path, label in missing:
            rel = path.relative_to(root).as_posix()
            print(
                f"  - {label}: {rel}\n    Resolved absolute path: {path}",
                file=sys.stderr,
            )
        print(
            "\nThese resources are project core (i18n source of truth). If a\n"
            "refactor moved them, update the path constants at the top of\n"
            "scripts/check_locales.py (and any matching CI gate).",
            file=sys.stderr,
        )
        return 2

    all_errors: list[str] = []

    locale_dirs = [
        (web_locales_dir, "Web UI"),
        (vscode_locales_dir, "VS Code Plugin"),
    ]

    for dir_path, label in locale_dirs:
        all_errors.extend(check_locale_pair(dir_path, label))

    all_errors.extend(check_nls_pair(vscode_dir))
    all_errors.extend(
        check_cross_platform_aiia_parity(web_locales_dir, vscode_locales_dir)
    )

    if all_errors:
        print(f"❌ 发现 {len(all_errors)} 个 locale 一致性问题：")
        for err in all_errors:
            print(f"  - {err}")
        return 1

    print("✅ Locale 文件一致性检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
