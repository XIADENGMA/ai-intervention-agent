"""R641 - empty/singleton Prometheus histogram bucket keys avoid list()."""

from __future__ import annotations

import inspect
from unittest import mock

from ai_intervention_agent.web_ui_routes import system as system_module


def _raise_if_list_called(_value: object) -> list[float]:
    raise AssertionError("empty/singleton bucket fast path must not call list(buckets)")


def test_empty_bucket_keys_do_not_materialize_bucket_list() -> None:
    with mock.patch.object(system_module, "list", _raise_if_list_called, create=True):
        keys, has_inf_bucket = system_module._prom_histogram_bucket_keys({})

    assert keys == [system_module._PROM_INF]
    assert has_inf_bucket is False


def test_single_bucket_key_does_not_materialize_bucket_list() -> None:
    with mock.patch.object(system_module, "list", _raise_if_list_called, create=True):
        keys, has_inf_bucket = system_module._prom_histogram_bucket_keys({0.5: 3})

    assert keys == [0.5, system_module._PROM_INF]
    assert has_inf_bucket is False


def test_single_inf_bucket_key_preserves_existing_inf_flag() -> None:
    with mock.patch.object(system_module, "list", _raise_if_list_called, create=True):
        keys, has_inf_bucket = system_module._prom_histogram_bucket_keys(
            {system_module._PROM_INF: 3}
        )

    assert keys == [system_module._PROM_INF]
    assert has_inf_bucket is True


def test_multi_bucket_path_still_materializes_for_sortedness_scan() -> None:
    keys, has_inf_bucket = system_module._prom_histogram_bucket_keys(
        {system_module._PROM_INF: 3, 0.5: 2, 0.1: 1}
    )

    assert keys == [0.1, 0.5, system_module._PROM_INF]
    assert has_inf_bucket is True


def test_bucket_key_source_checks_empty_singleton_before_list_materialization() -> None:
    source = inspect.getsource(system_module._prom_histogram_bucket_keys)

    count_idx = source.index("bucket_count = len(buckets)")
    empty_idx = source.index("if bucket_count == 0:")
    singleton_idx = source.index("if bucket_count == 1:")
    single_key_idx = source.index("single_key = next(iter(buckets))")
    list_idx = source.index("bucket_keys = list(buckets)")
    scan_idx = source.index("key_iter = iter(bucket_keys)")

    assert count_idx < empty_idx < singleton_idx < single_key_idx < list_idx < scan_idx
    assert "bucket_keys = list(buckets)" in source
