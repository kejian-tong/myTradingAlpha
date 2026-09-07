"""Deterministic ResearchNote construction from sealed evidence and response data."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from math import isfinite

from mytradingalpha.contracts.research import (
    MAX_RESEARCH_NOTE_BYTES,
    EvidenceCitation,
    EvidenceReference,
    ResearchNote,
    ResearchNoteSerializationError,
    ResearchProvenance,
    ResearchSourceFields,
)
from mytradingalpha.contracts.schemas import Mode, NetworkPolicy, RunContext
from mytradingalpha.data.bundle import BundleReplayPolicy, EvidenceBundle
from mytradingalpha.data.provenance import SourceManifest
from mytradingalpha.data.universe import AssetClass, Instrument
from mytradingalpha.ops.logging import redact_plain_data, redact_text
from mytradingalpha.research.cached_response import (
    CachedGraphResponse,
    _safe_response_input,
)

from .evidence_tools import (
    AmbiguousEvidenceReferenceError,
    CrossBundleEvidenceError,
    DuplicateEvidenceReferenceError,
    EvidenceToolError,
    EvidenceToolset,
    IneligibleEvidenceReferenceError,
    MalformedEvidenceReferenceError,
    MissingEvidenceReferenceError,
    _copy_bundle,
    _copy_reference,
)


class ResearchNoteError(ValueError):
    """Base class for typed ResearchNote construction failures."""


class ResearchNoteInputError(ResearchNoteError):
    """Raised when source fields or claim mappings are malformed."""


class ResearchNoteBindingError(ResearchNoteError):
    """Raised when bundle, context, or cached response bindings disagree."""


_CONTEXT_FIELDS = (
    "schema_version",
    "run_id",
    "mode",
    "variant_id",
    "decision_time",
    "knowledge_cutoff",
    "earliest_execution_time",
    "bundle_id",
    "bundle_hash",
    "calendar_id",
    "base_currency",
    "network_policy",
)
_NETWORK_POLICY_FIELDS = (
    "data_capture_egress",
    "model_provider_egress",
    "research_tool_egress",
    "paper_broker_egress",
    "live_broker_egress",
)
_RESPONSE_FIELDS = (
    "schema_version",
    "response_id",
    "response_hash",
    "bundle_id",
    "bundle_hash",
    "knowledge_cutoff",
    "calendar_id",
    "replay_policy",
    "variant_id",
    "trade_date",
    "ticker",
    "instrument_id",
    "asset_type",
    "instrument_context",
    "graph_artifact_id",
    "graph_artifact_hash",
    "model_artifact_id",
    "model_artifact_hash",
    "runtime_manifest_id",
    "runtime_manifest_hash",
    "capture_manifest",
    "output",
    "output_hash",
)
_RESPONSE_STRING_FIELDS = (
    "schema_version",
    "response_id",
    "response_hash",
    "bundle_id",
    "bundle_hash",
    "calendar_id",
    "variant_id",
    "trade_date",
    "ticker",
    "instrument_id",
    "asset_type",
    "instrument_context",
    "graph_artifact_id",
    "graph_artifact_hash",
    "model_artifact_id",
    "model_artifact_hash",
    "runtime_manifest_id",
    "runtime_manifest_hash",
    "output_hash",
)


def _raw_fields(
    value: object,
    *,
    expected_type: type[object],
    expected_fields: tuple[str, ...],
) -> dict[str, object]:
    if type(value) is not expected_type:
        raise ResearchNoteInputError("unexpected caller-owned contract type")
    try:
        storage = object.__getattribute__(value, "__dict__")
    except (AttributeError, TypeError) as exc:
        raise ResearchNoteInputError("caller-owned contract storage is unavailable") from exc
    if type(storage) is not dict:
        raise ResearchNoteInputError("caller-owned contract storage must be an exact dictionary")
    keys = tuple(dict.keys(storage))
    if any(type(key) is not str for key in keys) or set(keys) != set(expected_fields):
        raise ResearchNoteInputError("caller-owned contract fields are not canonical")
    return {field: dict.__getitem__(storage, field) for field in expected_fields}


def _safe_response_data(value: object, *, seen: set[int], depth: int) -> object:
    if depth > 64:
        raise ResearchNoteBindingError("cached response output exceeds maximum depth")
    value_type = type(value)
    if value_type in (str, int, bool, type(None)):
        return value
    if value_type is float:
        if not isfinite(value):
            raise ResearchNoteBindingError("cached response output requires finite numbers")
        return value
    if value_type not in (dict, list, tuple):
        raise ResearchNoteBindingError("cached response output contains an unsupported object")
    identity = id(value)
    if identity in seen:
        raise ResearchNoteBindingError("cached response output contains a cycle")
    seen.add(identity)
    try:
        if value_type is dict:
            result: dict[str, object] = {}
            for key, item in value.items():
                if type(key) is not str:
                    raise ResearchNoteBindingError("cached response output keys must be strings")
                result[key] = _safe_response_data(item, seen=seen, depth=depth + 1)
            return result
        return value_type(
            _safe_response_data(item, seen=seen, depth=depth + 1) for item in value
        )
    finally:
        seen.remove(identity)


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError, UnicodeError) as exc:
        raise ResearchNoteSerializationError("research note is not canonical JSON data") from exc


def _copy_context(context: object) -> RunContext:
    try:
        fields = _raw_fields(
            context,
            expected_type=RunContext,
            expected_fields=_CONTEXT_FIELDS,
        )
        string_fields = (
            "schema_version",
            "run_id",
            "variant_id",
            "bundle_id",
            "bundle_hash",
            "calendar_id",
            "base_currency",
        )
        if any(type(fields[field]) is not str for field in string_fields):
            raise ResearchNoteBindingError("context string fields are malformed")
        if type(fields["mode"]) is not Mode:
            raise ResearchNoteBindingError("context mode is malformed")
        if any(type(fields[field]) is not datetime for field in (
            "decision_time",
            "knowledge_cutoff",
            "earliest_execution_time",
        )):
            raise ResearchNoteBindingError("context timestamps are malformed")
        policy = fields["network_policy"]
        policy_fields = _raw_fields(
            policy,
            expected_type=NetworkPolicy,
            expected_fields=_NETWORK_POLICY_FIELDS,
        )
        if any(type(policy_fields[field]) is not bool for field in _NETWORK_POLICY_FIELDS):
            raise ResearchNoteBindingError("context network policy is malformed")
        fields["network_policy"] = policy_fields
        return RunContext.model_validate(fields)
    except ResearchNoteInputError:
        raise
    except (TypeError, ValueError) as exc:
        raise ResearchNoteBindingError("context failed defensive validation") from exc


def _copy_response(response: object) -> CachedGraphResponse:
    try:
        fields = _raw_fields(
            response,
            expected_type=CachedGraphResponse,
            expected_fields=_RESPONSE_FIELDS,
        )
        if any(type(fields[field]) is not str for field in _RESPONSE_STRING_FIELDS):
            raise ResearchNoteBindingError("cached response string fields are malformed")
        if type(fields["knowledge_cutoff"]) not in (str, datetime):
            raise ResearchNoteBindingError("cached response cutoff is malformed")
        if type(fields["replay_policy"]) not in (str, BundleReplayPolicy):
            raise ResearchNoteBindingError("cached response replay policy is malformed")
        if type(fields["capture_manifest"]) is not SourceManifest:
            raise ResearchNoteBindingError("cached response capture manifest is malformed")
        fields["output"] = _safe_response_data(fields["output"], seen=set(), depth=0)
        safe_fields = _safe_response_input(fields)
        return CachedGraphResponse.model_validate(safe_fields)
    except ResearchNoteInputError:
        raise
    except (TypeError, ValueError) as exc:
        raise ResearchNoteBindingError("cached response failed defensive validation") from exc


def _project_provenance(manifest: object) -> ResearchProvenance:
    if type(manifest) is not SourceManifest:
        raise ResearchNoteBindingError("evidence provenance requires an exact SourceManifest")
    try:
        original = SourceManifest.model_validate(
            SourceManifest.model_dump(manifest, mode="python")
        )
        original_payload = original.model_dump(mode="json")
        manifest_hash = f"sha256:{hashlib.sha256(_canonical(original_payload)).hexdigest()}"
        redacted = redact_plain_data(original_payload)
        if type(redacted) is not dict:
            raise ResearchNoteSerializationError("redacted provenance is not a plain object")
        redacted["manifest_hash"] = manifest_hash
        return ResearchProvenance.model_validate(redacted)
    except ResearchNoteError:
        raise
    except (TypeError, ValueError) as exc:
        raise ResearchNoteBindingError("evidence provenance failed projection") from exc


def _trade_date(value: object) -> date:
    if type(value) is not str:
        raise ResearchNoteBindingError("cached response trade date is not a plain string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ResearchNoteBindingError("cached response trade date is invalid") from exc
    if parsed.isoformat() != value:
        raise ResearchNoteBindingError("cached response trade date is not canonical")
    return parsed


def _active_on(value: date, start: date, end: date | None) -> bool:
    return start <= value and (end is None or value < end)


def _resolve_instrument(
    bundle: EvidenceBundle,
    *,
    ticker: object,
    trade_date: object,
    asset_type: object,
) -> tuple[Instrument, str]:
    as_of = _trade_date(trade_date)
    if type(ticker) is not str or not ticker or ticker != ticker.strip():
        raise ResearchNoteBindingError("cached response ticker is invalid")
    if type(asset_type) is not str:
        raise ResearchNoteBindingError("cached response asset type is invalid")
    instrument_by_id = {item.instrument_id: item for item in bundle.instruments}
    candidate_ids = {
        alias.instrument_id
        for alias in bundle.aliases
        if alias.symbol == ticker and _active_on(as_of, alias.valid_from, alias.valid_to)
    }
    candidates = [
        instrument_by_id[instrument_id]
        for instrument_id in sorted(candidate_ids)
        if instrument_id in instrument_by_id
        and _active_on(
            as_of,
            instrument_by_id[instrument_id].active_from,
            instrument_by_id[instrument_id].active_to,
        )
    ]
    if not candidates:
        raise ResearchNoteBindingError(
            f"no unique sealed instrument for ticker {ticker!r} on {trade_date!r}"
        )
    if len(candidates) != 1:
        raise ResearchNoteBindingError(
            f"ambiguous sealed instrument for ticker {ticker!r} on {trade_date!r}"
        )
    instrument = candidates[0]
    permitted_classes = {AssetClass.EQUITY, AssetClass.ETF} if asset_type == "stock" else set()
    if instrument.asset_class not in permitted_classes:
        raise ResearchNoteBindingError(
            f"asset type does not match sealed instrument {instrument.instrument_id!r}"
        )
    instrument_context = (
        f"Symbol: {ticker}; instrument_id: {instrument.instrument_id}; "
        f"asset_class: {instrument.asset_class.value}; exchange: {instrument.exchange}; "
        f"currency: {instrument.currency}"
    )
    return instrument, instrument_context


def _validate_bindings(
    bundle: EvidenceBundle,
    context: RunContext,
    response: CachedGraphResponse,
) -> None:
    if context.bundle_id != bundle.bundle_id or context.bundle_hash != bundle.bundle_hash:
        raise ResearchNoteBindingError("run context is bound to a different evidence bundle")
    if context.knowledge_cutoff != bundle.knowledge_cutoff:
        raise ResearchNoteBindingError("run context cutoff does not match evidence bundle")
    if context.calendar_id != bundle.calendar.calendar_id:
        raise ResearchNoteBindingError("run context calendar does not match evidence bundle")
    response_bindings = (
        ("bundle_id", response.bundle_id, bundle.bundle_id),
        ("bundle_hash", response.bundle_hash, bundle.bundle_hash),
        ("knowledge_cutoff", response.knowledge_cutoff, bundle.knowledge_cutoff),
        ("calendar_id", response.calendar_id, bundle.calendar.calendar_id),
        ("variant_id", response.variant_id, context.variant_id),
    )
    for field, actual, expected in response_bindings:
        if actual != expected:
            raise ResearchNoteBindingError(f"cached response binding mismatch: {field}")
    if response.replay_policy.value != bundle.replay_policy.value:
        raise ResearchNoteBindingError("cached response replay policy does not match bundle")
    if response.trade_date != bundle.knowledge_cutoff.date().isoformat():
        raise ResearchNoteBindingError("cached response trade date does not match bundle cutoff")
    instrument, instrument_context = _resolve_instrument(
        bundle,
        ticker=response.ticker,
        trade_date=response.trade_date,
        asset_type=response.asset_type,
    )
    if response.instrument_id != instrument.instrument_id:
        raise ResearchNoteBindingError("cached response instrument does not match ticker alias")
    if response.instrument_context != instrument_context:
        raise ResearchNoteBindingError("cached response instrument context does not match alias")


def _reference_key(reference: EvidenceReference) -> tuple[str, str, str]:
    return reference.bundle_id, reference.domain, reference.record_id


class ResearchNoteBuilder:
    """Build one deterministic note from already sealed plain-data records."""

    def __init__(
        self,
        *,
        bundle: EvidenceBundle,
        context: RunContext,
        response: CachedGraphResponse,
    ) -> None:
        try:
            self._bundle = _copy_bundle(bundle)
        except EvidenceToolError as exc:
            raise ResearchNoteInputError("ResearchNoteBuilder received an invalid bundle") from exc
        self._context = _copy_context(context)
        self._response = _copy_response(response)

    def build(
        self,
        *,
        source_agent: object,
        source_fields: Mapping[str, str],
        claim_citations: Mapping[str, Sequence[EvidenceReference]],
    ) -> ResearchNote:
        """Build a note from explicit source fields and claim-to-citation mapping."""

        _validate_bindings(self._bundle, self._context, self._response)
        if type(source_agent) is not str or not source_agent or source_agent != source_agent.strip():
            raise ResearchNoteInputError("source_agent must be a non-empty plain string")
        if type(source_fields) is not dict or set(source_fields) != {"thesis", "risks"}:
            raise ResearchNoteInputError("source_fields must explicitly name thesis and risks")
        try:
            selected_fields = ResearchSourceFields.model_validate(source_fields)
        except (TypeError, ValueError) as exc:
            raise ResearchNoteInputError("source_fields are invalid") from exc
        if type(claim_citations) is not dict or set(claim_citations) != {"thesis", "risks"}:
            raise ResearchNoteInputError(
                "claim_citations must explicitly map thesis and risks"
            )
        output = self._response.output
        texts: dict[str, str] = {}
        for claim in ("thesis", "risks"):
            field = getattr(selected_fields, claim)
            if type(field) is not str or not field or field != field.strip():
                raise ResearchNoteInputError(f"{claim} source field must be a plain string")
            if field not in output or type(output[field]) is not str:
                raise ResearchNoteInputError(
                    f"{claim} source field must name an existing top-level string"
                )
            texts[claim] = redact_text(output[field])

        toolset = EvidenceToolset(self._bundle)
        citations: list[EvidenceCitation] = []
        seen: set[tuple[str, str, str]] = set()
        for claim in ("thesis", "risks"):
            references = claim_citations[claim]
            if type(references) not in (tuple, list) or not references:
                raise ResearchNoteInputError(f"{claim} must cite at least one evidence record")
            try:
                copied_references = tuple(_copy_reference(item) for item in references)
                ordered = tuple(
                    sorted(copied_references, key=lambda item: (item.domain, item.record_id))
                )
            except (AttributeError, TypeError, ValueError) as exc:
                raise ResearchNoteInputError("claim citations must be structured references") from exc
            for reference in ordered:
                key = _reference_key(reference)
                if key in seen:
                    raise DuplicateEvidenceReferenceError(
                        f"duplicate evidence citation: {reference.domain}/{reference.record_id}"
                    )
                item = toolset.get(reference)
                provenance = _project_provenance(
                    SourceManifest.model_validate(dict(item.provenance))
                )
                seen.add(key)
                citations.append(
                    EvidenceCitation(
                        claim=claim,
                        reference=reference,
                        provenance=provenance,
                        semantic_support="unassessed",
                    )
                )

        # Validate canonical note content before deriving its deterministic ID.
        base: dict[str, object] = {
            "schema_version": "v1",
            "run_id": self._context.run_id,
            "variant_id": self._context.variant_id,
            "instrument_id": self._response.instrument_id,
            "bundle_id": self._bundle.bundle_id,
            "bundle_hash": self._bundle.bundle_hash,
            "knowledge_cutoff": self._bundle.knowledge_cutoff,
            "calendar_id": self._bundle.calendar.calendar_id,
            "replay_policy": self._bundle.replay_policy.value,
            "response_id": self._response.response_id,
            "response_hash": self._response.response_hash,
            "output_hash": self._response.output_hash,
            "graph_artifact_id": self._response.graph_artifact_id,
            "graph_artifact_hash": self._response.graph_artifact_hash,
            "model_artifact_id": self._response.model_artifact_id,
            "model_artifact_hash": self._response.model_artifact_hash,
            "runtime_manifest_id": self._response.runtime_manifest_id,
            "runtime_manifest_hash": self._response.runtime_manifest_hash,
            "capture_manifest": _project_provenance(self._response.capture_manifest),
            "source_agent": source_agent,
            "source_fields": selected_fields,
            "thesis": texts["thesis"],
            "risks": (texts["risks"],),
            "citations": tuple(citations),
        }
        try:
            canonical_input = ResearchNote.model_validate(
                {**base, "note_id": "note-pending"}
            ).model_dump(mode="json")
            note_id = f"note-{hashlib.sha256(_canonical(canonical_input)).hexdigest()}"
            note = ResearchNote.model_validate({**base, "note_id": note_id})
            note.canonical_bytes()
            return note
        except ResearchNoteError:
            raise
        except (TypeError, ValueError) as exc:
            raise ResearchNoteSerializationError("research note failed canonical validation") from exc


__all__ = [
    "AmbiguousEvidenceReferenceError",
    "CrossBundleEvidenceError",
    "DuplicateEvidenceReferenceError",
    "EvidenceToolError",
    "IneligibleEvidenceReferenceError",
    "MalformedEvidenceReferenceError",
    "MAX_RESEARCH_NOTE_BYTES",
    "MissingEvidenceReferenceError",
    "ResearchNoteBindingError",
    "ResearchNoteBuilder",
    "ResearchNoteError",
    "ResearchNoteInputError",
    "ResearchNoteSerializationError",
]
