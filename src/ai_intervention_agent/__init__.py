"""ai-intervention-agent 包根 — MCP 服务 + Web UI + 多任务反馈队列。

导入约定（src/ layout，2026-05 R76 重组后）：
- 包顶层模块全部以 ``ai_intervention_agent.<module>`` 形式 import
  例如 ``from ai_intervention_agent.server import main``、
  ``from ai_intervention_agent.config_manager import config_manager``
- 入口函数 ``main`` 通过 ``ai_intervention_agent.server:main`` 注册
  在 ``pyproject.toml`` 的 ``[project.scripts]`` 段。

历史背景：
- 1.5.45 之前所有源码平铺在仓库根（``server.py`` / ``web_ui.py`` / …）
- R76 把 24 个根 ``.py`` + ``config_modules/`` + ``web_ui_routes/``
  整体迁入 ``src/ai_intervention_agent/`` 以满足 PyPA / Hatch 推荐的
  ``src`` layout：编辑期不会因为 ``cwd`` 误 import 到 in-development 文件，
  ``editable install`` 后 import 路径与发布安装路径一致。
"""
