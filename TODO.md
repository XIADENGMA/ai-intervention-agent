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
- [ ] 重构网页主题
  - 适配深色主题、浅色主题
  - 适配中文、英文
  - 在合适的地方显示版本信息、github 地址等
- [ ] 优化 prompt
- [x] 研究是否可以打包成 vscode 插件
  - 在侧边栏显示（基础功能完成），但是现在切换侧边栏标签页回来会有一段时间空白需要等待
  - 在底栏显示 MCP 服务状态
- [ ] 复制、粘贴优化，特别是在 ios 平台上
- [ ] 全平台支持、发布到 uvx pypi 平台
- [ ] github action（设想）
  - 自动发布
  - 自动化测试
  - 自动化 pr
- 修复 uvx 模式图片反馈问题：`Error calling tool 'interactive_feedback': Unable to serialize unknown type: <class 'fastmcp.utilities.types.Image'>`，而本地测试正常
  - 问题在于 uvx 会强制序列化，而 FastMCP 的 Image 无法序列化

# List

## WebSocket vs HTTP 方案对比

### 当前架构 (HTTP + 轮询)

**技术栈：**

- 后端：Flask + requests
- 前端：JavaScript fetch API
- 通信：HTTP POST/GET + 轮询机制

**工作流程：**

1. MCP 服务启动 Flask Web 服务器
2. 前端通过`/api/config`轮询获取配置和内容状态
3. 用户提交反馈通过`/api/submit`发送
4. 后端通过`/api/feedback`轮询检查反馈结果
5. 使用`has_content`状态变化检测用户操作

**优势：**

- ✅ 实现简单，易于调试
- ✅ HTTP 协议成熟稳定，代理友好
- ✅ 无连接状态管理，容错性好
- ✅ 支持文件上传（multipart/form-data）
- ✅ 现有安全机制完善（CSP、速率限制、IP 过滤）
- ✅ 容易通过 SSH 端口转发使用

**劣势：**

- ❌ 轮询带来额外网络开销（每 2 秒一次请求）
- ❌ 延迟较高（2-30 秒检测间隔）
- ❌ 服务器资源消耗（持续轮询检查）
- ❌ 网络流量浪费（大量空的轮询请求）

---

### WebSocket 方案

**技术栈建议：**

- 后端：`websockets` (python-websockets/websockets)
- 前端：原生 WebSocket API
- 通信：全双工实时通信

**潜在架构：**

```python
# 服务器端
import asyncio
from websockets.asyncio.server import serve, broadcast

CONNECTIONS = set()

async def handler(websocket):
    CONNECTIONS.add(websocket)
    try:
        async for message in websocket:
            # 处理用户反馈
            feedback_data = json.loads(message)
            # 广播给MCP服务
            broadcast(CONNECTIONS, json.dumps(feedback_data))
    finally:
        CONNECTIONS.remove(websocket)

async def main():
    async with serve(handler, "localhost", 8765) as server:
        await server.serve_forever()
```

**优势：**

- ✅ **实时双向通信** - 无需轮询，即时响应
- ✅ **网络效率高** - 避免无意义的轮询请求
- ✅ **延迟极低** - 消息即时传达（< 100ms）
- ✅ **服务器资源节省** - 减少 HTTP 请求处理开销
- ✅ **更好的用户体验** - 实时状态更新，响应更快
- ✅ **支持广播** - 可同时通知多个连接的客户端

**劣势：**

- ❌ **实现复杂度高** - 需要连接管理、心跳检测、重连机制
- ❌ **状态管理复杂** - 连接断开、异常恢复处理
- ❌ **代理兼容性** - 某些企业代理可能阻止 WebSocket
- ❌ **文件上传复杂** - 需要 Base64 编码或分块传输
- ❌ **调试困难** - 连接状态、消息流难以跟踪
- ❌ **安全考虑** - 需重新实现认证、授权、速率限制
- ❌ **SSH 端口转发兼容性** - 某些 SSH 版本对 WebSocket 支持不佳

---

### 详细技术对比

| 方面           | HTTP 轮询        | WebSocket        |
| -------------- | ---------------- | ---------------- |
| **延迟**       | 2-30 秒          | < 100ms          |
| **网络开销**   | 高（频繁轮询）   | 低（仅实际数据） |
| **服务器负载** | 中等（轮询请求） | 低（连接保持）   |
| **实现难度**   | 简单             | 复杂             |
| **调试便利性** | 容易             | 困难             |
| **代理兼容性** | 极好             | 一般             |
| **移动端兼容** | 极好             | 好               |
| **文件上传**   | 原生支持         | 需特殊处理       |
| **连接稳定性** | 无状态，稳定     | 有状态，需维护   |
| **安全实现**   | 成熟完善         | 需重新设计       |

---

### 使用场景分析

**适合 HTTP 轮询的场景：**

- 用户交互不频繁（当前 AI 反馈场景）
- 对延迟要求不高（几秒内响应可接受）
- 需要通过各种网络环境（企业代理、SSH 转发）
- 要求高稳定性和容错性
- 开发团队经验有限，追求简单可靠

**适合 WebSocket 的场景：**

- 需要实时响应（游戏、聊天、实时协作）
- 高频双向通信
- 对延迟要求极高（< 1 秒）
- 需要服务器主动推送
- 有经验的开发团队，能处理复杂性

---

### 建议

**对于当前 AI Intervention Agent 项目：**

建议**保持 HTTP 轮询方案**，理由：

1. **符合使用场景** - AI 反馈不需要毫秒级响应
2. **稳定性优先** - 工具类软件需要高可靠性
3. **网络兼容性** - SSH 端口转发、企业代理环境友好
4. **维护成本低** - 现有方案已经成熟稳定
5. **渐进优化** - 可通过减少轮询间隔、智能轮询等方式改善性能

**可选的改进方案：**

- 实现智能轮询（有活动时频率更高）
- 使用 Server-Sent Events (SSE) 作为中间方案
- 在特定场景下提供 WebSocket 作为可选项

除非项目需求明确要求实时性（如实时协作编辑），否则当前 HTTP 方案更适合工具类软件的稳定性要求。
