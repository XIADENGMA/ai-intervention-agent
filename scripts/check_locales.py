#!/usr/bin/env python3
"""Locale 文件一致性校验：确保 en.json 和 zh-CN.json 的 key 完全对齐。

可集成到 CI Gate，也可单独运行：
    uv run python scripts/check_locales.py
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


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    all_errors: list[str] = []

    locale_dirs = [
        (root / "static" / "locales", "Web UI"),
        (root / "packages" / "vscode" / "locales", "VS Code Plugin"),
    ]

    for dir_path, label in locale_dirs:
        if dir_path.exists():
            all_errors.extend(check_locale_pair(dir_path, label))

    vscode_dir = root / "packages" / "vscode"
    if vscode_dir.exists():
        all_errors.extend(check_nls_pair(vscode_dir))

    if all_errors:
        print(f"❌ 发现 {len(all_errors)} 个 locale 一致性问题：")
        for err in all_errors:
            print(f"  - {err}")
        return 1

    print("✅ Locale 文件一致性检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
