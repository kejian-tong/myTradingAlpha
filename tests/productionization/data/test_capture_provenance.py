"""PIT-01 contract tests for immutable capture provenance and raw storage."""

from __future__ import annotations

import hashlib
import inspect
import json
import socket
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from mytradingalpha.data.capture import CaptureClient, CapturedPayload
from mytradingalpha.data.provenance import SourceManifest
from mytradingalpha.data.raw_store import (
    RawStore,
    RawStoreConflictError,
    RawStoreCorruptionError,
    RawStoreInvalidKeyError,
    RawStoreNotFoundError,
)

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "pit" / "provider_payload.bin"
FIXTURE_SHA256 = "b01abc35a90c73e160dd26c1694a0c4759921534f8c41637f9c143f3006b7569"


def _manifest_fields(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "schema_version": "v1",
        "manifest_id": "capture-alpha-20260115-r7",
        "source": "synthetic-provider",
        "source_locator": "fixture://vendor/payload.bin",
        "fetched_at": "2026-01-15T16:00:00-05:00",
        # Event time is intentionally later than ingestion. PIT-01 preserves it but does
        # not infer a general chronology between event time and provider availability.
        "event_time": "2026-01-20T21:00:00Z",
        "published_at": "2026-01-15T20:55:00Z",
        "available_at": "2026-01-15T20:56:00Z",
        "ingested_at": "2026-01-15T21:02:00Z",
        "terms": "vendor-terms-v3",
        "revision": 7,
    }
    fields.update(overrides)
    return fields


def _capture(
    payload: bytes | bytearray | memoryview | None = None, **overrides: object
) -> CapturedPayload:
    raw = FIXTURE_PATH.read_bytes() if payload is None else payload
    return CaptureClient().capture(raw, **_manifest_fields(**overrides))


def _regular_file_snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }


def _raw_object_path(root: Path, expected: bytes) -> Path:
    matches = [
        path
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink() and path.read_bytes() == expected
    ]
    assert len(matches) == 1, "one content-addressed object must hold each unique payload"
    return matches[0]


def _manifest_path(root: Path, manifest_id: str) -> Path:
    encoded_id = manifest_id.encode()
    matches = [
        path
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink() and encoded_id in path.read_bytes()
    ]
    assert len(matches) == 1, "one durable manifest must map each manifest_id"
    return matches[0]


def test_capture_round_trips_exact_fixture_with_independent_sha256() -> None:
    expected = FIXTURE_PATH.read_bytes()
    captured = _capture()

    assert hashlib.sha256(expected).hexdigest() == FIXTURE_SHA256
    assert captured.raw_bytes == expected
    assert captured.manifest.checksum == f"sha256:{FIXTURE_SHA256}"


def test_capture_api_requires_every_manifest_field_except_checksum_as_explicit_keywords() -> None:
    parameters = inspect.signature(CaptureClient.capture).parameters
    expected_keywords = set(_manifest_fields())

    assert set(parameters) == {"self", "raw_bytes", *expected_keywords}
    assert parameters["raw_bytes"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert all(
        parameters[name].kind is inspect.Parameter.KEYWORD_ONLY for name in expected_keywords
    )
    assert all(parameters[name].default is inspect.Parameter.empty for name in expected_keywords)


def test_capture_preserves_full_provenance_and_normalizes_utc() -> None:
    captured = _capture()
    manifest = captured.manifest

    assert manifest.schema_version == "v1"
    assert manifest.manifest_id == "capture-alpha-20260115-r7"
    assert manifest.source == "synthetic-provider"
    assert manifest.source_locator == "fixture://vendor/payload.bin"
    assert manifest.fetched_at == datetime(2026, 1, 15, 21, 0, tzinfo=timezone.utc)
    assert manifest.event_time == datetime(2026, 1, 20, 21, 0, tzinfo=timezone.utc)
    assert manifest.published_at == datetime(2026, 1, 15, 20, 55, tzinfo=timezone.utc)
    assert manifest.available_at == datetime(2026, 1, 15, 20, 56, tzinfo=timezone.utc)
    assert manifest.ingested_at == datetime(2026, 1, 15, 21, 2, tzinfo=timezone.utc)
    assert manifest.terms == "vendor-terms-v3"
    assert manifest.revision == 7
    assert manifest.model_dump(mode="json")["fetched_at"] == "2026-01-15T21:00:00Z"


@pytest.mark.parametrize("schema_version", [None, "", "v0", "v2", 1])
def test_source_manifest_requires_exact_v1_schema(schema_version: object) -> None:
    fields = _manifest_fields()
    fields["schema_version"] = schema_version

    with pytest.raises(ValidationError):
        CaptureClient().capture(FIXTURE_PATH.read_bytes(), **fields)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fetched_at", 1_768_514_400),
        ("event_time", 1_768_514_400.0),
        ("published_at", "2026-01-15"),
        ("available_at", "2026-01-15T20:56:00"),
        ("ingested_at", "not-a-time"),
        ("fetched_at", datetime(2026, 1, 15, 21, 0)),
    ],
)
def test_source_manifest_rejects_numeric_naive_date_only_and_malformed_timestamps(
    field: str, value: object
) -> None:
    with pytest.raises(ValidationError):
        _capture(**{field: value})


@pytest.mark.parametrize(
    "overrides",
    [
        {"published_at": "2026-01-15T20:57:00Z"},
        {"available_at": "2026-01-15T21:01:00Z"},
        {"fetched_at": "2026-01-15T21:03:00Z"},
        {"published_at": None, "available_at": "2026-01-15T21:01:00Z"},
    ],
)
def test_source_manifest_rejects_impossible_provenance_chronology(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        _capture(**overrides)


@pytest.mark.parametrize("revision", [-1, True, False, 1.0, "7"])
def test_source_manifest_requires_nonnegative_strict_integer_revision(revision: object) -> None:
    with pytest.raises(ValidationError):
        _capture(revision=revision)


@pytest.mark.parametrize("terms", [None, "", "   ", b"vendor-terms-v3"])
def test_source_manifest_requires_nonempty_string_terms_reference(terms: object) -> None:
    with pytest.raises(ValidationError):
        _capture(terms=terms)


@pytest.mark.parametrize(
    "checksum",
    [
        "",
        "sha256:abc",
        f"sha256:{'A' * 64}",
        f"md5:{'0' * 64}",
        "0" * 64,
    ],
)
def test_source_manifest_requires_canonical_sha256_checksum(checksum: str) -> None:
    fields = _manifest_fields()
    with pytest.raises(ValidationError):
        SourceManifest(**fields, checksum=checksum)


@pytest.mark.parametrize(
    "checksum",
    [
        f"prefix-sha256:{'0' * 64}",
        f"sha256:{'0' * 64}-suffix",
        f" sha256:{'0' * 64}",
        f"sha256:{'0' * 64} ",
        f"\nsha256:{'0' * 64}",
        f"sha256:{'0' * 64}\n",
    ],
)
def test_source_manifest_rejects_content_around_canonical_checksum(checksum: str) -> None:
    with pytest.raises(ValidationError):
        SourceManifest(**_manifest_fields(), checksum=checksum)


def test_capture_defensively_copies_mutable_bytes_and_accepts_memoryview() -> None:
    mutable = bytearray(FIXTURE_PATH.read_bytes())
    captured = _capture(mutable)
    mutable[:] = b"mutated after capture"

    assert captured.raw_bytes == FIXTURE_PATH.read_bytes()
    assert isinstance(captured.raw_bytes, bytes)
    assert _capture(memoryview(FIXTURE_PATH.read_bytes())).raw_bytes == FIXTURE_PATH.read_bytes()


def test_capture_rejects_non_bytes_payload() -> None:
    with pytest.raises(TypeError):
        CaptureClient().capture("not bytes", **_manifest_fields())  # type: ignore[arg-type]


def test_manifest_and_captured_payload_are_frozen_and_forbid_extra_fields() -> None:
    captured = _capture()

    with pytest.raises(ValidationError):
        captured.manifest.source = "changed"
    with pytest.raises(ValidationError):
        captured.raw_bytes = b"changed"
    with pytest.raises(ValidationError):
        SourceManifest.model_validate(
            {**captured.manifest.model_dump(), "transport_headers": {"Authorization": "secret"}}
        )
    with pytest.raises(ValidationError):
        CapturedPayload.model_validate(
            {"manifest": captured.manifest, "raw_bytes": captured.raw_bytes, "extra": True}
        )


def test_captured_payload_refuses_checksum_mismatch() -> None:
    captured = _capture()

    with pytest.raises(ValidationError):
        CapturedPayload(manifest=captured.manifest, raw_bytes=b"different bytes")


def test_capture_contract_has_no_transport_secret_or_header_credentials() -> None:
    forbidden_fragments = {"secret", "credential", "password", "token", "header", "auth"}
    manifest_fields = set(SourceManifest.model_fields)
    capture_parameters = set(inspect.signature(CaptureClient.capture).parameters)

    assert not any(
        fragment in name.lower()
        for name in manifest_fields | capture_parameters
        for fragment in forbidden_fragments
    )


def test_capture_performs_no_network_io(monkeypatch: pytest.MonkeyPatch) -> None:
    def deny_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("capture must not open a socket")

    monkeypatch.setattr(socket, "socket", deny_network)
    monkeypatch.setattr(socket, "create_connection", deny_network)

    assert _capture().raw_bytes == FIXTURE_PATH.read_bytes()


def test_raw_store_put_get_is_create_only_and_idempotent(tmp_path: Path) -> None:
    store = RawStore(tmp_path / "raw-store")
    captured = _capture()

    store.put(captured)
    before = _regular_file_snapshot(tmp_path / "raw-store")
    store.put(captured)

    assert _regular_file_snapshot(tmp_path / "raw-store") == before
    assert store.get(captured.manifest.manifest_id) == captured


def test_raw_store_deduplicates_bytes_across_independent_manifests(tmp_path: Path) -> None:
    store = RawStore(tmp_path / "raw-store")
    first = _capture(manifest_id="capture-alpha-a")
    second = _capture(manifest_id="capture-alpha-b", source_locator="fixture://mirror/payload.bin")

    store.put(first)
    store.put(second)

    assert store.get(first.manifest.manifest_id) == first
    assert store.get(second.manifest.manifest_id) == second
    _raw_object_path(tmp_path / "raw-store", FIXTURE_PATH.read_bytes())


@pytest.mark.parametrize(
    "replacement",
    [
        _capture(source_locator="fixture://changed/payload.bin"),
        _capture(payload=b"changed payload"),
    ],
)
def test_raw_store_conflict_preserves_original_without_partial_writes(
    tmp_path: Path, replacement: CapturedPayload
) -> None:
    store = RawStore(tmp_path / "raw-store")
    original = _capture()
    store.put(original)
    before = _regular_file_snapshot(tmp_path / "raw-store")

    with pytest.raises(RawStoreConflictError):
        store.put(replacement)

    assert store.get(original.manifest.manifest_id) == original
    assert _regular_file_snapshot(tmp_path / "raw-store") == before


def test_raw_store_serializes_competing_create_only_writers(tmp_path: Path) -> None:
    store = RawStore(tmp_path / "raw-store")
    candidates = (_capture(payload=b"candidate one"), _capture(payload=b"candidate two"))

    def put(candidate: CapturedPayload) -> str:
        try:
            store.put(candidate)
        except RawStoreConflictError:
            return "conflict"
        return "stored"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(put, candidates))

    assert sorted(outcomes) == ["conflict", "stored"]
    assert store.get(candidates[0].manifest.manifest_id) in candidates


@pytest.mark.parametrize("manifest_id", ["", "../escape", "a/b", "/absolute", ".", ".."])
def test_raw_store_rejects_invalid_or_traversal_keys(tmp_path: Path, manifest_id: str) -> None:
    store = RawStore(tmp_path / "raw-store")

    with pytest.raises(RawStoreInvalidKeyError):
        store.get(manifest_id)


def test_raw_store_rejects_invalid_key_even_on_bypassed_model_validation(tmp_path: Path) -> None:
    store = RawStore(tmp_path / "raw-store")
    captured = _capture()
    invalid_manifest = captured.manifest.model_copy(update={"manifest_id": "../escape"})
    invalid_capture = captured.model_copy(update={"manifest": invalid_manifest})

    with pytest.raises(RawStoreInvalidKeyError):
        store.put(invalid_capture)


def test_raw_store_missing_manifest_fails_closed(tmp_path: Path) -> None:
    store = RawStore(tmp_path / "raw-store")

    with pytest.raises(RawStoreNotFoundError):
        store.get("capture-does-not-exist")


@pytest.mark.parametrize("mutation", ["tamper", "truncate"])
def test_raw_store_detects_payload_tamper_or_truncation(tmp_path: Path, mutation: str) -> None:
    root = tmp_path / "raw-store"
    store = RawStore(root)
    captured = _capture()
    store.put(captured)
    object_path = _raw_object_path(root, captured.raw_bytes)
    if mutation == "tamper":
        object_path.write_bytes(b"tampered" + captured.raw_bytes)
    else:
        object_path.write_bytes(captured.raw_bytes[:-5])

    with pytest.raises(RawStoreCorruptionError):
        store.get(captured.manifest.manifest_id)


def test_raw_store_detects_valid_json_manifest_tamper(tmp_path: Path) -> None:
    root = tmp_path / "raw-store"
    store = RawStore(root)
    captured = _capture()
    store.put(captured)
    manifest_path = _manifest_path(root, captured.manifest.manifest_id)
    original = manifest_path.read_bytes()
    tampered = original.replace(b"fixture://vendor/payload.bin", b"fixture://tampered/payload.bin")
    assert tampered != original
    assert json.loads(tampered)
    manifest_path.write_bytes(tampered)

    with pytest.raises(RawStoreCorruptionError):
        store.get(captured.manifest.manifest_id)


@pytest.mark.parametrize("entry", ["manifest", "object"])
def test_raw_store_rejects_symlink_entries(tmp_path: Path, entry: str) -> None:
    root = tmp_path / "raw-store"
    store = RawStore(root)
    captured = _capture()
    store.put(captured)
    path = (
        _manifest_path(root, captured.manifest.manifest_id)
        if entry == "manifest"
        else _raw_object_path(root, captured.raw_bytes)
    )
    external = tmp_path / f"external-{entry}"
    external.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(external)

    with pytest.raises(RawStoreCorruptionError):
        store.get(captured.manifest.manifest_id)


def test_raw_store_rejects_nonregular_manifest_entry(tmp_path: Path) -> None:
    root = tmp_path / "raw-store"
    store = RawStore(root)
    captured = _capture()
    store.put(captured)
    manifest_path = _manifest_path(root, captured.manifest.manifest_id)
    manifest_path.unlink()
    manifest_path.mkdir()

    with pytest.raises(RawStoreCorruptionError):
        store.get(captured.manifest.manifest_id)


@pytest.mark.parametrize("operation", ["put", "get"])
def test_raw_store_rejects_retargeted_ancestor_symlink(
    tmp_path: Path, operation: str
) -> None:
    original_parent = tmp_path / "original-parent"
    outside_parent = tmp_path / "outside-parent"
    original_parent.mkdir()
    outside_parent.mkdir()
    alias = tmp_path / "store-alias"
    alias.symlink_to(original_parent, target_is_directory=True)
    store = RawStore(alias / "raw-store")
    original = _capture()
    store.put(original)
    original_root = original_parent / "raw-store"
    before = _regular_file_snapshot(original_root)

    alias.unlink()
    alias.symlink_to(outside_parent, target_is_directory=True)

    with pytest.raises(RawStoreCorruptionError):
        if operation == "put":
            store.put(_capture(manifest_id="capture-after-retarget"))
        else:
            store.get(original.manifest.manifest_id)

    assert _regular_file_snapshot(original_root) == before
    assert not list(outside_parent.rglob("*"))


@pytest.mark.parametrize(
    "non_directory",
    [
        "root",
        "objects",
        "objects/sha256",
        "manifests",
        "locks",
    ],
)
def test_raw_store_put_translates_non_directory_boundaries(
    tmp_path: Path, non_directory: str
) -> None:
    root = tmp_path / "raw-store"
    store = RawStore(root)
    boundary = root if non_directory == "root" else root / non_directory
    boundary.parent.mkdir(parents=True, exist_ok=True)
    boundary.write_bytes(b"not a directory")

    with pytest.raises(RawStoreCorruptionError):
        store.put(_capture())


def test_raw_store_exposes_no_mutation_or_enumeration_api() -> None:
    assert not {"delete", "list", "repair"}.intersection(vars(RawStore))
