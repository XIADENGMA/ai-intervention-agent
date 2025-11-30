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
- [ ] 页面显示的 markdown 样式优化
  - 现在只显示基础效果
- [ ] 更新 README，英文、中文版本
  - 参考：https://github.com/Minidoracat/mcp-feedback-enhanced/blob/main/README.zh-CN.md
- [x] 重构网页主题
  - [x] 适配深色主题、浅色主题 - 使用 CSS 变量实现主题切换
  - [ ] 适配中文、英文
  - [ ] 在`设置`的最下面的`关于`中显示版本信息、github 地址<https://github.com/XIADENGMA/ai-intervention-agent>等
- [ ] 优化 prompt
- [x] 研究是否可以打包成 vscode 插件
  - [x] 在侧边栏显示（基础功能完成），但是现在切换侧边栏标签页回来会有一段时间空白需要等待
  - [ ] ~~在底栏显示 MCP 服务状态~~
- [ ] 复制、粘贴优化，特别是在 ios 平台上
- [ ] 全平台支持、发布到 uvx pypi 平台
- [ ] github action（设想）
  - 自动发布
    - 自动化测试
    - 自动化 pr
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

# 已完成的优化项目

- [x] **Bark 通知同步修复** - 跨进程配置同步问题已解决
- [x] **单元测试套件** - 140+ 个测试用例，覆盖核心模块
- [x] **测试覆盖率提升**
  - notification_manager: 63.24%
  - config_manager: 36.96%
  - file_validator: 89.82%
  - task_queue: 81.58%
- [x] **FileWatcher 优化** - 使用 Event.wait() 支持优雅关闭
- [x] **配置验证增强** - 边界检查、类型转换、默认值处理
- [x] **代码质量优化** - 类型提示、日志分级、文档生成
- [x] **前端增强** - 键盘快捷键、主题切换、响应式改进
- [x] **静态资源优化** - JS/CSS 压缩和合并
- [x] **性能优化** - 请求去抖动、图片懒加载

# WorkFlow

- 使用 uv 在 8080 端口启动测试脚本，并且使用 chrome-devtools mcp 打开<http://0.0.0.0:8080>测试页面，仔细分析并考虑边界情况，检查任务是否完整的完成

# List
