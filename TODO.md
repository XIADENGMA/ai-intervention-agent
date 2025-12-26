# TODO

- [x] 输入框允许拖入/粘贴/上传图片（允许 base64），并以合适的方式显示在输入框上方
  - 并没有正确传入到 cursor 或其他 ide -> 修改为不使用 base64，使用 fastmcp image 的形式
- [x] 允许接收到反馈时以合适的方式通知（声音/系统通知/bark 通知……
- [ ] 更换页面上字体为版权合适字体
  - 不允许自定义字体，使用用户系统默认字体即可
- [x] 全平台快捷键支持
- [x] 统一使用配置文件，移除环境变量依赖
- [x] 支持 JSONC 格式配置文件（带注释的 JSON）
- [x] 系统通知修复`import plyer`
- [x] 页面显示的 markdown 样式优化
  - 现在只显示基础效果
- [x] 更新 README，英文、中文版本
  - 参考：https://github.com/Minidoracat/mcp-feedback-enhanced/blob/main/README.zh-CN.md
- [x] 重构网页主题
  - [x] 适配深色主题、浅色主题 - 使用 CSS 变量实现主题切换
  - [ ] 适配中文、英文
  - [x] 在`设置`的最下面的`关于`中显示版本信息、github 地址<https://github.com/XIADENGMA/ai-intervention-agent>等
- [ ] 优化 prompt
- [x] 研究是否可以打包成 vscode 插件
  - [x] 在侧边栏显示（基础功能完成），但是现在切换侧边栏标签页回来会有一段时间空白需要等待
  - [x] ~~在底栏显示 MCP 服务状态~~ 当前只显示发送反馈等信息
- [ ] 复制、粘贴优化，特别是在 ios 平台上
- [ ] 全平台支持、发布到 uvx pypi 平台
- [x] github action（设想）
  - [x] 自动发布（release.yml：构建 + 发布 PyPI + 创建 GitHub Release）
    - [x] 自动化测试（test.yml：ruff/ty/pytest/minify_check/coverage）
    - [x] 自动化 pr（dependabot.yml：依赖自动更新 PR）
- [x] 修复 uvx 模式图片反馈问题：`Error calling tool 'interactive_feedback': Unable to serialize unknown type: <class 'fastmcp.utilities.types.Image'>`

  - [x] 改造这条工具链，让它在任何对外返回、跨工具传递的地方，都只传 MCP 协议定义的` ImageContent`（本质是一个包含 `type/data/mimeType` 字段的纯 dict），彻底移除 `fastmcp.utilities.types.Image` 这种类对象。
  - [ ] 现在图片似乎不能被正常识别到，需要进一步排查
    - Cursor 的问题，似乎解决不了，但是别的 mcp 可以 ，比如 chrome-devtools
    - 需要参考：https://github.com/jackbba/mcp-feedback-enhanced
    - [ ] 现在上传图片后似乎太大，需要压缩：Large output has been written to: /home/xiadengma/.cursor/projects/home-xiadengma-Code-Python-ai-intervention-agent-vscode/agent-tools/a980209e-75a7-4660-b99d-2ac77e83f683.txt (253.7 KB, 1 lines)
    - 当前返回格式：
      ```json
      [
        {
          "type": "image",
          "data": "iVBORw0KGgoAAgEAiEvcZ/Aa7jCVtuWheuAAAAAElFTkSuQmCC...",
          "mimeType": "image/png"
        },
        {
          "type": "text",
          "text": "选择的选项: 测试成功，一切正常\n\n用户输入: 无有效内容页面的进度条参考服务端那种效果（现在这个动态效果有点不对）\r\n请积极调用interactive_feedback工具\n\n=== 图片 1 ===\n文件名: image.png\n类型: image/png\n大小: 190.0 KB"
        }
      ]
      ```

- [x] 参考<https://github.com/Pursue-LLL/interactive-feedback-mcp>添加功能
  - [x] task_id 自动生成 - 系统自动生成唯一 task_id（使用时间戳+随机数），不再支持手动指定，彻底避免冲突问题
  - [x] 自动重调机制 - 自动在规定时间内重新调用工具以延续对话 - Cursor 等 IDE 有会话超时时间限制，当超时后在该工具中输入提交后会直接报错，在超时时间内进行自动重新调用可以使会话始终保持活跃，持续等待用户输入新的下一步指令，从而达到一次请求在较长一段时间内仍能完成多次任务的需求
    - [x] ~~好的，代码先保持现状，然后重新调用 interactive_feedback 工具，调用 interactive_feedback 后会有一个窗口，我将在窗口中告诉你下一步指令，请先调用 interactive_feedback 工具~~
    - [x] ~~\n 请回答以上问题或要求。\n 并且注意，除非我主动让你结束，否则不要结束对话，必须回复。回复或反思优化步骤完成后必须重新调用 interactive_feedback 工具拉起反馈窗口来询问我的反馈，因为反馈窗口仅对当前轮次对话有效，旧的窗口已无效，所以每一轮新对话必须重新调用，只有这样才能保证会话连续性，如果你本轮仅仅回复了内容但是没有调用 interactive_feedback 工具询问我的反馈，那么对话将会终止，任务将会失败！所以决不允许只回复内容不调用工具询问反馈，直接在回复中询问是无效的，用户看不到，所以必须重新调用工具在反馈窗口中询问反馈！~~
    - [x] \n 请积极调用 interactive_feedback 工具
    - [x] 请立即调用 interactive_feedback 工具
  - [x] 项目标识显示 - 显示当前项目以用于多窗口时的区分 - 便于在多项目同时开发时快速识别当前操作的项目
- [x] 长时间运行会错误的中断
  - TaskGroup 同步的问题
- [x] web ui 显示代码块渲染不对
  - ~~会有 CORS 的问题~~（已修复：CSP 配置导致内联样式被阻止）
  - 使用`python test.py --port 8080 --verbose --thread-timeout 0`启动测试后，再使用 chrome-devtools mcp 打开<http://0.0.0.0:8080>测试页面，并设置为桌面端查看效果
  - 问题根源：
    1. CSP 配置中 `style-src` 同时包含 `nonce` 和 `'unsafe-inline'`，导致 `'unsafe-inline'` 被忽略
    2. `updateDescriptionDisplay` 函数直接使用 `innerHTML` 而没有调用 `renderMarkdownContent`，导致 `processCodeBlocks` 没有执行
  - 解决方案：
    1. 修改 `web_ui.py`：从 `style-src` 中移除 `nonce`，只保留 `'unsafe-inline'`
    2. 修改 `static/js/multi_task.js`：让 `updateDescriptionDisplay` 调用 `renderMarkdownContent`
  - 结果：代码块渲染完全正常，背景、高亮、工具栏都正确显示
- [x] Web UI 小问题优化
  - [x] `navigator.vibrate` 被阻止警告：已添加用户交互检测，只在用户交互后才调用振动 API
  - [x] MathJax 字体文件 404 错误：已下载 MathJax WOFF 字体文件到本地 `static/js/output/chtml/fonts/woff-v2/`
- [x] 移动端标签栏和标签样式和位置不对
  - 使用 chrome-devtools mcp 打开<http://0.0.0.0:8080>测试页面，并设置为移动端查看效果
  - 问题根源：
    1. CSS 媒体查询中没有定义标签栏的移动端样式，使用了桌面端样式
    2. 字体过小（12.5px）、内边距过大（28px）、宽度不适配
  - 解决方案：
    1. 在 `@media (max-width: 768px)` 添加移动端样式：padding 1rem, font-size 14px, max-width 150px
    2. 在 `@media (max-width: 480px)` 添加小屏幕优化：padding 0.75rem, font-size 13px, max-width 140px
    3. 添加 `margin: 0` 和 `box-sizing: border-box` 防止布局溢出
  - 结果：标签栏布局正确，字体可读，触摸友好
- [x] Bark 通知不对
  - 在 web ui 上，选中`启用 Bark 通知`，然后点击`🧪 测试 Bark 通知`会正常通知
  - 在 web ui 上，未选中`启用 Bark 通知`，然后点击`🧪 测试 Bark 通知`不通知
  - 如果刚开始未在设置文件启用 bark 通知，然后开始运行程序，在程序运行中在 web ui 选中`启用 Bark 通知`后，收到新任务时，不会通知
  - 如果刚开始在设置文件启用 bark 通知，然后开始运行程序，收到新任务时，还是不会通知
  - 问题根源：
    - 测试按钮有独立的通知代码，正常工作
    - 实际任务创建时缺少通知触发代码
    - 用户使用 `test.py` 测试，调用的是 `launch_feedback_ui()`
    - 而我最初只在 `interactive_feedback()` 中添加了通知代码
  - 解决方案：任务添加成功后立即发送通知（使用 `notification_manager.send_notification()`）
- [x] 错误的情况下会返回 text:任务超时
  - 看上去是`async def interactive_feedback(`的
    ```python
    # 使用 MCP 标准 TextContent 格式返回错误
    return [{"type": "text", "text": result["error"]}]
    ```
  - 修改为：请立即调用 interactive_feedback 工具
- [x] `请立即调用 interactive_feedback 工具`和`\n 请积极调用 interactive_feedback 工具`允许在再配置文件内配置
- [x] 在 mcp 实际使用中，接收到新任务，浏览器 console 会新增问题：`main.js:1078 ⚠️ 页面状态不一致，跳过通知（内容页面未显示）`，而且实际上我也没有接收到 bark 通知
- [x] 程序运行中，在 web ui 取消 bark 通知选项（包括修改相关设置），新任务还是会发送 bark 通知
  - 问题根源：`web_ui.py` 作为子进程运行，与主 MCP 服务器进程有独立的 `notification_manager` 实例
  - 解决方案：在 `server.py` 发送通知前调用 `notification_manager.refresh_config_from_file()` 重新加载配置
  - 额外优化：添加线程锁保护、配置缓存、类型验证等
- [x] [12:37:27]info 子 (ai-intervention-agent)/home/xiadengma/.cache/uv/archive-v0/uSqUmOIQfbRzcZdRAyuEF/lib/python3.13/site-packages/task_queue.py:862: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
  - 已修复：将 `datetime.utcnow()` 替换为 `datetime.now(timezone.utc)`
- [x] 页面上深色模式/浅色模式切换按钮无效（包括桌面端和移动端），点击后 console 也无反馈
  - 问题根源：代码引用了 `ThemeManager.toggle()` 但 `ThemeManager` 对象从未定义
  - 解决方案：
    1. 添加 `ThemeManager` 对象（包含 `init`、`getTheme`、`setTheme`、`toggle` 方法）
    2. 添加 CSS 变量系统（`:root` 深色主题 + `[data-theme="light"]` 浅色主题）
    3. 更新主要元素使用 CSS 变量（body、container、header、h1 等）
  - 功能特性：主题保存到 localStorage，跟随系统主题偏好，平滑过渡动画
- [x] 运行后 cursor 会报错：mCP error -32001: Request timed out
  - 说明：这是 Cursor 的内置 MCP 请求超时限制，不是代码问题
  - 原因：`interactive_feedback` 工具设计为长时间等待用户输入，可能超过 Cursor 的超时限制
  - 现有方案：已实现 `auto_resubmit_timeout` 机制，前端倒计时结束后自动重新提交
- [x] cursor 的 mcp 调用日志显示：notification_manager - ERROR - 更新 Bark 提供者失败: 通知提供者不可用
  - 问题根源：`notification_manager.py` 和 `notification_providers.py` 之间存在循环导入
  - 解决方案：在 `_update_bark_provider()` 方法内使用延迟导入（lazy import），避免模块加载时的循环依赖
  - 验证结果：27 个通知相关单元测试全部通过，边界情况（幂等性、并发安全、状态切换）测试通过
- [x] cursor 的 mcp 调用日志显示 FastMCP Banner
  - 说明：这是 FastMCP 的启动 Banner，输出到 stderr，Cursor 显示为 error，实际是正常信息
  - 已修复：在 `mcp.run()` 调用中添加 `show_banner=False` 参数禁用 Banner
  - 生效方式：提交代码到 GitHub 后，清除 uvx 缓存即可
- [x] cursor 的 mcp 调用日志显示：2025-12-05 13:07:14.937 [info] Found 1 tools, 0 prompts, and 0 resources
      2025-12-05 13:07:17.745 [error] /home/xiadengma/.cache/uv/archive-v0/uSqUmOIQfbRzcZdRAyuEF/lib/python3.13/site-packages/task_queue.py:862: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
      now = datetime.utcnow() # 使用 UTC 时间，与 completed_at 保持一致
  - 已修复：本地代码已将 `datetime.utcnow()` 替换为 `datetime.now(timezone.utc)`
  - 注意：日志路径 `/home/xiadengma/.cache/uv/archive-v0/...` 显示这是 uvx 缓存的旧版本
  - 生效方式：提交代码到 GitHub 后，清除 uvx 缓存或等待缓存过期即可生效
- [x] cursor 的 mcp 调用日志显示：2025-12-05 13:11:56.575 [error] Client error for command Received a response for an unknown message ID: {"jsonrpc":"2.0","id":13,"error":{"code":0,"message":"Request cancelled"}}
  - 说明：这是 Cursor 内部消息，表示请求被取消但服务器仍返回了响应，属于正常行为，不是代码问题
- [x] cursor 的 mcp 调用日志显示：2025-12-05 13:13:09.025 [error] 2025-12-05 13:13:09,024 - notification_manager - ERROR - 处理通知事件失败: notification_1764911579024_140187607365488 - 1 (of 3) futures unfinished
  - 已优化：使用 try-except 捕获 TimeoutError，记录警告而非错误，并取消未完成任务
- [x] cursor 的 mcp 调用日志显示：2025-12-05 13:13:09.036 [error] 2025-12-05 13:13:09,035 - notification_providers - ERROR - Bark 通知发送超时: notification_1764911579024_140187607365488
  - 说明：Bark 网络超时是正常现象，服务器响应慢或网络问题，不影响核心功能
- [x] cursor 的 mcp 调用日志显示 MCP 启动过程中的各种消息

  - "No server info found"：Cursor 在 uvx 启动完成前尝试连接，属于正常启动时序，最终会成功连接
  - "更新 Bark 提供者失败: 通知提供者不可用"：uvx 缓存的旧版本代码问题，本地已修复，提交后清除缓存即可
  - FastMCP banner：FastMCP 默认输出到 stderr，Cursor 将其显示为 error，实际是正常信息
  - DeprecationWarning：uvx 缓存的旧版本问题，本地已修复为 `datetime.now(timezone.utc)`
  - 生效方式：提交代码到 GitHub 后，运行 `rm -rf ~/.cache/uv/archive-v0/` 清除缓存，重启 Cursor MCP 即可

- [x] 当前有很多内联脚本，需要以合适的方式独立出来
- [x] 调用时出现`Error handling CallToolRequest: McpError: MCP error -32001: Request timed out`，导致调用者的调用整个失败，但是服务还是在正常运行【已修复】

  0. 当前是在 mcphub 内管理多个 MCP，其中包括 ai-intervention-agent，以及其他一些 mcp，ai-intervention-agent 的 mcp 地址是`http://0.0.0.0:20004`，通过 streamable HTTP 方式进行调用
  1. 测试 1：`方式二：开发模式（本地使用）`：进行连续调用测试，测试 3 次（倒计时反馈设置为 240s）发现 2 次成功，1 次失败，修改为超时 200s 后，测试 11 次（倒计时反馈设置为 200s）发现 11 次成功，0 次失败,再修改为超时 240s 后，测试 5 次（倒计时反馈设置为 240s）发现 5 次成功，0 次失败
  2. 测试 2：`方式一：uvx 直接使用（推荐）`：进行连续调用测试，测试 6 次（倒计时反馈设置为 240s），发现 5 次成功，1 次失败，测试 5 次（倒计时反馈设置为 290s），发现 3 次成功，2 次失败（分别在 230s 和 280s 的时候报错）
     ```
     [16:08:11]info 主 (7754)Handling CallToolRequest for tool: {"name":"ai-intervention-agent-interactive_feedback","arguments":{"message":"## BBB 很好！交互功能正常工作 ✅\n\n 现在让我问你一个实际的问题：\n\n**你最常使用哪种编程语言？**\n\n 请选择或输入你的答案：","predefined_options":["Python","JavaScript/TypeScript","Java","C/C++","Go","Rust","其他语言"]}}
     [16:10:18]info 主 (7754)Global SSE/MCP endpoint access - no user context
     [16:10:18]info 主 (7754)Handling MCP other request
     [16:13:11]error 主 (7754)Error handling CallToolRequest: McpError: MCP error -32001: Request timed out
     ```

  - 我发现` McpError: MCP error -32001: Request timed out`都是在实际时间超过 300s 后才报错，虽然我软件里面设置了，但是由于软件启动是需要时间的，所以第一次启用或中断后重新启用，会存在发送请求到最终结束请求的时间超过我们设定时间的情况。
  - 还发现会有页面时间不正确的情况，导致没有正确达到超时时间，导致报错。
    ```
    [17:00:02]info主 (7754)Handling CallToolRequest for tool: {"name":"ai-intervention-agent-local-interactive_feedback","arguments":{"message":"## 兄弟抱一下，偶尔爷爷也有\n\n**你最常使用哪种编程语言？**\n\n请选择或输入你的答案：","predefined_options":["Python","JavaScript/TypeScript","Java","C/C++","Go","Rust","其他语言"]}}
    [17:03:00]info主 (7754)Global SSE/MCP endpoint access - no user context
    [17:03:00]info主 (7754)Handling MCP other request
    [17:05:02]error主 (7754)Error handling CallToolRequest: McpError: MCP error -32001: Request timed out
    ```
    我记录的时候是 17:05:22，但是页面倒计时显示还有 180s，我是在页面启动后，切换到别的页面去使用了，然后等过了一段时间我回来发现超时报错了，导致我以为我设置的超时时间没有生效。当我刷新页面后，它倒计时显示时间为 0，然后变成-1，这时候它才意识到程序已经中断。
  - 正确的实现可以这样理解：把真正裁决“这次调用是否超时”的逻辑全部放在后端，并且按 MCPHub 固定 300 秒的硬超时上限预留安全余量，例如只允许业务逻辑在 260 秒内运行，然后用单调时间（比如 Python 的 time.monotonic 这类不会受系统时间调整影响的计时源）来记录开始时刻和截止时刻，每次循环都根据“当前单调时间和截止时间的差值”判断是否超时；一旦到点，就由后端主动返回“本次交互已超时”的业务结果并结束调用，避免让请求自然拖到 300 秒被 MCPHub 直接掐断；与此同时，前端只负责展示倒计时和给用户做提示，所显示的剩余时间应根据后端返回的“服务器当前时间 + 截止时间”推算，不自行拍脑袋计时，这样无论切换标签页、刷新页面还是本机时间被改动，前端看到的状态都能与后端真实的超时状态保持一致。

- [x] 还出现了，选中选项直接点击提交，显示没有输入不让提交的问题【已修复】
- [x] Bark 通知发送失败，我配置是正确的
  - bark 服务器的问题，发送成功但是没有通知
- [x] 添加配套插件：参考：https://github.com/fhyfhy17/panel-feedback
- [x] 修复图片功能：参考：https://github.com/ChromeDevTools/chrome-devtools-mcp 的 `take_screenshot`工具
  1. 首先，上传图片页面上没有正确预览
  2. 其次，返回图片到 mcp 调用方也不正确
  3. 过大的图片应该压缩后返回，而不是直接返回原始图片
- [x] 我现在可以粘贴图片吗？我上传图片后会有显示吗？
- [x] 配置热更新：当我修改配置文件/在 web ui 上修改配置后，程序应该自动重新加载配置，而不是需要手动重启程序
- [ ] 请你深度思考和深度测试，我想知道我这个项目还有什么缺少的/可以改进的/可以优化的/可以测试的。
- [x] 检查配置热更新功能是否正确：比如我修改/home/xiadengma/.config/ai-intervention-agent/config.jsonc 的反馈配置那部分，不重启程序，程序返回会更新吗？如果我修改 bark_enabled，那么 web ui 里面设置页面会更新吗？我允许你修改 8080 端口为 8082 或其他来测试，除了 8081。
- 请使用 uv、ruff、ty 和 pyproject.toml 更新我的项目；以及 test.py 设置--port 8080，那么里面全部都使用 8080 端口。
- 仔细分析后修复问题：使用 uv run python test.py --port 8080 --verbose --thread-timeout 0，第一次反馈虽然是在 8080 端口，但是`🔄 更新页面内容...`后的下面反馈现在是根据 config.jsonc 来的
- 界面截图：包括桌面端和移动端，包括深色模式和浅色模式，包括无有效内容页面、有内容页面（uv run python test.py --port 8080 --verbose --thread-timeout 0 的第一个页面）

# 已完成的优化项目

- [x] Bark 通知同步修复 - 跨进程配置同步问题已解决
- [x] 单元测试套件 - 140+ 个测试用例，覆盖核心模块
- [x] 测试覆盖率提升
  - notification_manager: 63.24%
  - config_manager: 36.96%
  - file_validator: 89.82%
  - task_queue: 81.58%
- [x] FileWatcher 优化 - 使用 Event.wait() 支持优雅关闭
- [x] 配置验证增强 - 边界检查、类型转换、默认值处理
- [x] 代码质量优化 - 类型提示、日志分级、文档生成
- [x] 前端增强 - 键盘快捷键、主题切换、响应式改进
- [x] 静态资源优化 - JS/CSS 压缩和合并
- [x] 性能优化 - 请求去抖动、图片懒加载

# WorkFlow

- 使用 uv run python test.py --port 8080 --verbose --thread-timeout 0 在且只在 8080 端口启动测试脚本，并且使用 chrome-devtools mcp 打开<http://0.0.0.0:8080>测试页面（尽量使用文字方法去读取网页内容，而不是截图），仔细分析并考虑边界情况，检查任务是否完整的完成
- 我是使用 python 脚本生成 min 文件的

# List
