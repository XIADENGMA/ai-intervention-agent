"""TODO#12 — VS Code 设置面板「在编辑器中打开配置文件」按钮链路。

链路（本测试逐段锁定）：
    webview.ts 设置面板 HTML：
        只读 #settingsConfigPath 右侧渲染 #settingsOpenConfigBtn
    webview-settings-ui.js：
        点击按钮 → postMessage({type:'openConfigFile', path:<input 值>})
    webview.ts 宿主 handler：
        case 'openConfigFile' → _handleOpenConfigFile →
        绝对路径校验 → vscode.window.showTextDocument（当前编辑器打开）
    locales：
        en / zh-CN / zh-TW 均含 settings.config.openInEditor(+Title)
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VSCODE_DIR = REPO_ROOT / "packages" / "vscode"


def _read(name: str) -> str:
    return (VSCODE_DIR / name).read_text(encoding="utf-8")


class TestSettingsPanelHtml:
    def test_open_button_rendered_next_to_path_input(self) -> None:
        src = _read("webview.ts")
        assert 'id="settingsOpenConfigBtn"' in src, (
            "设置面板必须渲染打开按钮 #settingsOpenConfigBtn"
        )
        assert "settings-config-path-row" in src, "路径 input 与按钮应包在同一行容器里"
        # 按钮必须在路径 input 之后（同一行、右侧）
        assert src.index('id="settingsConfigPath"') < src.index(
            'id="settingsOpenConfigBtn"'
        )
        assert 'data-i18n="settings.config.openInEditor"' in src
        assert 'data-i18n-title="settings.config.openInEditorTitle"' in src

    def test_button_is_type_button_not_inside_label(self) -> None:
        src = _read("webview.ts")
        row_start = src.index("settings-config-path-row")
        snippet = src[row_start - 600 : row_start + 800]
        assert 'type="button"' in snippet, (
            "按钮必须是 type=button（避免触发表单/label 默认行为）"
        )


class TestFrontendBinding:
    def test_click_posts_open_config_file_message(self) -> None:
        src = _read("webview-settings-ui.js")
        assert "settingsOpenConfigBtn" in src
        assert '"openConfigFile"' in src or "'openConfigFile'" in src
        # path 取自只读 input 的当前值
        idx = src.index("settingsOpenConfigBtn")
        snippet = src[idx : idx + 1200]
        assert "settingsConfigPath" in snippet, (
            "点击处理必须从 #settingsConfigPath 读取路径"
        )


class TestHostHandler:
    def test_message_case_wired(self) -> None:
        src = _read("webview.ts")
        assert re.search(r'case\s+"openConfigFile"\s*:', src), (
            "宿主消息分发必须有 openConfigFile case"
        )
        assert "_handleOpenConfigFile" in src

    def test_handler_validates_absolute_path_and_opens_in_editor(self) -> None:
        src = _read("webview.ts")
        marker = "_handleOpenConfigFile(message: WebviewMessage): void {"
        start = src.find(marker)
        assert start != -1, "找不到 _handleOpenConfigFile 实现"
        open_brace = src.find("{", start + len(marker) - 1)
        depth = 1
        i = open_brace + 1
        while i < len(src) and depth > 0:
            if src[i] == "{":
                depth += 1
            elif src[i] == "}":
                depth -= 1
            i += 1
        body = src[start:i]
        assert "showTextDocument" in body, (
            "必须用 vscode.window.showTextDocument 在当前编辑器打开"
        )
        assert "isAbsolute" in body, "必须做绝对路径防御性校验"
        # Windows 盘符不能被误判成 URI scheme 而拒绝
        assert re.search(r"\[a-zA-Z\]:\[\\\\/\]", body), (
            "绝对路径判断必须兼容 Windows 盘符（C:\\ / C:/）"
        )


class TestLocales:
    def test_all_locales_have_open_in_editor_keys(self) -> None:
        for name in ("en.json", "zh-CN.json", "zh-TW.json"):
            data = json.loads((VSCODE_DIR / "locales" / name).read_text("utf-8"))
            config = data["settings"]["config"]
            assert config.get("openInEditor"), f"{name} 缺 openInEditor"
            assert config.get("openInEditorTitle"), f"{name} 缺 openInEditorTitle"
