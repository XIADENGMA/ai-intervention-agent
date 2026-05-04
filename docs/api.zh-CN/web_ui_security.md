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
