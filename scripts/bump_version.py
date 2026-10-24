from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_text_or_none(path: Path, *, label: str) -> str | None:
    try:
        return _read_text(path)
    except FileNotFoundError:
        print(f"{label}: 文件不存在：{path}", file=sys.stderr)
    except OSError as e:
        print(f"{label}: 读取失败：{e}", file=sys.stderr)
    return None


def _load_json_object(text: str, *, label: str) -> dict[str, object] | None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        print(
            f"{label}: JSON 解析失败（{e.msg} at line {e.lineno} col {e.colno}）",
            file=sys.stderr,
        )
        return None

    if not isinstance(data, dict):
        print(f"{label}: expected JSON object", file=sys.stderr)
        return None
    return data


def _write_text_atomic(path: Path, content: str) -> None:
    import tempfile

    fd, tmp_path = tempfile.mkstemp(suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _replace_first(
    pattern: re.Pattern[str], repl: str, text: str, *, label: str
) -> str:
    new_text, n = pattern.subn(repl, text, count=1)
    if n != 1:
        raise ValueError(f"{label}: expected 1 match, got {n}")
    return new_text


def _update_pyproject_version(text: str, new_version: str) -> str:
    lines = text.splitlines(keepends=True)
    start = None
    for i, line in enumerate(lines):
        if line.strip() == "[project]":
            start = i
            break
    if start is None:
        raise ValueError("pyproject.toml: missing [project] section")

    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("[") and lines[i].strip().endswith("]"):
            end = i
            break

    found = False
    for i in range(start + 1, end):
        line = lines[i]
        line_ending = "\n" if line.endswith("\n") else ""
        line_body = line[:-1] if line_ending else line
        m = re.match(r'^(\s*version\s*=\s*)"(.*)"([ \t]*)$', line_body)
        if m:
            prefix, _old, suffix = m.groups()
            lines[i] = f'{prefix}"{new_version}"{suffix}{line_ending}'
            found = True
            break

    if not found:
        raise ValueError('pyproject.toml: missing version = "..." under [project]')

    return "".join(lines)


def _extract_pyproject_version(text: str) -> str | None:
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() == "[project]":
            start = i
            break
    if start is None:
        return None

    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("[") and lines[i].strip().endswith("]"):
            end = i
            break

    for i in range(start + 1, end):
        m = re.match(r'^\s*version\s*=\s*"([^"]+)"\s*$', lines[i])
        if m:
            return m.group(1)
    return None


def _update_uv_lock_version(text: str, new_version: str) -> str:
    lines = text.splitlines(keepends=True)
    in_pkg = False
    is_target = False
    for i, line in enumerate(lines):
        if line.strip() == "[[package]]":
            in_pkg = True
            is_target = False
            continue

        if in_pkg:
            name_m = re.match(r'^name\s*=\s*"([^"]+)"\s*$', line.strip())
            if name_m and name_m.group(1) == "ai-intervention-agent":
                is_target = True
                continue

            if is_target:
                ver_m = re.match(r'^(version\s*=\s*)"([^"]+)"(\s*)$', line.strip())
                if ver_m:
                    prefix, _old, suffix = ver_m.groups()

                    indent_match = re.match(r"^(\s*)", line)
                    indent = indent_match.group(1) if indent_match else ""
                    lines[i] = f'{indent}{prefix}"{new_version}"{suffix}\n'
                    return "".join(lines)

    raise ValueError('uv.lock: missing package entry for name="ai-intervention-agent"')


def _extract_uv_lock_version(text: str) -> str | None:
    lines = text.splitlines()
    in_pkg = False
    is_target = False
    for line in lines:
        if line.strip() == "[[package]]":
            in_pkg = True
            is_target = False
            continue
        if not in_pkg:
            continue
        name_m = re.match(r'^name\s*=\s*"([^"]+)"\s*$', line.strip())
        if name_m:
            is_target = name_m.group(1) == "ai-intervention-agent"
            continue
        if is_target:
            ver_m = re.match(r'^version\s*=\s*"([^"]+)"\s*$', line.strip())
            if ver_m:
                return ver_m.group(1)
    return None


def _update_json_version_text(text: str, new_version: str, *, label: str) -> str:
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"{label}: expected JSON object")
    data["version"] = new_version
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _update_package_lock_text(text: str, new_version: str) -> str:
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("package-lock.json: expected JSON object")

    data["version"] = new_version
    packages = data.get("packages")
    if isinstance(packages, dict):
        root_pkg = packages.get("")
        if isinstance(root_pkg, dict):
            root_pkg["version"] = new_version
        vscode_pkg = packages.get("packages/vscode")
        if isinstance(vscode_pkg, dict):
            vscode_pkg["version"] = new_version

    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _update_bug_template(text: str, new_version: str) -> str:
    pat = re.compile(r"(placeholder:\s*e\.g\.\s*)(\S+)")
    return _replace_first(pat, rf"\g<1>{new_version}", text, label="bug_report.yml")


def _extract_bug_template_example_version(text: str) -> str | None:
    pat = re.compile(r"placeholder:\s*e\.g\.\s*(\S+)")
    m = pat.search(text)
    return m.group(1) if m else None


def _update_citation_version(text: str, new_version: str) -> str:
    pat = re.compile(r'^(version:\s*)"[^"]*"', re.MULTILINE)
    return _replace_first(pat, rf'\g<1>"{new_version}"', text, label="CITATION.cff")


def _extract_citation_version(text: str) -> str | None:
    pat = re.compile(r'^version:\s*"([^"]*)"', re.MULTILINE)
    m = pat.search(text)
    return m.group(1) if m else None


# ``date-released: "2026-09-07"``；引号可以是双引号、单引号或没有，改写时原样保留。
_CITATION_DATE_RE = re.compile(
    r"^(date-released:[ \t]*)([\"']?)(\d{4}-\d{2}-\d{2})\2[ \t]*$", re.MULTILINE
)


def _extract_citation_date(text: str) -> str | None:
    """``CITATION.cff`` 顶层 ``date-released`` 的值；没有这个字段返回 ``None``。"""
    m = _CITATION_DATE_RE.search(text)
    return m.group(3) if m else None


def _update_citation_date(text: str, release_date: str) -> str:
    """把 ``date-released`` 改成 ``release_date``（``YYYY-MM-DD``），其余字节不动。"""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", release_date):
        raise ValueError(f"release_date 必须是 YYYY-MM-DD：{release_date!r}")
    datetime.date.fromisoformat(release_date)
    return _replace_first(
        _CITATION_DATE_RE,
        rf"\g<1>\g<2>{release_date}\g<2>",
        text,
        label="CITATION.cff date-released",
    )


def _changelog_release_date(text: str, version: str) -> str | None:
    """``CHANGELOG.md`` 里 ``## [<version>] - YYYY-MM-DD`` 标题写的发布日期（R874）。

    分隔符可以是连字符、en dash 或 em dash（这个文件两种写法都有）；标题后面还可以跟
    ``[YANKED]`` 之类的备注。没有这个标题、或写的不是一个真实存在的日期，返回 ``None``。
    同一个版本出现多次时取最靠前的有效标题。
    """
    heading = re.compile(
        rf"^## \[{re.escape(version)}\][ \t]+[-\u2013\u2014][ \t]+"
        r"(\d{4}-\d{2}-\d{2})(?:[ \t].*)?\r?$",
        re.MULTILINE,
    )
    for match in heading.finditer(text):
        try:
            datetime.date.fromisoformat(match.group(1))
        except ValueError:
            continue
        return match.group(1)
    return None


def _update_citation(text: str, new_version: str, release_date: str | None) -> str:
    """``CITATION.cff`` 的新内容：版本号，加上（已知时）与 CHANGELOG 一致的发布日期。"""
    updated = _update_citation_version(text, new_version)
    if release_date is not None and _extract_citation_date(updated) is not None:
        updated = _update_citation_date(updated, release_date)
    return updated


def _read_text_or_none_quiet(path: Path) -> str | None:
    try:
        return _read_text(path)
    except OSError:
        return None


def _citation_date_warning(root: Path, new_version: str) -> str | None:
    """CHANGELOG 里还没有该版本的带日期标题、而 ``CITATION.cff`` 有日期要同步时的提示。"""
    changelog = _read_text_or_none_quiet(root / "CHANGELOG.md")
    citation = _read_text_or_none_quiet(root / "CITATION.cff")
    if changelog is None or citation is None:
        return None
    current = _extract_citation_date(citation)
    if current is None or _changelog_release_date(changelog, new_version) is not None:
        return None
    return (
        f'WARNING (R874): CHANGELOG.md 里没有 "## [{new_version}] - YYYY-MM-DD" 标题，'
        f"CITATION.cff 的 date-released 保持 {current} 不变。"
        "请先把 [Unreleased] 改成这个标题再 bump，或手动改 date-released。（继续 bump）"
    )


def _citation_dry_run_note(
    root: Path, updated: str, new_version: str, release_date: str | None
) -> str:
    """``--dry-run`` 里 ``CITATION.cff`` 那一行的说明：会改哪些字段，日期怎么处理（R881）。"""
    current = _read_text_or_none_quiet(root / "CITATION.cff")
    if current is None:
        return ""
    fields: list[str] = []
    if _extract_citation_version(current) != _extract_citation_version(updated):
        fields.append("version")
    old_date = _extract_citation_date(current)
    new_date = _extract_citation_date(updated)
    if old_date is not None and new_date != old_date:
        fields.append(f"date-released {old_date} → {new_date}")
    elif old_date is not None and release_date is None:
        fields.append(
            f"date-released 保持 {old_date} 不变，"
            f'CHANGELOG.md 里没有 "## [{new_version}] - YYYY-MM-DD" 标题'
        )
    return f"  ({'；'.join(fields)})" if fields else ""


def _dry_run_lines(
    root: Path,
    new_version: str,
    release_date: str | None,
    pending_writes: list[tuple[Path, str]],
) -> list[str]:
    """``--dry-run`` 打印的内容：真正 bump 时会改哪些文件（R881）。"""
    if not pending_writes:
        return [
            f"所有目标文件已是 {new_version}，没有需要修改的文件（dry-run：未写文件）。"
        ]
    lines = [f"将同步版本号到 {new_version}（dry-run：未写文件），会修改："]
    for path, updated in pending_writes:
        line = f"- {path.relative_to(root).as_posix()}"
        if path == root / "CITATION.cff":
            line += _citation_dry_run_note(root, updated, new_version, release_date)
        lines.append(line)
    return lines


def _changelog_unreleased_section(text: str) -> tuple[int, int] | None:
    """返回 ``[Unreleased]`` 区段在 ``text`` 中的 ``(start, end)`` 字节索引。"""
    head = re.search(r"^## \[Unreleased\]\s*$", text, re.MULTILINE)
    if head is None:
        return None
    start = head.end()
    next_release = re.search(r"^## \[", text[start:], re.MULTILINE)
    end = start + next_release.start() if next_release else len(text)
    return (start, end)


def _unreleased_section_is_empty(text: str) -> bool:
    """``CHANGELOG.md [Unreleased]`` 是否为空（无任何 bullet 条目）。"""
    span = _changelog_unreleased_section(text)
    if span is None:
        return True
    start, end = span
    section = text[start:end]
    return re.search(r"^\s*[-*]\s+\S", section, re.MULTILINE) is None


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, cwd=_repo_root(), check=True)


def _maybe_run_ci_gate(*, include_vscode: bool) -> None:
    cmd = ["uv", "run", "python", "scripts/ci_gate.py"]
    if include_vscode:
        cmd.append("--with-vscode")
    _run(cmd)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="一键同步项目版本号（Python + Node + VSCode 扩展）。建议使用：uv run python scripts/bump_version.py X.Y.Z",
    )
    parser.add_argument(
        "version",
        nargs="?",
        help="目标版本号（SemVer），例如 1.4.18 或 1.4.18-rc.1。不提供时：--check 会自动使用 pyproject.toml 的版本。",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check", action="store_true", help="仅检查是否已是该版本（不写文件）"
    )
    parser.add_argument(
        "--from-pyproject",
        action="store_true",
        help="从 pyproject.toml 读取版本号作为目标版本（主要用于 --check；不建议用于实际 bump）。",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "R881：按真正 bump 的流程校验并计算，只打印将修改的文件列表"
            "（不写文件，也不执行 --ci-gate）。版本号不合法、文件缺失、更新失败时"
            "与真正 bump 一样报错退出，警告也一样打印。不能与 --check 同用。"
        ),
    )
    parser.add_argument(
        "--ci-gate",
        action="store_true",
        help="在版本同步完成后执行本地 CI Gate（uv/ruff/ty/pytest/minify + 可选 vscode）",
    )
    parser.add_argument(
        "--with-vscode",
        action="store_true",
        help="配合 --ci-gate：包含 npm run vscode:check（默认不包含）",
    )
    parser.add_argument(
        "--warn-empty-unreleased",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "R183：bump 时若 CHANGELOG.md [Unreleased] 看起来为空，"
            "打印 WARNING 到 stderr（仍继续 bump）。"
            "防止『忘记 backfill 入口』导致空 changelog 发布。默认开启。"
        ),
    )
    args = parser.parse_args(argv)

    root = _repo_root()

    raw_version = (args.version or "").strip()
    if not raw_version:
        if args.from_pyproject and not args.check:
            print(
                "--from-pyproject 仅用于 --check（请显式传入要 bump 的新版本号）",
                file=sys.stderr,
            )
            return 2

        if args.check or args.from_pyproject:
            pyproject_text = _read_text_or_none(
                root / "pyproject.toml", label="pyproject.toml"
            )
            if pyproject_text is None:
                return 1

            pyproject_ver = _extract_pyproject_version(pyproject_text)
            if not pyproject_ver:
                print(
                    'pyproject.toml: 无法解析 [project].version（期望存在 version = "..."）',
                    file=sys.stderr,
                )
                return 1
            raw_version = pyproject_ver.strip()
        else:
            print(
                "缺少版本号：请提供 X.Y.Z（例如 1.4.18），或使用 --check",
                file=sys.stderr,
            )
            return 2

    new_version = raw_version
    if not _SEMVER_RE.match(new_version):
        print(f"版本号格式不合法：{new_version}", file=sys.stderr)
        return 2

    changelog_text = _read_text_or_none_quiet(root / "CHANGELOG.md")
    release_date = (
        None
        if changelog_text is None
        else _changelog_release_date(changelog_text, new_version)
    )

    targets: list[tuple[Path, Callable[[str], str]]] = [
        (root / "pyproject.toml", lambda t: _update_pyproject_version(t, new_version)),
        (root / "uv.lock", lambda t: _update_uv_lock_version(t, new_version)),
        (
            root / "package.json",
            lambda t: _update_json_version_text(t, new_version, label="package.json"),
        ),
        (
            root / "package-lock.json",
            lambda t: _update_package_lock_text(t, new_version),
        ),
        (
            root / "packages" / "vscode" / "package.json",
            lambda t: _update_json_version_text(
                t, new_version, label="packages/vscode/package.json"
            ),
        ),
        (
            root / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml",
            lambda t: _update_bug_template(t, new_version),
        ),
        (
            root / "CITATION.cff",
            lambda t: _update_citation(t, new_version, release_date),
        ),
    ]

    if args.check:
        bad = False

        pyproject_text = _read_text_or_none(
            root / "pyproject.toml", label="pyproject.toml"
        )
        if pyproject_text is None:
            bad = True
        else:
            cur = _extract_pyproject_version(pyproject_text)
            if cur is None:
                bad = True
                print(
                    'pyproject.toml: 无法解析 [project].version（期望存在 version = "..."）',
                    file=sys.stderr,
                )
            elif cur != new_version:
                bad = True
                print(
                    f"版本不一致：pyproject.toml（当前: {cur}，期望: {new_version}）",
                    file=sys.stderr,
                )

        uv_lock_text = _read_text_or_none(root / "uv.lock", label="uv.lock")
        if uv_lock_text is None:
            bad = True
        else:
            cur = _extract_uv_lock_version(uv_lock_text)
            if cur is None:
                bad = True
                print(
                    'uv.lock: 无法解析 name="ai-intervention-agent" 的 version 字段',
                    file=sys.stderr,
                )
            elif cur != new_version:
                bad = True
                print(
                    f"版本不一致：uv.lock（当前: {cur}，期望: {new_version}）",
                    file=sys.stderr,
                )

        root_pkg_text = _read_text_or_none(root / "package.json", label="package.json")
        if root_pkg_text is None:
            bad = True
        else:
            root_pkg = _load_json_object(root_pkg_text, label="package.json")
            if root_pkg is None:
                bad = True
            else:
                cur_v = root_pkg.get("version")
                if not isinstance(cur_v, str):
                    bad = True
                    print("package.json: 缺少字符串字段 version", file=sys.stderr)
                elif cur_v != new_version:
                    bad = True
                    print(
                        f"版本不一致：package.json（当前: {cur_v}，期望: {new_version}）",
                        file=sys.stderr,
                    )

        vscode_pkg_text = _read_text_or_none(
            root / "packages" / "vscode" / "package.json",
            label="packages/vscode/package.json",
        )
        if vscode_pkg_text is None:
            bad = True
        else:
            vscode_pkg = _load_json_object(
                vscode_pkg_text, label="packages/vscode/package.json"
            )
            if vscode_pkg is None:
                bad = True
            else:
                cur_v = vscode_pkg.get("version")
                if not isinstance(cur_v, str):
                    bad = True
                    print(
                        "packages/vscode/package.json: 缺少字符串字段 version",
                        file=sys.stderr,
                    )
                elif cur_v != new_version:
                    bad = True
                    print(
                        f"版本不一致：packages/vscode/package.json（当前: {cur_v}，期望: {new_version}）",
                        file=sys.stderr,
                    )

        plock_text = _read_text_or_none(
            root / "package-lock.json", label="package-lock.json"
        )
        if plock_text is None:
            bad = True
        else:
            plock = _load_json_object(plock_text, label="package-lock.json")
            if plock is None:
                bad = True
            else:
                cur_v = plock.get("version")
                if not isinstance(cur_v, str):
                    bad = True
                    print("package-lock.json: 缺少字符串字段 version", file=sys.stderr)
                elif cur_v != new_version:
                    bad = True
                    print(
                        f"版本不一致：package-lock.json（当前: {cur_v}，期望: {new_version}）",
                        file=sys.stderr,
                    )

                packages_obj = plock.get("packages")
                if not isinstance(packages_obj, dict):
                    bad = True
                    print("package-lock.json: 缺少对象字段 packages", file=sys.stderr)
                else:
                    packages = cast(dict[str, object], packages_obj)

                    root_pkg_obj = packages.get("")
                    if not isinstance(root_pkg_obj, dict):
                        bad = True
                        print(
                            'package-lock.json: packages[""] 缺失或类型错误',
                            file=sys.stderr,
                        )
                    else:
                        root_pkg = cast(dict[str, object], root_pkg_obj)
                        rv = root_pkg.get("version")
                        if not isinstance(rv, str):
                            bad = True
                            print(
                                'package-lock.json: packages[""].version 缺失或类型错误',
                                file=sys.stderr,
                            )
                        elif rv != new_version:
                            bad = True
                            print(
                                f'版本不一致：package-lock.json:packages[""]（当前: {rv}，期望: {new_version}）',
                                file=sys.stderr,
                            )

                    vs_pkg_obj = packages.get("packages/vscode")
                    if not isinstance(vs_pkg_obj, dict):
                        bad = True
                        print(
                            'package-lock.json: packages["packages/vscode"] 缺失或类型错误',
                            file=sys.stderr,
                        )
                    else:
                        vs_pkg = cast(dict[str, object], vs_pkg_obj)
                        vv = vs_pkg.get("version")
                        if not isinstance(vv, str):
                            bad = True
                            print(
                                'package-lock.json: packages["packages/vscode"].version 缺失或类型错误',
                                file=sys.stderr,
                            )
                        elif vv != new_version:
                            bad = True
                            print(
                                '版本不一致：package-lock.json:packages["packages/vscode"]'
                                f"（当前: {vv}，期望: {new_version}）",
                                file=sys.stderr,
                            )

        bug_template_path = root / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml"
        bug_text = _read_text_or_none(
            bug_template_path, label=".github/ISSUE_TEMPLATE/bug_report.yml"
        )
        if bug_text is None:
            bad = True
        else:
            cur = _extract_bug_template_example_version(bug_text)
            if cur is None:
                bad = True
                print(
                    ".github/ISSUE_TEMPLATE/bug_report.yml: 无法解析示例版本"
                    "（期望存在 `placeholder: e.g. X.Y.Z`）",
                    file=sys.stderr,
                )
            elif cur != new_version:
                bad = True
                print(
                    f"版本不一致：.github/ISSUE_TEMPLATE/bug_report.yml"
                    f"（当前: {cur}，期望: {new_version}）",
                    file=sys.stderr,
                )

        citation_path = root / "CITATION.cff"
        citation_text = _read_text_or_none(citation_path, label="CITATION.cff")
        if citation_text is None:
            bad = True
        else:
            cur = _extract_citation_version(citation_text)
            if cur is None:
                bad = True
                print(
                    "CITATION.cff: 无法解析顶层 version 字段"
                    '（期望存在 `version: "X.Y.Z"`）',
                    file=sys.stderr,
                )
            elif cur != new_version:
                bad = True
                print(
                    f"版本不一致：CITATION.cff（当前: {cur}，期望: {new_version}）",
                    file=sys.stderr,
                )

        if bad:
            return 1

        print("OK：所有目标文件版本号一致。")
        return 0

    if args.warn_empty_unreleased:
        changelog_path = root / "CHANGELOG.md"
        if changelog_path.exists():
            try:
                cl_text = _read_text(changelog_path)
            except OSError:
                cl_text = None
            if cl_text is not None and _unreleased_section_is_empty(cl_text):
                print(
                    "WARNING (R183): CHANGELOG.md [Unreleased] 看起来为空——"
                    "是否忘了把本次 bump 的发布说明落到该区段？"
                    "（继续 bump；通过 --no-warn-empty-unreleased 关闭此提示）",
                    file=sys.stderr,
                )

    date_warning = _citation_date_warning(root, new_version)
    if date_warning is not None:
        print(date_warning, file=sys.stderr)

    pending_writes: list[tuple[Path, str]] = []
    for path, transformer in targets:
        if not path.exists():
            print(f"文件不存在：{path.relative_to(root)}", file=sys.stderr)
            return 1

        try:
            raw = _read_text(path)
        except OSError as e:
            print(f"读取失败：{path.relative_to(root)}: {e}", file=sys.stderr)
            return 1

        try:
            updated = transformer(raw)
        except Exception as e:
            print(
                f"更新失败：{path.relative_to(root)}: {type(e).__name__}: {e}",
                file=sys.stderr,
            )
            return 1
        if updated != raw:
            pending_writes.append((path, updated))

    if args.dry_run:
        for line in _dry_run_lines(root, new_version, release_date, pending_writes):
            print(line)
        return 0

    for path, content in pending_writes:
        _write_text_atomic(path, content)

    print(f"已同步版本号到：{new_version}")

    if args.ci_gate:
        _maybe_run_ci_gate(include_vscode=bool(args.with_vscode))

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
