# TODO

- [x] 输入框允许拖入/粘贴/上传图片（允许 base64），并以合适的方式显示在输入框上方
  - 并没有正确传入到 cursor 或其他 ide -> 修改为不使用 base64，使用 fastmcp image 的形式
- [x] 允许接收到反馈时以合适的方式通知（声音/系统通知/bark 通知……
- [ ] 更换页面上字体为版权合适字体
- [x] 全平台快捷键支持
- [x] 统一使用配置文件，移除环境变量依赖
- [x] 支持 JSONC 格式配置文件（带注释的 JSON）
- [x] 系统通知修复`import plyer`
- [ ] 页面显示的 markdown 样式优化
- [ ] 更新 README，英文、中文版本
  - 参考：https://github.com/Minidoracat/mcp-feedback-enhanced/blob/main/README.zh-CN.md
- [ ] 重构主题
  - 适配深色主题、浅色主题
  - 适配中文、英文
  - 在合适的地方显示版本信息、github 地址等
- [ ] 优化 prompt
- [ ] 研究是否可以打包成 vscode 插件【在侧边栏显示？】【在底栏显示状态】
- [ ] 复制、粘贴优化，特别是在 ios 平台上
- [ ] 全平台支持、发布到 uvx pypi 平台
- [ ] github action（设想）
  - 自动发布
  - 自动化测试
  - 自动化 pr
- 修复 uvx 模式图片反馈问题：`Error calling tool 'interactive_feedback': Unable to serialize unknown type: <class 'fastmcp.utilities.types.Image'>`，而本地测试正常

# List
