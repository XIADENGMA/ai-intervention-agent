"""R54-B：``LogSanitizer`` 扩展 PII / API key 脱敏覆盖。

锁定目标：让 ``enhanced_logging.LogSanitizer`` 的脱敏正则集覆盖现代主流
LLM / 云服务 vendor 的 API key 形态，同时不引入误伤普通日志的退路。

为什么单独做这一轮：

- 原始正则（R51-C 时）只覆盖 ``sk-XXX`` (OpenAI 老格式) / ``xoxb-`` /
  ``ghp_``，已经不够用——
  - OpenAI 在 2024 推出工程级 key ``sk-proj-XXX``、Anthropic 用
    ``sk-ant-XXX``，两者都在 ``sk-`` 后多了一段 ``proj-`` / ``ant-``，老
    regex 的字符集 ``[A-Za-z0-9]`` 不收 dash → 在 ``sk-proj-...`` 处只 match
    到 ``sk-proj`` 4 个字符就失败、整条 key 漏脱敏。
  - 公司日志里同样会出现 AWS / GCP / GitHub server token / Slack user
    token / HuggingFace / Stripe / JWT 等形态。
- 一旦泄漏一次就需要全 vendor 走轮换流程，运维成本远高于"提前覆盖"。
- 测试组织：每个 vendor 独立 case，方便 git log 直接读懂 "本轮加了哪些
  vendor 的覆盖"。

不锁定的边界（明确不收，避免误伤）：

- Bearer header 里的 token（很多合法日志含 ``Bearer xxx``，宽 regex 必伤）。
- 单段 base64（无 ``eyJ.<seg>.<seg>`` 形态的，可能是合法 image / hash）。
- 短 hex（< 16 char）—— 太短随机字符串容易跟 commit hash / uuid 撞误伤。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from enhanced_logging import LogSanitizer

REDACTED = "***REDACTED***"


class TestExistingPatternsStillCovered(unittest.TestCase):
    """既有覆盖（R51-C 之前）必须不退化。"""

    def setUp(self) -> None:
        self.s = LogSanitizer()

    def test_password_eq_value(self) -> None:
        self.assertNotIn(
            "super_secret_value", self.s.sanitize("password=super_secret_value")
        )
        self.assertIn(REDACTED, self.s.sanitize("password=super_secret_value"))

    def test_passwd_field(self) -> None:
        self.assertIn(REDACTED, self.s.sanitize("passwd=hunter22hunter22"))

    def test_secret_key_field(self) -> None:
        self.assertIn(REDACTED, self.s.sanitize("secret_key=ABCDEFGH12345678"))

    def test_private_key_field(self) -> None:
        self.assertIn(REDACTED, self.s.sanitize("private_key=ABCDEFGH12345678"))

    def test_openai_legacy_sk(self) -> None:
        # 老格式：sk- 后无 dash，字母数字 32+
        token = "sk-" + "A" * 40
        self.assertIn(REDACTED, self.s.sanitize(f"key={token}"))

    def test_slack_xoxb(self) -> None:
        token = "xoxb-" + "1" * 60
        self.assertIn(REDACTED, self.s.sanitize(f"slack: {token}"))

    def test_github_pat(self) -> None:
        token = "ghp_" + "A" * 36
        self.assertIn(REDACTED, self.s.sanitize(f"GH={token}"))


# ============================================================================
# 新增覆盖（R54-B）
# ============================================================================


class TestOpenAIProjectKey(unittest.TestCase):
    """``sk-proj-...`` 必须被脱敏（修复老 regex 在 dash 处停的 bug）。"""

    def setUp(self) -> None:
        self.s = LogSanitizer()

    def test_sk_proj_redacted(self) -> None:
        # OpenAI 工程级 key：sk-proj- 后通常 ≥ 40 chars，含 _ / -
        token = "sk-proj-" + "A1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6Q7R8S9T0"
        out = self.s.sanitize(f"OPENAI={token}")
        self.assertNotIn(token, out)
        self.assertIn(REDACTED, out)

    def test_sk_proj_with_underscores(self) -> None:
        token = "sk-proj-A1B2C3_4E5F6G_7H8I9J0K1L2M3N4O5P6Q7R8S9"
        out = self.s.sanitize(f"key={token}")
        self.assertNotIn(token, out)


class TestAnthropicKey(unittest.TestCase):
    """``sk-ant-...`` 必须被脱敏。"""

    def setUp(self) -> None:
        self.s = LogSanitizer()

    def test_sk_ant_redacted(self) -> None:
        token = "sk-ant-api03-" + "X" * 50
        out = self.s.sanitize(f"ANTHROPIC_API_KEY={token}")
        self.assertNotIn(token, out)
        self.assertIn(REDACTED, out)


class TestAllGitHubTokenForms(unittest.TestCase):
    """GitHub 五种 token 前缀：ghp/ghs/gho/ghu/ghr。"""

    def setUp(self) -> None:
        self.s = LogSanitizer()

    def test_ghs_server_token(self) -> None:
        token = "ghs_" + "B" * 36
        self.assertIn(REDACTED, self.s.sanitize(f"server token={token}"))

    def test_gho_oauth_token(self) -> None:
        token = "gho_" + "C" * 36
        self.assertIn(REDACTED, self.s.sanitize(f"oauth={token}"))

    def test_ghu_user_to_server(self) -> None:
        token = "ghu_" + "D" * 36
        self.assertIn(REDACTED, self.s.sanitize(f"u2s={token}"))

    def test_ghr_refresh_token(self) -> None:
        token = "ghr_" + "E" * 36
        self.assertIn(REDACTED, self.s.sanitize(f"refresh={token}"))


class TestSlackUserToken(unittest.TestCase):
    """新增 ``xoxp-`` (user) 覆盖。"""

    def setUp(self) -> None:
        self.s = LogSanitizer()

    def test_xoxp_user_redacted(self) -> None:
        token = "xoxp-" + "9" * 60
        self.assertIn(REDACTED, self.s.sanitize(f"slack user={token}"))


class TestAWSAccessKeyID(unittest.TestCase):
    """AWS Access Key ID 形态：AKIA + 16 大写字母数字。"""

    def setUp(self) -> None:
        self.s = LogSanitizer()

    def test_akia_redacted(self) -> None:
        token = "AKIAIOSFODNN7EXAMPLE"
        out = self.s.sanitize(f"aws_access_key_id={token}")
        self.assertNotIn(token, out)
        self.assertIn(REDACTED, out)


class TestGoogleAPIKey(unittest.TestCase):
    """Google / Firebase / Gemini API key：``AIza`` + 35 char。"""

    def setUp(self) -> None:
        self.s = LogSanitizer()

    def test_aiza_redacted(self) -> None:
        token = "AIza" + "X" * 35
        out = self.s.sanitize(f"API_KEY={token}")
        self.assertNotIn(token, out)
        self.assertIn(REDACTED, out)


class TestHuggingFaceToken(unittest.TestCase):
    """HuggingFace token：``hf_`` + 34+ char。"""

    def setUp(self) -> None:
        self.s = LogSanitizer()

    def test_hf_redacted(self) -> None:
        token = "hf_" + "Q" * 37
        out = self.s.sanitize(f"HF_TOKEN={token}")
        self.assertNotIn(token, out)


class TestStripeKey(unittest.TestCase):
    """Stripe live / test publishable / secret keys。"""

    def setUp(self) -> None:
        self.s = LogSanitizer()

    def test_sk_live_redacted(self) -> None:
        token = "sk_live_" + "A" * 24
        out = self.s.sanitize(f"STRIPE_KEY={token}")
        self.assertNotIn(token, out)

    def test_pk_test_redacted(self) -> None:
        token = "pk_test_" + "B" * 30
        out = self.s.sanitize(f"K={token}")
        self.assertNotIn(token, out)


class TestURLBasicAuth(unittest.TestCase):
    """URL 内 basic auth 的密码段必须脱敏，username 和 host 留下。"""

    def setUp(self) -> None:
        self.s = LogSanitizer()

    def test_password_in_https_url_is_redacted_keep_username(self) -> None:
        url = "https://alice:s3cr3tpass@db.example.com/path"
        out = self.s.sanitize(f"connecting to {url}")
        self.assertNotIn("s3cr3tpass", out)
        # username 应保留——便于运维定位是哪个账号在 leak
        self.assertIn("alice", out)
        # host 应保留
        self.assertIn("db.example.com", out)
        # 占位符必须出现在 user:host 之间
        self.assertIn("alice:***REDACTED***@", out)

    def test_password_in_http_url_is_redacted(self) -> None:
        url = "http://bob:hunter22@svc/endpoint"
        out = self.s.sanitize(url)
        self.assertNotIn("hunter22", out)
        self.assertIn("bob:***REDACTED***@", out)


class TestJWT(unittest.TestCase):
    """JWT：必须 eyJ 开头 + 三段。"""

    def setUp(self) -> None:
        self.s = LogSanitizer()

    def test_jwt_redacted(self) -> None:
        jwt = (
            "eyJhbGciOiJIUzI1NiJ9."
            "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
            "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        )
        out = self.s.sanitize(f"Authorization: Bearer {jwt}")
        self.assertNotIn(jwt, out)
        self.assertIn(REDACTED, out)


class TestNoFalsePositives(unittest.TestCase):
    """合法 / 无害文本不应被误脱敏。"""

    def setUp(self) -> None:
        self.s = LogSanitizer()

    def test_normal_message(self) -> None:
        msg = "Server started on port 8080 with 4 workers"
        self.assertEqual(self.s.sanitize(msg), msg)

    def test_short_sk_word_not_redacted(self) -> None:
        # ``sk-foo`` 应该不被认作 key——长度 < 24 char，正则不收
        msg = "Skip sk-foo and continue"
        self.assertEqual(self.s.sanitize(msg), msg)

    def test_commit_hash_not_redacted(self) -> None:
        # 普通 git short hash 形态：长度 < 16，不被任何 regex 收
        msg = "Commit a1b2c3d landed"
        self.assertEqual(self.s.sanitize(msg), msg)

    def test_uuid_not_redacted(self) -> None:
        msg = "task_id=550e8400-e29b-41d4-a716-446655440000"
        # uuid 不是 ``eyJ`` 开头、不在任何 vendor 前缀里
        self.assertEqual(self.s.sanitize(msg), msg)

    def test_bearer_token_not_blanket_redacted(self) -> None:
        # 我们故意不收 Bearer header 的 token（避免误伤合法日志），但如果
        # token 本身是 JWT / sk-... 形态会被对应 regex 命中
        msg = "Authorization: Bearer abc.def.ghi"
        # ``abc.def.ghi`` 不是 JWT（不以 eyJ 开头），不应被改
        self.assertEqual(self.s.sanitize(msg), msg)


class TestSanitizerIsCalledByPatcher(unittest.TestCase):
    """``_sanitize_and_escape`` patcher 必须仍然走 ``_global_sanitizer``。"""

    def test_patcher_uses_global_sanitizer(self) -> None:
        from enhanced_logging import _sanitize_and_escape

        token = "sk-proj-" + "Z" * 40
        record: dict[str, str] = {"message": f"key={token}"}
        _sanitize_and_escape(record)
        self.assertNotIn(token, record["message"])
        self.assertIn(REDACTED, record["message"])


class TestRingBufferUsesNewSanitizer(unittest.TestCase):
    """R51-C 的 ring buffer 写入路径也走新脱敏。"""

    def setUp(self) -> None:
        from enhanced_logging import clear_recent_logs

        clear_recent_logs()

    def test_record_to_ring_redacts_modern_key(self) -> None:
        import logging

        from enhanced_logging import _record_to_ring, get_recent_logs

        token = "sk-proj-" + "Y" * 40
        _record_to_ring(logging.WARNING, "test.logger", f"detected key={token}")

        entries = get_recent_logs()
        self.assertEqual(len(entries), 1)
        msg = str(entries[0]["message"])
        self.assertNotIn(token, msg)
        self.assertIn(REDACTED, msg)


if __name__ == "__main__":
    unittest.main()
