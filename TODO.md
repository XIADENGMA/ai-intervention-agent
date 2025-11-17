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
- [ ] 更新 README，英文、中文版本
  - 参考：https://github.com/Minidoracat/mcp-feedback-enhanced/blob/main/README.zh-CN.md
- [ ] 重构网页主题
  - 适配深色主题、浅色主题
  - 适配中文、英文
  - 在`设置`的最下面的`关于`中显示版本信息、github 地址<https://github.com/XIADENGMA/ai-intervention-agent>等
- [ ] 优化 prompt
- [x] 研究是否可以打包成 vscode 插件
  - [ ] 在侧边栏显示（基础功能完成），但是现在切换侧边栏标签页回来会有一段时间空白需要等待
  - [ ] 在底栏显示 MCP 服务状态
- [ ] 复制、粘贴优化，特别是在 ios 平台上
- [ ] 全平台支持、发布到 uvx pypi 平台
- [ ] github action（设想）
  - 自动发布
    - 自动化测试
    - 自动化 pr
- 修复 uvx 模式图片反馈问题：`Error calling tool 'interactive_feedback': Unable to serialize unknown type: <class 'fastmcp.utilities.types.Image'>`，而本地测试正常
  - 改造这条工具链，让它在任何对外返回、跨工具传递的地方，都只传 MCP 协议定义的` ImageContent`（本质是一个包含 `type/data/mimeType` 字段的纯 dict），彻底移除 `fastmcp.utilities.types.Image` 这种类对象。
- [x] 参考<https://github.com/Pursue-LLL/interactive-feedback-mcp>添加功能

  1. 新增 task_id 参数，帮助用户区分不同任务
  2. 自动在规定时间内重新调用工具以延续对话 - Cursor 等 IDE 有会话超时时间限制，当超时后在该工具中输入提交后会直接报错，在超时时间内进行自动重新调用可以使会话始终保持活跃，持续等待用户输入新的下一步指令，从而达到一次请求在较长一段时间内仍能完成多次任务的需求
     - 好的，代码先保持现状，然后重新调用 interactive_feedback 工具，调用 interactive_feedback 后会有一个窗口，我将在窗口中告诉你下一步指令，请先调用 interactive_feedback 工具
     - \n 请回答以上问题或要求。\n 并且注意，除非我主动让你结束，否则不要结束对话，必须回复。回复或反思优化步骤完成后必须重新调用 interactive_feedback 工具拉起反馈窗口来询问我的反馈，因为反馈窗口仅对当前轮次对话有效，旧的窗口已无效，所以每一轮新对话必须重新调用，只有这样才能保证会话连续性，如果你本轮仅仅回复了内容但是没有调用 interactive_feedback 工具询问我的反馈，那么对话将会终止，任务将会失败！所以决不允许只回复内容不调用工具询问反馈，直接在回复中询问是无效的，用户看不到，所以必须重新调用工具在反馈窗口中询问反馈！
  3. 显示当前项目以用于多窗口时的区分 - 便于在多项目同时开发时快速识别当前操作的项目

- 修复插件
  1. 在 vscode output 的日志问题，修改为正常的
  2. 插件呼吸灯应该根据服务器连接状态更新颜色
  3. 支持多标签页和倒计时圆环显示
  4. 不要每次点开插件页面都要重新加载
  5. 支持 markdown 显示
  6. 在底栏显示 MCP 服务状态

# List
