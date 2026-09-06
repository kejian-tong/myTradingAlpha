"""Deterministic ResearchNote construction from sealed evidence and response data."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from mytradingalpha.contracts.research import EvidenceCitation, EvidenceReference, ResearchNote
from mytradingalpha.contracts.schemas import RunContext
from mytradingalpha.data.bundle import EvidenceBundle
from mytradingalpha.ops.logging import redact_text
from mytradingalpha.research.cached_response import CachedGraphResponse

from .evidence_tools import (
    AmbiguousEvidenceReferenceError,
    CrossBundleEvidenceError,
    DuplicateEvidenceReferenceError,
    EvidenceToolError,
    EvidenceToolset,
    IneligibleEvidenceReferenceError,
    MalformedEvidenceReferenceError,
    MissingEvidenceReferenceError,
)


class ResearchNoteError(ValueError):
    """Base class for typed ResearchNote construction failures."""


class ResearchNoteInputError(ResearchNoteError):
    """Raised when source fields or claim mappings are malformed."""


class ResearchNoteBindingError(ResearchNoteError):
    """Raised when bundle, context, or cached response bindings disagree."""


class ResearchNoteSerializationError(ResearchNoteError):
    """Raised when note content cannot be represented canonically."""


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


def _copy_bundle(bundle: object) -> EvidenceBundle:
    if type(bundle) is not EvidenceBundle:
        raise ResearchNoteInputError("ResearchNoteBuilder requires an exact EvidenceBundle")
    try:
        return EvidenceBundle.model_validate(bundle.model_dump(mode="python"))
    except (TypeError, ValueError) as exc:
        raise ResearchNoteInputError("ResearchNoteBuilder received an invalid bundle") from exc


def _check_exact_type(value: object, expected: type[Any], label: str) -> None:
    if type(value) is not expected:
        raise ResearchNoteInputError(f"{label} requires an exact {expected.__name__}")


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
    if response.instrument_id not in {item.instrument_id for item in bundle.instruments}:
        raise ResearchNoteBindingError("cached response instrument is not in the sealed bundle")
    if response.trade_date != bundle.knowledge_cutoff.date().isoformat():
        raise ResearchNoteBindingError("cached response trade date does not match bundle cutoff")


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
        self._bundle = _copy_bundle(bundle)
        _check_exact_type(context, RunContext, "context")
        _check_exact_type(response, CachedGraphResponse, "response")
        self._context = context
        self._response = response

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
        if type(claim_citations) is not dict or set(claim_citations) != {"thesis", "risks"}:
            raise ResearchNoteInputError(
                "claim_citations must explicitly map thesis and risks"
            )
        output = self._response.output
        texts: dict[str, str] = {}
        for claim in ("thesis", "risks"):
            field = source_fields[claim]
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
            if not isinstance(references, (tuple, list)) or not references:
                raise ResearchNoteInputError(f"{claim} must cite at least one evidence record")
            try:
                ordered = tuple(
                    sorted(
                        references,
                        key=lambda item: (
                            getattr(item, "domain", ""),
                            getattr(item, "record_id", ""),
                        ),
                    )
                )
            except (AttributeError, TypeError) as exc:
                raise ResearchNoteInputError("claim citations must be structured references") from exc
            for reference in ordered:
                if type(reference) is not EvidenceReference:
                    raise MalformedEvidenceReferenceError(
                        "claim citation must be an exact EvidenceReference"
                    )
                key = _reference_key(reference)
                if key in seen:
                    raise DuplicateEvidenceReferenceError(
                        f"duplicate evidence citation: {reference.domain}/{reference.record_id}"
                    )
                item = toolset.get(reference)
                del item
                seen.add(key)
                citations.append(
                    EvidenceCitation(
                        claim=claim,
                        reference=reference,
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
            "capture_manifest": self._response.capture_manifest,
            "source_agent": source_agent,
            "source_fields": {"thesis": source_fields["thesis"], "risks": source_fields["risks"]},
            "thesis": texts["thesis"],
            "risks": (texts["risks"],),
            "citations": tuple(citations),
        }
        try:
            canonical_input = ResearchNote.model_validate(
                {**base, "note_id": "note-pending"}
            ).model_dump(mode="json")
            note_id = f"note-{hashlib.sha256(_canonical(canonical_input)).hexdigest()}"
            return ResearchNote.model_validate({**base, "note_id": note_id})
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
    "MissingEvidenceReferenceError",
    "ResearchNoteBindingError",
    "ResearchNoteBuilder",
    "ResearchNoteError",
    "ResearchNoteInputError",
    "ResearchNoteSerializationError",
]
