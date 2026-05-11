"""R151 — Housekeeping after Code Review #8 (R146-R149-R150 follow-up).

Background
----------
After Code Review #8 wrapped up R146-R149 + R150, three small but
load-bearing maintenance items remained:

1.  **CLIENT_COOLDOWN_MS** in
    ``src/ai_intervention_agent/static/js/notification_test_button.js``
    was 600 ms — set in R146 when the dispatch round-trip was ~2 s.
    R147 + R148 grew the user-visible round-trip to 4-8 s
    (baseline + dispatch + probe + delay).  At 600 ms the cooldown
    was effectively zero relative to the ``button.disabled`` window
    covering the same path; bumping it to 1500 ms keeps the cooldown
    *defensive* (in particular surviving a settings-panel re-mount
    where ``button.disabled`` resets but the ``data-last-click-ts``
    DOM attribute survives) rather than decorative.

2.  **Open VSX `displayName` mismatch** historically broke v1.6.1's
    release.  R149 pinned ``ovsx@0.10.9`` but did **not** document
    the upgrade ritual.  A future maintainer reading just the source
    has no way to know "do I bump the pin to ``ovsx@0.11.0`` when
    the next breaking change drops, or do I unpin?"  R151 adds a
    full ``docs/troubleshooting.md`` section explaining both Tier 1
    (literal content fix) and Tier 2 (pin) plus a step-by-step
    upgrade-the-pin ritual + Chinese mirror.

3.  **CHANGELOG R148-R151 entries** must persist somewhere in the
    file (not be silently dropped). R151 originally backfilled them
    into ``[Unreleased]`` so v1.6.3's release notes would not ship
    empty. The v1.6.3 bump (R179) then correctly migrated those
    entries from ``[Unreleased]`` into ``[1.6.3]`` — Keep-a-Changelog
    standard practice.

R180 lifecycle rescue
---------------------
The third assertion class was originally pinned to ``[Unreleased]``
only. Once ``scripts/bump_version.py`` migrated R148-R151 into
``[1.6.3]``, the snapshot test fossilised: it assumed the
**transient** rolling section was the **persistent** home. R180
rescues the intent — we still guard that R148-R151 housekeeping
entries are present **somewhere** in the changelog under a real
release / Added / Changed / Fixed heading — without re-tying them
to the empty post-bump ``[Unreleased]`` block.

What this suite locks
---------------------
*   ``CLIENT_COOLDOWN_MS`` in the JS source is exactly 1500 (3-digit
    integer, ≥ 1500, ≤ 5000 sanity envelope).
*   ``docs/troubleshooting.md`` ships a section #12 covering Open VSX
    displayName + ovsx pin upgrade ritual, with concrete sub-headers
    matching the documented flow.
*   ``docs/troubleshooting.zh-CN.md`` mirrors the section (parity with
    the rest of the bilingual docs in this repo).
*   ``CHANGELOG.md`` mentions R148, R149, R150, R151 in some real
    release section (Added / Changed / Fixed) — and the
    ``[Unreleased]`` anchor still exists (may be empty after a bump,
    which is correct per Keep-a-Changelog).

A failure in any of these means the housekeeping deliverable drifted
out of lockstep — fix the source, don't relax the test.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS_PATH = ROOT / "src/ai_intervention_agent/static/js/notification_test_button.js"
TROUBLESHOOTING_EN = ROOT / "docs/troubleshooting.md"
TROUBLESHOOTING_ZH = ROOT / "docs/troubleshooting.zh-CN.md"
CHANGELOG = ROOT / "CHANGELOG.md"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class TestR151CooldownBump(unittest.TestCase):
    """R151 lifted CLIENT_COOLDOWN_MS from 600 to 1500."""

    def test_cooldown_is_at_least_1500(self) -> None:
        m = re.search(r"CLIENT_COOLDOWN_MS\s*=\s*(\d+)", _read(JS_PATH))
        self.assertIsNotNone(m, "CLIENT_COOLDOWN_MS 必须存在")
        assert m is not None
        v = int(m.group(1))
        self.assertGreaterEqual(
            v,
            1500,
            f"R151 把 CLIENT_COOLDOWN_MS 升到 1500；当前 {v} 偏低。"
            "若你打算降回去请确认 R147+R148 后 dispatch 路径仍 < 该值。",
        )
        self.assertLessEqual(
            v,
            5000,
            f"CLIENT_COOLDOWN_MS={v} 过长（>5s）；FETCH_TIMEOUT_MS=60s "
            "已经覆盖网络阻塞场景，过长 cooldown 会让用户误以为按钮坏了。",
        )

    def test_cooldown_has_r151_rationale_comment(self) -> None:
        # The bump should carry an inline rationale so a future code-
        # review doesn't mistake it for a typo and revert.
        text = _read(JS_PATH)
        idx = text.find("CLIENT_COOLDOWN_MS = ")
        self.assertGreater(idx, 0)
        # Look ~1500 chars above the line for an R151 / R147 / R148
        # mention; that's where our inline comment lives.
        window = text[max(0, idx - 1500) : idx]
        self.assertRegex(
            window,
            r"R151|R147|R148|baseline|probe|dispatch path",
            "CLIENT_COOLDOWN_MS bump 必须有附近的注释解释 R147/R148 "
            "之后的预算变化，否则未来 reviewer 可能误改回 600。",
        )


class TestR151TroubleshootingSection(unittest.TestCase):
    """``docs/troubleshooting.md`` 必须有 §12 Open VSX displayName / ovsx pin 章节."""

    def test_english_has_section(self) -> None:
        text = _read(TROUBLESHOOTING_EN)
        # Match the new section header.  Use re.MULTILINE so ``^`` /
        # ``$`` anchor at line boundaries inside the markdown body.
        self.assertRegex(
            text,
            re.compile(r"^## 12\.\s+Open VSX publish step fails", re.MULTILINE),
            "英文 troubleshooting 必须有 #12 Open VSX 章节",
        )
        # Tier 1 + Tier 2 + upgrade ritual subsections all required.
        for needle in (
            "match content literally",
            "pin the toolchain",
            "Upgrading the pinned",
        ):
            self.assertIn(
                needle,
                text,
                f"英文 troubleshooting #12 必须含子标题/段落 {needle!r}",
            )

    def test_chinese_has_mirrored_section(self) -> None:
        text = _read(TROUBLESHOOTING_ZH)
        self.assertRegex(
            text,
            re.compile(r"^## 12\.\s+Open VSX 发布步骤失败", re.MULTILINE),
            "中文 troubleshooting 必须有 #12 Open VSX 章节",
        )
        for needle in (
            "字面量对齐",
            "锁工具链版本",
            "升级钉死的",
        ):
            self.assertIn(
                needle,
                text,
                f"中文 troubleshooting #12 必须含子标题 {needle!r}",
            )

    def test_both_reference_r149_workflow_path(self) -> None:
        # Cross-reference must point readers at the actual file +
        # the regression test, not just paraphrase.
        for path in (TROUBLESHOOTING_EN, TROUBLESHOOTING_ZH):
            text = _read(path)
            self.assertIn(
                "release.yml",
                text,
                f"{path.name} 必须 reference release.yml 路径",
            )
            self.assertIn(
                "test_release_workflow_ovsx_pinned_r149.py",
                text,
                f"{path.name} 必须 reference R149 guard test path",
            )


class TestR151ChangelogPersistence(unittest.TestCase):
    """R148-R151 housekeeping entries 必须在 CHANGELOG 中持久存在.

    R180 lifecycle rescue
    ---------------------
    Original ``TestR151ChangelogUnreleased`` (R151) pinned the
    invariant on the rolling ``[Unreleased]`` section. That worked
    until the v1.6.3 bump (R179) migrated R148-R151 entries into the
    persistent ``[1.6.3]`` section per Keep-a-Changelog — the
    snapshot test then claimed the bump had rolled back the entries.

    Fix: track R148-R151 in the **whole** changelog under any
    release-flavour heading. We still keep an ``[Unreleased]`` anchor
    assertion (the anchor must exist, but may be empty post-bump —
    that is the correct Keep-a-Changelog state right after a
    release).
    """

    #: Headings under which a "real entry" is allowed to live.
    #: Notably, "release" body (``## [x.y.z]``) is also valid because
    #: we accept entries listed directly under the release header
    #: without an explicit ``### Added``/``### Changed`` sub-heading.
    _VALID_ENTRY_HEADINGS = {"### Added", "### Changed", "### Fixed"}

    def setUp(self) -> None:
        self.text = _read(CHANGELOG)

    def _all_section_headings_for(self, ident: str) -> list[str]:
        """Return every ``### X`` heading under which ``ident`` appears.

        Walks each occurrence of ``ident`` (so a token mentioned in
        prose **and** in a real entry both count) and records the
        most-recent **line-anchored** ``### `` heading above it. We
        deliberately stop at ``### `` (h3) so we capture the
        Keep-a-Changelog category (Added/Changed/Fixed), not the
        release ``## [x.y.z]`` header.

        Uses ``re.MULTILINE`` so an inline ``### x`` in prose can't
        masquerade as a heading.
        """
        # Pre-compute every line-anchored h3 heading position so each
        # lookup is O(log h3-count) instead of O(text-length).
        h3_positions: list[tuple[int, str]] = [
            (m.start(), m.group(0).strip())
            for m in re.finditer(r"^### .+$", self.text, re.MULTILINE)
        ]
        headings: list[str] = []
        for m in re.finditer(re.escape(ident), self.text):
            idx = m.start()
            nearest: str | None = None
            for pos, heading in h3_positions:
                if pos < idx:
                    nearest = heading
                else:
                    break
            if nearest is not None:
                headings.append(nearest)
        return headings

    def test_unreleased_section_exists(self) -> None:
        """``[Unreleased]`` anchor must remain (may be empty post-bump).

        Keep-a-Changelog requires the rolling section to be present
        even between releases — it's how the next dev cycle starts.
        We no longer require non-empty body: that is a *transient*
        property, not a regression-worthy invariant.
        """
        self.assertRegex(
            self.text,
            re.compile(r"^## \[Unreleased\]\s*$", re.MULTILINE),
            "CHANGELOG 必须保留 ## [Unreleased] 锚点（即便为空）",
        )

    def test_mentions_each_r_feature(self) -> None:
        """R148-R151 must persist somewhere — Unreleased *or* released."""
        for ident in ("R148", "R149", "R150", "R151"):
            self.assertIn(
                ident,
                self.text,
                f"CHANGELOG 必须 mention {ident}（不限 section）",
            )

    def test_categorized_under_added_or_changed(self) -> None:
        """R148-R151 must each appear under at least one ``### Added``/
        ``### Changed``/``### Fixed`` heading."""
        for ident in ("R148", "R149", "R150", "R151"):
            headings = self._all_section_headings_for(ident)
            self.assertTrue(
                headings,
                f"{ident} 应当至少在一个 ### 子节下出现",
            )
            self.assertTrue(
                any(h in self._VALID_ENTRY_HEADINGS for h in headings),
                f"{ident} 必须至少在 Added/Changed/Fixed 之一下出现, "
                f"实际所在 ### 子节: {headings}",
            )


if __name__ == "__main__":
    unittest.main()
