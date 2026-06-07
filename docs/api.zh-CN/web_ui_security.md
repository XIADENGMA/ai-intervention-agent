# web_ui_security

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/web_ui_security.md`](../api/web_ui_security.md)

安全策略 Mixin — 从 WebFeedbackUI 提取。

提供 IP 访问控制、CSP 安全头注入、网络安全配置加载等方法，
由 WebFeedbackUI 通过 MRO 继承。

## 类

### `class SecurityMixin`

IP 访问控制 + HTTP 安全头 + CSP nonce 管理。

#### 方法

##### `setup_security_headers(self) -> None`

注册 before_request / after_request 钩子：IP 访问控制 + 安全头注入。

R306: 同时注册 ``context_processor``, 让所有 ``render_template()``
调用自动拿到 ``csp_nonce`` 变量, 不再需要每个 route 手动传 ctx。
历史 bug: ``offline.html`` 通过 ``render_template("offline.html")``
渲染时没传 ``csp_nonce``, Jinja2 ``{{ csp_nonce }}`` 默认渲染为空
字符串, 浏览器 CSP 阻止其 ``<script nonce="">`` 执行, "Retry"
按钮永不工作。改用 context_processor 后, 任何模板都自动获得当前
请求的 nonce, 防同类 bug 再生。
