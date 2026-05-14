"""R239 / Cycle 15 · F-cycle14-4 (was F-cycle13-6): README star-count
snapshot date may not silently rot beyond 12 months.

Why this invariant
------------------

Both `README.md` and `README.zh-CN.md`'s "Related projects" section
ends with a disclaimer that the star counts shown are *snapshots*
with a "last reviewed YYYY-MM" date:

* EN: ``Star counts are approximate snapshots (last reviewed
  YYYY-MM); check each upstream for current numbers.``
* ZH: ``上面的 stars 是粗略快照（最近核对：YYYY-MM），请以各上游为
  准。``

Without a guard this date drifts silently — at v1.7.7 the
"~3.8k", "~1.4k", "~310", "~30" numbers next to it become
unverifiable claims. Worse, *first-time readers* trust the
date as freshness signal and infer accuracy that isn't there.

What this test guards
---------------------

1. **Date exists** in both EN + ZH READMEs, matching ``YYYY-MM``
   format.
2. **Date is parseable** (not e.g. ``2026-13`` or ``20260514``).
3. **Date is not in the future** (catches typos like ``2099-05``).
4. **Date is not older than 12 months** from today. The 12-month
   threshold is intentionally generous: this is a star-count
   list of competitor projects, not a security-critical claim;
   yearly refresh is the standard for "related projects" sections
   in mature OSS READMEs.
5. **Date matches across locales** (EN + ZH) — if one drifts
   ahead the other should follow.

Recovery path
-------------

When this test fails, the maintainer is expected to:

1. Re-check each project's GitHub star count.
2. Update the ``~Nk`` / ``~NNN`` figures in both READMEs as needed.
3. Bump the ``last reviewed YYYY-MM`` to current month.
4. Commit with a chore: prefix (no behavior change).

The 12-month threshold can be overridden via env var
``R239_STAR_COUNT_MAX_AGE_MONTHS`` for emergency or one-off
investigation — but never bake an override into the test itself.

This is a Pattern D (documentation-freshness / drift-detection)
invariant in the spirit of R231 (catalogue lag) and R233 (README
factual claims).
"""

from __future__ import annotations

import datetime as dt
import os
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README_EN = REPO_ROOT / "README.md"
README_ZH = REPO_ROOT / "README.zh-CN.md"

DEFAULT_MAX_AGE_MONTHS = 12

EN_DATE_PATTERN = re.compile(
    r"Star counts are approximate snapshots \(last reviewed "
    r"(?P<year>\d{4})-(?P<month>\d{1,2})\);"
)
ZH_DATE_PATTERN = re.compile(r"最近核对：(?P<year>\d{4})-(?P<month>\d{1,2})")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _today() -> dt.date:
    return dt.date.today()


def _max_age_months() -> int:
    override = os.environ.get("R239_STAR_COUNT_MAX_AGE_MONTHS")
    if override:
        try:
            value = int(override)
            if value <= 0:
                raise ValueError
            return value
        except ValueError as exc:
            raise ValueError(
                f"R239_STAR_COUNT_MAX_AGE_MONTHS must be a positive integer, "
                f"got {override!r}"
            ) from exc
    return DEFAULT_MAX_AGE_MONTHS


def _extract_date(text: str, pattern: re.Pattern[str], locale: str) -> dt.date:
    match = pattern.search(text)
    assert match is not None, (
        f"R239: cannot find 'last reviewed' / '最近核对' date in {locale} README. "
        f"If the disclaimer was rewritten, update the regex in this test."
    )
    year = int(match.group("year"))
    month = int(match.group("month"))
    if month < 1 or month > 12:
        raise AssertionError(
            f"R239: invalid month {month} in {locale} README 'last reviewed' "
            f"date (must be 1-12)"
        )
    return dt.date(year, month, 1)


def _months_between(earlier: dt.date, later: dt.date) -> int:
    return (later.year - earlier.year) * 12 + (later.month - earlier.month)


class TestStarCountDateExtractable(unittest.TestCase):
    def test_en_readme_has_parseable_date(self) -> None:
        _extract_date(_read(README_EN), EN_DATE_PATTERN, "EN")

    def test_zh_readme_has_parseable_date(self) -> None:
        _extract_date(_read(README_ZH), ZH_DATE_PATTERN, "ZH")


class TestStarCountDateNotInFuture(unittest.TestCase):
    def test_en_readme_date_not_in_future(self) -> None:
        date = _extract_date(_read(README_EN), EN_DATE_PATTERN, "EN")
        today = _today()
        self.assertLessEqual(
            date,
            dt.date(today.year, today.month, 1),
            msg=(
                f"R239 invariant: EN README 'last reviewed' = {date.isoformat()} "
                f"在未来 (today = {today.isoformat()}). 常见原因: 写错年份 "
                f"(2099-XX) 或月份。修正方式: 改回当前月份。"
            ),
        )

    def test_zh_readme_date_not_in_future(self) -> None:
        date = _extract_date(_read(README_ZH), ZH_DATE_PATTERN, "ZH")
        today = _today()
        self.assertLessEqual(date, dt.date(today.year, today.month, 1))


class TestStarCountDateWithinFreshnessWindow(unittest.TestCase):
    def test_en_readme_date_within_window(self) -> None:
        date = _extract_date(_read(README_EN), EN_DATE_PATTERN, "EN")
        today = _today()
        age = _months_between(date, today)
        max_age = _max_age_months()
        self.assertLessEqual(
            age,
            max_age,
            msg=(
                f"R239 invariant: EN README 'last reviewed' = {date.isoformat()} "
                f"距今 {age} 个月, 超过 {max_age} 月阈值。需重新核对 'Related "
                "projects' 表中每个项目的 GitHub star 数 (3 项 + 1 ancestor), "
                "更新 ~Nk / ~NNN 数字, 然后把 'last reviewed YYYY-MM' 改成当前"
                "月份。也可通过环境变量 R239_STAR_COUNT_MAX_AGE_MONTHS 临时调整"
                "阈值 (但不要写进测试代码本身)。"
            ),
        )

    def test_zh_readme_date_within_window(self) -> None:
        date = _extract_date(_read(README_ZH), ZH_DATE_PATTERN, "ZH")
        today = _today()
        age = _months_between(date, today)
        max_age = _max_age_months()
        self.assertLessEqual(age, max_age)


class TestStarCountDateParityAcrossLocales(unittest.TestCase):
    """EN + ZH 必须用同一个 review 日期, 否则两个 README 'freshness' 不一致。"""

    def test_dates_match(self) -> None:
        en_date = _extract_date(_read(README_EN), EN_DATE_PATTERN, "EN")
        zh_date = _extract_date(_read(README_ZH), ZH_DATE_PATTERN, "ZH")
        self.assertEqual(
            en_date,
            zh_date,
            msg=(
                f"R239 invariant: EN README ({en_date.isoformat()}) 与 ZH README "
                f"({zh_date.isoformat()}) 的 'last reviewed' 日期不一致。同一次"
                "核对应同步两份 README, 否则一边显示 stale 一边显示 fresh, 用户"
                "无法判断信任哪份。"
            ),
        )


if __name__ == "__main__":
    unittest.main()
