"""R213 / Cycle 10 · F-21.4-1 · production static assets precompress completeness invariant。

设计目标
========

R20.14-D 引入 ``.gz`` 预压缩，R21.4 加 ``.br`` (brotli) 预压缩，``scripts/
precompress_static.py --check`` 在 build-time 能检测 stale，但**没有
pytest-level 信号**守护「production static assets 真的有完整的 .br + .gz
副本」。

后果（silent decay 风险，沿用 CR#10 lessons-learned 同款剧本）：

- 如果 brotli 包某次 dependency bump 被意外删除 → ``BROTLI_AVAILABLE =
  False`` → precompress 静默跳过所有 .br 写入 → CI 不报错（precompress
  --check 模式认为「跳过」是合法 action 不是 stale）→ production 全部
  fall back .gz/raw，体积大 17-23%，无人察觉直到用户报「页面慢」；
- 如果某次 refactor 把某个 css/js 改大体积超过 MIN_SIZE_BYTES 但忘
  跑 precompress → 该文件只有 raw，没 .gz/.br → 同上 silent perf decay；
- 如果某次 refactor 把 ``DEFAULT_TARGET_DIRS`` 改名 (e.g. 把
  ``static/locales`` 改成 ``static/i18n``) 但忘了同步 precompress 配
  置 → 新目录的资源不被预压缩 → 同上。

R20.14-D / R21.4 测试套（``test_static_compression_r20_14d.py`` +
``test_brotli_precompress_r21_4.py``）覆盖了 ``compress_file()`` /
``compress_file_br()`` / ``_send_with_optional_gzip()`` 的单元行为 +
Flask test client e2e；**但所有测试都跑在 ``tmp_path`` fixture 上**, 没
有一个测试断言 production 的 ``src/ai_intervention_agent/static/``
目录里的资源真有齐全的 .br + .gz 副本。

R213 是 production assets 完整性 invariant —— pytest 跑到这个测试时, 必
须看到 production static 目录里**每个**符合预压缩条件的文件 (size ≥
MIN_SIZE_BYTES + 扩展名不在 SKIP_EXTENSIONS) 都有：

1. **.gz 副本**（gzip 必须 work, 是 fallback 的底线）；
2. **.br 副本**（仅当 brotli 可用; CI 环境 brotli 装在 dev deps 里）；
3. **.gz 体积 < 原文件**（gzip 有效）；
4. **.br 体积 < .gz 体积**（brotli 优于 gzip，R21.4 设计前提）；
5. **.gz/.br 反解后 byte-equal 原文件**（不是被 stale state 卡住）。

设计契约
========

* **运行时 invariant, 非 build script**：pytest 自己跑这个测试,
  不依赖 ``precompress --check`` 在 build 时跑过 (CI gate 已经先跑了
  precompress 但本测试不假设这一点);
* **零 source code 改动**：与 R212 同款 invariant-only 风格, 后续任意
  refactor 漂移都被 pytest fail 捕获;
* **brotli 不可用时 graceful skip .br 检查**：现实里测试环境 brotli
  可能缺，但 gzip 必须始终存在 (Python stdlib);
* **R20.14-D / R21.4 测试不重叠**：本测试只测「production target dirs
  内 build artifacts 完整性」, 不重测 compress_file_* 单元行为。

测试架构 (4 invariant class / 9 cases / 1 subtest)
==================================================

1. TestProductionGzipCompleteness (3 cases): production css/js/locales/lottie
   目录里, 每个符合条件的 source 都有 .gz + .gz 体积 < 原 + 反解
   byte-equal;
2. TestProductionBrotliCompleteness (3 cases, brotli-skip): 同上 .br
   层 + .br 体积 < .gz;
3. TestProductionTargetDirsRegistered (2 cases): 防 refactor 漂移
   ——`DEFAULT_TARGET_DIRS` 必含 css / js / locales / lottie 四个目录, 路径
   存在;
4. TestPrecompressCheckExitsCleanInProduction (1 case + 1 subtest):
   `precompress_static.py --check` 在 production assets 上必须
   exit code 0 (no stale).

沿用 R212 invariant bridge 风格 + 零 source changes 原则。
"""

from __future__ import annotations

import gzip
import subprocess
import sys
import unittest
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.precompress_static import (
    BROTLI_AVAILABLE,
    DEFAULT_TARGET_DIRS,
    MIN_SIZE_BYTES,
    SKIP_EXTENSIONS,
)


def _iter_production_sources() -> Iterator[Path]:
    """遍历 production target dirs, yield 每个**符合预压缩条件**的源文件。

    条件: 文件存在 + 大小 ≥ MIN_SIZE_BYTES + 扩展名不在 SKIP_EXTENSIONS。
    """
    for d in DEFAULT_TARGET_DIRS:
        if not d.is_dir():
            continue
        for f in d.iterdir():
            if not f.is_file():
                continue
            if f.suffix.lower() in SKIP_EXTENSIONS:
                continue
            try:
                size = f.stat().st_size
            except OSError:
                continue
            if size < MIN_SIZE_BYTES:
                continue
            yield f


# ---------------------------------------------------------------------------
# 1. Production .gz completeness invariant
# ---------------------------------------------------------------------------


class TestProductionGzipCompleteness(unittest.TestCase):
    """生产环境每个符合条件的源文件必有 .gz 副本 + 体积合理 + 反解 byte-equal。

    这是 R20.14-D production assets 的完整性硬契约——一旦失守, raw
    response 取代 .gz response, 实测体积可砍 70-85% 的性能收益直接
    消失, 用户感知首屏慢。
    """

    def setUp(self) -> None:
        self.sources = list(_iter_production_sources())
        # 防止 sources 列表为空（target dirs 整个被删 / refactor 改名）
        # 时本 test 误"trivially pass"。
        self.assertGreater(
            len(self.sources),
            0,
            "production target dirs 必有至少一个符合预压缩条件的源文件; "
            "为 0 暗示 DEFAULT_TARGET_DIRS 路径漂移或目录全空 — 检查 "
            "src/ai_intervention_agent/static/{css,js,locales,lottie}",
        )

    def test_every_source_has_gz_sibling(self) -> None:
        """每个 source 必有 ``<source>.gz`` sibling."""
        missing = [
            str(s.relative_to(REPO_ROOT))
            for s in self.sources
            if not s.with_suffix(s.suffix + ".gz").is_file()
        ]
        self.assertEqual(
            missing,
            [],
            f"{len(missing)} production sources 缺 .gz 副本: {missing[:5]}"
            "...; 跑 `uv run python scripts/precompress_static.py` 生成",
        )

    def test_every_gz_smaller_than_source(self) -> None:
        """每个 .gz 体积必小于原 source（否则 precompress 不该写出来）。"""
        bloated = []
        for s in self.sources:
            gz = s.with_suffix(s.suffix + ".gz")
            if not gz.is_file():
                continue
            if gz.stat().st_size >= s.stat().st_size:
                bloated.append(
                    (
                        str(s.relative_to(REPO_ROOT)),
                        s.stat().st_size,
                        gz.stat().st_size,
                    )
                )
        self.assertEqual(
            bloated,
            [],
            "以下 .gz 体积 ≥ 原 source — precompress 反检 (skipped_no_gain) "
            f"被绕过, 应当重新跑 precompress: {bloated[:3]}",
        )

    def test_gz_decompress_byte_equal_to_source(self) -> None:
        """.gz 反解必须 byte-equal 原 source (defends against stale)。

        采样 5 个 (避免 5000+ files 全跑导致测试慢) — 这是 sanity
        check, 不是穷举验证 (穷举留给 R21.4 _is_fresh helper)。
        """
        sampled = self.sources[:5]
        for s in sampled:
            gz = s.with_suffix(s.suffix + ".gz")
            if not gz.is_file():
                continue
            with self.subTest(source=str(s.relative_to(REPO_ROOT))):
                raw_expected = s.read_bytes()
                with gzip.open(gz, "rb") as fh:
                    raw_actual = fh.read()
                self.assertEqual(
                    raw_expected,
                    raw_actual,
                    f".gz stale: {s} 解压后 ≠ 原文件 — 跑 precompress 重新生成",
                )


# ---------------------------------------------------------------------------
# 2. Production .br completeness invariant (brotli optional)
# ---------------------------------------------------------------------------


@unittest.skipUnless(
    BROTLI_AVAILABLE, "brotli package not installed; skip R213 brotli invariant"
)
class TestProductionBrotliCompleteness(unittest.TestCase):
    """生产环境每个符合条件的源文件必有 .br 副本 + 体积 < .gz + 反解 byte-equal。

    这是 R21.4 production assets 的完整性硬契约——一旦失守, brotli
    精细压缩收益 (实测比 gzip 小 17-23%) 直接消失, 退化到 R20.14-D
    水平。
    """

    def setUp(self) -> None:
        self.sources = list(_iter_production_sources())
        self.assertGreater(
            len(self.sources),
            0,
            "production target dirs 必有至少一个符合预压缩条件的源文件",
        )

    def test_every_source_has_br_sibling(self) -> None:
        missing = [
            str(s.relative_to(REPO_ROOT))
            for s in self.sources
            if not s.with_suffix(s.suffix + ".br").is_file()
        ]
        self.assertEqual(
            missing,
            [],
            f"{len(missing)} production sources 缺 .br 副本: {missing[:5]}"
            "...; 跑 `uv run python scripts/precompress_static.py` 生成",
        )

    def test_every_br_smaller_or_equal_than_gz(self) -> None:
        """.br 体积应**严格**小于 .gz（这是 R21.4 的设计前提）。

        允许极少数 'br ≈ gz' edge case (e.g. 已经压到熵极限的 minified
        bundle), 这里测 .br ≤ .gz + 5% tolerance (gzip 偶尔在某些
        repetitive ASCII 上小幅占优, R21.4 没用 quality < 11 时也可能)。
        如果 .br > .gz × 1.05 就 fail —— 暗示 .br 该被 precompress
        skipped_no_gain 但实际写出来了 (bug)。
        """
        regressed = []
        for s in self.sources:
            gz = s.with_suffix(s.suffix + ".gz")
            br = s.with_suffix(s.suffix + ".br")
            if not (gz.is_file() and br.is_file()):
                continue
            gz_size = gz.stat().st_size
            br_size = br.stat().st_size
            # 5% tolerance — see docstring
            if br_size > gz_size * 1.05:
                regressed.append(
                    (
                        str(s.relative_to(REPO_ROOT)),
                        gz_size,
                        br_size,
                        round((br_size / gz_size - 1) * 100, 1),
                    )
                )
        self.assertEqual(
            regressed,
            [],
            "以下 .br 体积 > .gz × 1.05 — R21.4 设计违规 (brotli 应"
            f"严格优于 gzip 或被 skipped_no_gain): {regressed[:3]}",
        )

    def test_br_decompress_byte_equal_to_source(self) -> None:
        """.br 反解必须 byte-equal 原 source (defends against stale)。

        采样 5 个 — 同 gzip 测试理由。
        """
        import brotli  # type: ignore[import-untyped]

        sampled = self.sources[:5]
        for s in sampled:
            br = s.with_suffix(s.suffix + ".br")
            if not br.is_file():
                continue
            with self.subTest(source=str(s.relative_to(REPO_ROOT))):
                raw_expected = s.read_bytes()
                raw_actual = brotli.decompress(br.read_bytes())
                self.assertEqual(
                    raw_expected,
                    raw_actual,
                    f".br stale: {s} 解压后 ≠ 原文件 — 跑 precompress 重新生成",
                )


# ---------------------------------------------------------------------------
# 3. Target dirs registration drift guard
# ---------------------------------------------------------------------------


class TestProductionTargetDirsRegistered(unittest.TestCase):
    """``DEFAULT_TARGET_DIRS`` 必含 css / js / locales / lottie 四个目录, 路径存在。

    防 refactor 漂移: R76 把 ``static/`` 从根挪进 ``src/ai_intervention_
    agent/`` 包内时, ``DEFAULT_TARGET_DIRS`` 没同步过一次 (历史教
    训, 见 ``scripts/check_brand_color_consistency.py`` 顶部 R88 注
    释)。如果未来又有人改 ``DEFAULT_TARGET_DIRS`` 路径但忘同步 (或
    反向: 加新 static 目录但没加进 DEFAULT_TARGET_DIRS), 本测试 fail。
    """

    def test_default_target_dirs_contain_expected_subdirs(self) -> None:
        names = [d.name for d in DEFAULT_TARGET_DIRS]
        for expected in ("css", "js", "locales", "lottie"):
            self.assertIn(
                expected,
                names,
                f"DEFAULT_TARGET_DIRS 缺 {expected!r} 子目录; 路径漂移?",
            )

    def test_all_target_dirs_exist_on_disk(self) -> None:
        missing = [
            str(d.relative_to(REPO_ROOT)) for d in DEFAULT_TARGET_DIRS if not d.is_dir()
        ]
        self.assertEqual(
            missing,
            [],
            f"DEFAULT_TARGET_DIRS 中有不存在的路径: {missing} — 路径漂移?",
        )


# ---------------------------------------------------------------------------
# 4. precompress --check 在 production assets 上 exit 0 (no stale)
# ---------------------------------------------------------------------------


class TestPrecompressCheckExitsCleanInProduction(unittest.TestCase):
    """``scripts/precompress_static.py --check`` 在 production assets 上必 exit 0。

    本测试与 ci_gate.py 已经跑过的 precompress --check **重复**, 但
    这里的价值是: pytest 本地跑 ``uv run pytest`` (跳过 ci_gate)
    也能立刻发现 stale precompress, 不必等 ci_gate run 才知道。
    """

    def test_precompress_check_no_stale(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "precompress_static.py"),
                "--check",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"precompress_static.py --check exit code {result.returncode}; "
            f"stale precompress detected. stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
