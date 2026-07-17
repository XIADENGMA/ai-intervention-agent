from __future__ import annotations

import inspect

from ai_intervention_agent.state_machine import (
    TRANSITIONS,
    ConnectionStatus,
    list_transitions,
)


def test_list_transitions_uses_dict_copy_for_rule_snapshots() -> None:
    source = inspect.getsource(list_transitions)

    assert "rules.copy()" in source
    assert "dict(rules)" not in source


def test_list_transitions_returns_independent_shallow_rule_snapshots() -> None:
    snapshot = list_transitions()

    assert snapshot == TRANSITIONS
    assert snapshot is not TRANSITIONS

    for kind, rules in snapshot.items():
        assert rules is not TRANSITIONS[kind]
        for source_state, targets in rules.items():
            assert targets is TRANSITIONS[kind][source_state]

    original_targets = TRANSITIONS["connection"][ConnectionStatus.IDLE]
    snapshot["connection"][ConnectionStatus.IDLE] = ("mutated",)

    assert TRANSITIONS["connection"][ConnectionStatus.IDLE] == original_targets
