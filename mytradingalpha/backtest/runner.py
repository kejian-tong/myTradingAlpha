"""Pure bounded reducer that emits canonical BT-01 clock events."""

from __future__ import annotations

from dataclasses import replace

from .clock import (
    _MAX_BINDINGS,
    _MAX_EVENTS,
    _MAX_RUN_SOURCE_BYTES,
    _MAX_SEQUENCE,
    _MAX_SOURCE_BYTES,
    BacktestInputError,
    SessionBinding,
    _CaptureBudget,
    _refresh_binding,
)
from .events import (
    BacktestEvent,
    _build_decision_event,
    _build_opportunity_event,
)

_BINDING_DOMAIN_SIZE = len(b"mytradingalpha:bt01:binding:v1\0")
_STAGE_PRIORITIES = (("decision", 4), ("opportunity", 5))


def _reject(reason_code: str) -> None:
    raise BacktestInputError(reason_code) from None


def _stage_priority(stage: str) -> int:
    for known, priority in _STAGE_PRIORITIES:
        if stage == known:
            return priority
    _reject("event_invalid")


class BacktestRunner:
    """Emit only deterministic decision and next-session opportunity events."""

    __slots__ = ()

    def run(
        self,
        bindings: tuple[SessionBinding, ...],
        *,
        start_sequence: int = 0,
    ) -> tuple[BacktestEvent, ...]:
        if type(bindings) is not tuple:
            _reject("input_invalid")
        binding_count = len(bindings)
        if binding_count > _MAX_BINDINGS:
            _reject("resource_limit")
        if type(start_sequence) is not int or not 0 <= start_sequence <= _MAX_SEQUENCE:
            _reject("sequence_invalid")
        event_count = binding_count * 2
        if event_count > _MAX_EVENTS:
            _reject("resource_limit")
        if event_count and start_sequence > _MAX_SEQUENCE - event_count + 1:
            _reject("sequence_invalid")
        for binding in bindings:
            if type(binding) is not SessionBinding:
                _reject("input_invalid")

        stored_source_bytes = 0
        for binding in bindings:
            source_json = object.__getattribute__(binding, "_sealed_source_json")
            if type(source_json) is not bytes:
                _reject("source_changed")
            source_size = _BINDING_DOMAIN_SIZE + len(source_json)
            if source_size > _MAX_SOURCE_BYTES:
                _reject("resource_limit")
            stored_source_bytes += source_size
            if stored_source_bytes > _MAX_RUN_SOURCE_BYTES:
                _reject("resource_limit")

        budget = _CaptureBudget()
        checked: list[tuple[SessionBinding, tuple[object, ...]]] = []
        decision_slots: set[tuple[object, ...]] = set()
        for binding in bindings:
            prepared = _refresh_binding(binding, budget)
            context, _, envelope, session = (
                prepared[0],
                prepared[1],
                prepared[2],
                prepared[3],
            )
            instrument_id = object.__getattribute__(
                object.__getattribute__(envelope, "quant"), "instrument_id"
            )
            variant_id = object.__getattribute__(context, "variant_id")
            session_date = object.__getattribute__(session, "session_date")
            slot = (session_date, instrument_id, variant_id)
            if slot in decision_slots:
                _reject("duplicate_decision_slot")
            decision_slots.add(slot)
            checked.append((binding, prepared))

        drafts: list[BacktestEvent] = []
        try:
            for _, prepared in checked:
                context, bundle, envelope, session, next_session, _, fingerprint = prepared
                decision = _build_decision_event(
                    context=context,
                    bundle=bundle,
                    envelope=envelope,
                    session=session,
                    source_fingerprint=fingerprint,
                    sequence=0,
                )
                opportunity = _build_opportunity_event(
                    context=context,
                    bundle=bundle,
                    envelope=envelope,
                    next_session=next_session,
                    source_fingerprint=fingerprint,
                    decision_event_id=decision.event_id,
                    sequence=0,
                )
                drafts.extend((decision, opportunity))
        except BacktestInputError:
            raise
        except Exception:
            _reject("event_invalid")

        event_ids: set[str] = set()
        for event in drafts:
            event_id = object.__getattribute__(event, "event_id")
            if event_id in event_ids:
                _reject("duplicate_event_id")
            event_ids.add(event_id)
        ordered = sorted(
            drafts,
            key=lambda event: (
                object.__getattribute__(event, "session_date"),
                object.__getattribute__(event, "economic_time"),
                _stage_priority(object.__getattribute__(event, "stage")),
                object.__getattribute__(event, "instrument_id"),
                object.__getattribute__(event, "event_id"),
            ),
        )
        previous_time = None
        for event in ordered:
            economic_time = object.__getattribute__(event, "economic_time")
            if previous_time is not None and economic_time < previous_time:
                _reject("event_invalid")
            previous_time = economic_time

        result = tuple(
            replace(event, sequence=start_sequence + index)
            for index, event in enumerate(ordered)
        )
        if any(len(event.canonical_bytes()) > 8192 for event in result):
            _reject("event_invalid")

        completion_budget = _CaptureBudget()
        for binding, _ in checked:
            _refresh_binding(binding, completion_budget)
        return result


__all__ = ["BacktestRunner"]
