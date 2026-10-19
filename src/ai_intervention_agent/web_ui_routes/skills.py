"""Skill catalogue route Mixin — data source of the feedback box's ``/`` picker."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from flask import jsonify
from flask.typing import ResponseReturnValue

from ai_intervention_agent.enhanced_logging import EnhancedLogger
from ai_intervention_agent.i18n import msg
from ai_intervention_agent.skill_catalog import get_catalog

if TYPE_CHECKING:
    from flask import Flask

    from ai_intervention_agent.web_ui_rate_limiter import WebUiLimiterProtocol

logger = EnhancedLogger(__name__)


def get_config() -> Any:
    """Lazy proxy kept patchable for the skill routes.

    ``config_manager`` builds the global ``ConfigManager`` (and the Pydantic
    section models) at import time; the cold-start budget of the Web UI forbids
    paying for that before a request actually needs the configuration.
    """
    from ai_intervention_agent.config_manager import get_config as _get_config

    return _get_config()


class SkillRoutesMixin:
    """提供 1 个技能目录路由，由 WebFeedbackUI 通过 MRO 继承。"""

    if TYPE_CHECKING:
        app: Flask
        limiter: WebUiLimiterProtocol

    def _setup_skill_routes(self) -> None:
        @self.app.route("/api/skills", methods=["GET"])
        @self.limiter.limit("60 per minute")
        def get_skills() -> ResponseReturnValue:
            """列出反馈输入框 ``/`` 选择器可用的 skill 与自定义命令
            ---
            tags:
              - Feedback
            description: |
              **幂等性 (idempotent + safe)**: HTTP GET，无副作用。扫描
              ``[feedback] skill_dirs`` 指向的目录（``"auto"`` 展开为
              ``~/.cursor/skills``、``~/.claude/skills``、``~/.codex/skills``、
              ``~/.agents/skills`` 及对应的 commands 目录和项目级同名目录），
              结果在服务端缓存 30 秒。只返回展示用元数据，不返回文件内容或
              绝对路径。
            responses:
              200:
                description: 技能与命令列表
                schema:
                  type: object
                  properties:
                    status:
                      type: string
                      example: success
                    skills:
                      type: array
                      items:
                        type: object
                        properties:
                          name:
                            type: string
                            description: 展示名（frontmatter name 或目录名）
                          insert:
                            type: string
                            description: 插入到 ``/`` 之后的单词
                          description:
                            type: string
                            description: 简介（最长 300 字符）
                          kind:
                            type: string
                            enum: [skill, command]
                          source:
                            type: string
                            description: 来源目录的简短标签（如 ``~/.cursor/skills``）
                    truncated:
                      type: boolean
                      description: 条目数或扫描时间触达上限时为 true
              500:
                description: 读取配置或扫描失败
                schema:
                  type: object
                  properties:
                    status:
                      type: string
                      enum: [error]
                    message:
                      type: string
            """
            try:
                feedback_config = get_config().get_section("feedback")
                catalog = get_catalog(feedback_config.get("skill_dirs"))
                return jsonify(
                    {
                        "status": "success",
                        "skills": catalog["skills"],
                        "truncated": catalog["truncated"],
                    }
                )
            except Exception as exc:
                logger.error(f"Failed to list skills: {exc}", exc_info=True)
                return jsonify(
                    {"status": "error", "message": msg("feedback.serverError")}
                ), 500
