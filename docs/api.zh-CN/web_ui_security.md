# web_ui_security

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/web_ui_security.md`](../api/web_ui_security.md)

安全策略 Mixin — 从 WebFeedbackUI 提取。

提供 IP 访问控制、CSP 安全头注入、网络安全配置加载等方法，
由 WebFeedbackUI 通过 MRO 继承。

## 函数

### `_normalize_trusted_host_candidate(value: object) -> str | None`

Return a Flask ``TRUSTED_HOSTS`` exact host value, or ``None``.

The input may be a hostname, IP literal, host:port, bracketed IPv6 literal,
or an absolute URL such as ``https://ai.example.com:8443``. Wildcard bind
addresses are excluded because they are listen addresses, not request
authority values.

### `build_trusted_hosts() -> list[str]`

Build the concrete host allowlist for Flask ``TRUSTED_HOSTS``.

### `_may_change_state(method: str, path: str) -> bool`

Does a request with this method and path run a handler that changes state?

``OPTIONS`` is answered by Flask / CORS itself and never reaches a view; every
other method except GET / HEAD is a write; GET / HEAD count only for the paths
in ``_STATE_CONSUMING_GET_PATHS``.

### `_origin_parts(value: str) -> tuple[str, str] | None`

``(scheme, host[:port])`` of an origin or base URL; ``None`` if it is not an http(s) origin.

The host is lower-cased and the scheme's default port dropped, so
``http://Example.com:80`` and ``http://example.com`` compare equal. ``null``
(a sandboxed frame, a cross-origin redirect chain) and non-http schemes such
as ``vscode-webview://`` give ``None``.

### `_origin_is_allowed(origin: str, host: str, allowed_origins: Collection[str | re.Pattern[str]]) -> bool`

Is ``origin`` the Web UI's own origin (same ``Host``) or in ``allowed_origins``?

### `is_cross_origin_write() -> bool`

Should this request be refused because a page of another origin caused it? (R787)

A page on any web site can make the visitor's browser send a ``POST`` to
``http://127.0.0.1:<port>``: a form with ``enctype="multipart/form-data"`` or
``application/x-www-form-urlencoded`` needs no CORS preflight, and CORS only
decides whether the page may *read* the answer, not whether the server acts on
the request. ``/api/submit`` takes exactly those two body types, so such a
page could answer the agent's question in the user's name.

Requests that cannot change state (``GET`` / ``HEAD`` / ``OPTIONS``, except the
read-and-clear ``GET /api/feedback``) are never refused. For the others, in
this order:

* ``Sec-Fetch-Site: same-origin`` / ``none`` is the browser's own statement
  (a page cannot set it) that the request came from this very origin: allowed,
  whatever a proxy did to ``Host``.
* Neither ``Origin`` nor ``Sec-Fetch-Site``: not a browser (the MCP server's
  httpx, ``curl``, Node ``fetch`` in the VS Code extension host): allowed.
* ``Sec-Fetch-Site`` without ``Origin``: a browser calling a request
  cross-site, with nothing to identify it by: refused.
* Otherwise the ``Origin`` must be this server's own (same authority as
  ``Host``) or one of ``allowed_origins`` (the CORS allow-list: the page's own
  ``localhost`` / ``127.0.0.1`` origins and the VS Code webview). ``null`` is
  refused.

### `_bracketed_address(value: str) -> IPv4Address | IPv6Address | None`

The address inside a leading ``[...]``; anything after ``]`` is ignored.

### `_host_is_trusted_with_ipv6(original: Callable[..., bool]) -> Callable[..., bool]`

Wrap Werkzeug's ``host_is_trusted`` so a bracketed IPv6 entry can match.

Werkzeug 3.1.9 keeps a ``Host`` header such as ``[::1]:8080`` in one piece
but still cuts every allowlist entry at its first colon, so a ``[::1]`` entry
turns into ``[`` and nothing matches it (pallets/werkzeug#3312: fixed on
main, not released yet). The wrapper only adds a way to be trusted: it
returns what Werkzeug returns, and when that is a refusal it accepts a
``Host`` value that Werkzeug itself validates, that is a bracketed IPv6
literal, and that names the same address as a bracketed entry of the list.

### `ensure_ipv6_trusted_hosts_support() -> bool`

Make ``TRUSTED_HOSTS`` usable for bracketed IPv6 literals; ``True`` if patched.

Probes Werkzeug with the loopback entry this module always trusts and wraps
``werkzeug.sansio.utils.host_is_trusted`` only when the probe is refused, so
a release that matches (or that fixed pallets/werkzeug#3312) is left alone,
and so is our own wrapper: calling this again is a no-op. A helper that is
missing or fails the probe is left alone too.

### `get_config() -> Any`

Lazy proxy kept patchable for tests and security helpers.

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
