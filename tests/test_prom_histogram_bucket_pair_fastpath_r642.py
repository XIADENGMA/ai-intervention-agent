"""R642 - two-bucket Prometheus histogram keys avoid list materialization."""

from __future__ import annotations

import inspect
from typing import Any, cast
from unittest import mock

import pytest

from ai_intervention_agent.web_ui_routes import system as system_module


def _raise_if_list_called(_value: object) -> list[float]:
    raise AssertionError("two-bucket fast path must not call list(buckets)")


def test_two_ordered_finite_buckets_do_not_materialize_list() -> None:
    with mock.patch.object(system_module, "list", _raise_if_list_called, create=True):
        keys, has_inf_bucket = system_module._prom_histogram_bucket_keys(
            {0.1: 1, 0.5: 2}
        )

    assert keys == [0.1, 0.5, system_module._PROM_INF]
    assert has_inf_bucket is False


def test_two_unordered_finite_buckets_sort_with_single_compare() -> None:
    with mock.patch.object(system_module, "list", _raise_if_list_called, create=True):
        keys, has_inf_bucket = system_module._prom_histogram_bucket_keys(
            {0.5: 2, 0.1: 1}
        )

    assert keys == [0.1, 0.5, system_module._PROM_INF]
    assert has_inf_bucket is False


def test_two_bucket_existing_inf_flag_preserved_when_inf_is_last() -> None:
    with mock.patch.object(system_module, "list", _raise_if_list_called, create=True):
        keys, has_inf_bucket = system_module._prom_histogram_bucket_keys(
            {0.5: 2, system_module._PROM_INF: 2}
        )

    assert keys == [0.5, system_module._PROM_INF]
    assert has_inf_bucket is True


def test_two_bucket_existing_inf_flag_preserved_when_inf_is_first() -> None:
    with mock.patch.object(system_module, "list", _raise_if_list_called, create=True):
        keys, has_inf_bucket = system_module._prom_histogram_bucket_keys(
            {system_module._PROM_INF: 2, 0.5: 2}
        )

    assert keys == [0.5, system_module._PROM_INF]
    assert has_inf_bucket is True


def test_two_bucket_incompatible_keys_preserve_type_error() -> None:
    with pytest.raises(TypeError):
        system_module._prom_histogram_bucket_keys(cast(Any, {0.5: 2, "bad": 1}))


def test_pair_fastpath_source_precedes_list_materialization() -> None:
    source = inspect.getsource(system_module._prom_histogram_bucket_keys)

    count_idx = source.index("bucket_count = len(buckets)")
    pair_idx = source.index("if bucket_count == 2:")
    iter_idx = source.index("key_iter = iter(buckets)")
    compare_idx = source.index("if first_key > second_key:")
    list_idx = source.index("bucket_keys = list(buckets)")

    assert count_idx < pair_idx < iter_idx < compare_idx < list_idx
    assert "bucket_keys.sort()" in source
