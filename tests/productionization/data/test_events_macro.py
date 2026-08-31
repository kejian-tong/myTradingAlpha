"""PIT-04 contracts for archived news, social, and macro evidence."""

from __future__ import annotations

import builtins
import inspect
import json
import socket
from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

import mytradingalpha.data.events as events_module
import mytradingalpha.data.macro as macro_module
import mytradingalpha.data.social as social_module
from mytradingalpha.data.events import (
    EventFutureError,
    EventKind,
    EventMissingError,
    EventQueryError,
    EventRepository,
    EventRepositoryError,
    HistoricalReplayBlockedError,
    NewsEvent,
    ReplayPolicy,
)
from mytradingalpha.data.macro import (
    MacroFrequency,
    MacroFutureError,
    MacroHistoricalReplayBlockedError,
    MacroMissingError,
    MacroObservation,
    MacroQueryError,
    MacroRepository,
    MacroRepositoryError,
)
from mytradingalpha.data.social import (
    SocialFutureError,
    SocialHistoricalReplayBlockedError,
    SocialMissingError,
    SocialPlatform,
    SocialPost,
    SocialQueryError,
    SocialRepository,
    SocialRepositoryError,
)

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "pit" / "events_social_macro_v1.json"


def _fixture() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _payload(collection: str, index: int) -> dict[str, object]:
    values = _fixture()[collection]
    assert isinstance(values, list)
    payload = deepcopy(values[index])
    assert isinstance(payload, dict)
    return payload


def _event(
    index: int = 0,
    *,
    overrides: dict[str, object] | None = None,
    manifest_overrides: dict[str, object] | None = None,
) -> NewsEvent:
    payload = _payload("events", index)
    if overrides:
        payload.update(overrides)
    manifest = payload["manifest"]
    assert isinstance(manifest, dict)
    if manifest_overrides:
        manifest.update(manifest_overrides)
    return NewsEvent.model_validate(payload)


def _social_post(
    index: int = 0,
    *,
    overrides: dict[str, object] | None = None,
    manifest_overrides: dict[str, object] | None = None,
) -> SocialPost:
    payload = _payload("social_posts", index)
    if overrides:
        payload.update(overrides)
    manifest = payload["manifest"]
    assert isinstance(manifest, dict)
    if manifest_overrides:
        manifest.update(manifest_overrides)
    return SocialPost.model_validate(payload)


def _macro_observation(
    index: int = 0,
    *,
    overrides: dict[str, object] | None = None,
    manifest_overrides: dict[str, object] | None = None,
) -> MacroObservation:
    payload = _payload("macro_observations", index)
    if overrides:
        payload.update(overrides)
    manifest = payload["manifest"]
    assert isinstance(manifest, dict)
    if manifest_overrides:
        manifest.update(manifest_overrides)
    return MacroObservation.model_validate(payload)


def _event_repository(*events: NewsEvent) -> EventRepository:
    return EventRepository(schema_version="v1", events=events)


def _social_repository(*posts: SocialPost) -> SocialRepository:
    return SocialRepository(schema_version="v1", posts=posts)


def _macro_repository(*observations: MacroObservation) -> MacroRepository:
    return MacroRepository(schema_version="v1", observations=observations)


def _event_query(
    repository: EventRepository,
    *,
    start_time: object = "2024-02-01T14:00:00Z",
    end_time: object = "2024-02-01T14:01:00Z",
    knowledge_cutoff: object = "2024-02-01T16:01:00Z",
    source: object = "synthetic-news",
    event_kind: object = EventKind.NEWS,
    instrument_id: object = "AAPL",
) -> tuple[NewsEvent, ...]:
    return repository.as_of(
        start_time,  # type: ignore[arg-type]
        end_time,  # type: ignore[arg-type]
        knowledge_cutoff=knowledge_cutoff,  # type: ignore[arg-type]
        source=source,  # type: ignore[arg-type]
        event_kind=event_kind,  # type: ignore[arg-type]
        instrument_id=instrument_id,  # type: ignore[arg-type]
    )


def _social_query(
    repository: SocialRepository,
    *,
    instrument_id: object = "AAPL",
    knowledge_cutoff: object = "2024-02-01T13:31:00Z",
    source: object = "synthetic-social",
    platform: object = SocialPlatform.REDDIT,
) -> tuple[SocialPost, ...]:
    return repository.as_of(
        instrument_id,  # type: ignore[arg-type]
        knowledge_cutoff=knowledge_cutoff,  # type: ignore[arg-type]
        source=source,  # type: ignore[arg-type]
        platform=platform,  # type: ignore[arg-type]
    )


def _macro_query(
    repository: MacroRepository,
    *,
    series_id: object = "GDP",
    observation_date: object = "2023-10-01",
    knowledge_cutoff: object = "2024-02-28T13:31:00Z",
    source: object = "synthetic-alfred",
    units: object = "usd_billions",
    frequency: object = MacroFrequency.QUARTERLY,
) -> MacroObservation:
    return repository.as_of(
        series_id,  # type: ignore[arg-type]
        observation_date,  # type: ignore[arg-type]
        knowledge_cutoff=knowledge_cutoff,  # type: ignore[arg-type]
        source=source,  # type: ignore[arg-type]
        units=units,  # type: ignore[arg-type]
        frequency=frequency,  # type: ignore[arg-type]
    )


def test_pit_04_enums_have_stable_wire_values() -> None:
    assert {item.value for item in ReplayPolicy} == {"archived", "live_now_only"}
    assert {item.value for item in EventKind} == {"news", "prediction_market"}
    assert {item.value for item in SocialPlatform} == {"stocktwits", "reddit"}
    assert {item.value for item in MacroFrequency} == {
        "daily",
        "weekly",
        "monthly",
        "quarterly",
    }


def test_pit_04_contracts_expose_only_frozen_v1_nested_time_fields() -> None:
    assert set(NewsEvent.model_fields) == {
        "schema_version",
        "event_id",
        "instrument_id",
        "kind",
        "title",
        "body",
        "publisher",
        "url",
        "replay_policy",
        "manifest",
    }
    assert set(SocialPost.model_fields) == {
        "schema_version",
        "post_id",
        "instrument_id",
        "platform",
        "text",
        "score",
        "comments",
        "replay_policy",
        "manifest",
    }
    assert set(MacroObservation.model_fields) == {
        "schema_version",
        "observation_id",
        "series_id",
        "observation_date",
        "value",
        "units",
        "frequency",
        "replay_policy",
        "manifest",
    }
    assert set(EventRepository.model_fields) == {"schema_version", "events"}
    assert set(SocialRepository.model_fields) == {"schema_version", "posts"}
    assert set(MacroRepository.model_fields) == {"schema_version", "observations"}
    assert SocialPost.model_fields["score"].is_required()
    assert SocialPost.model_fields["comments"].is_required()


def test_fixture_round_trips_exact_values_decimal_strings_and_nested_timestamps() -> None:
    event = _event()
    post = _social_post()
    observation = _macro_observation()

    assert event.kind is EventKind.NEWS
    assert event.manifest.event_time == datetime(2024, 2, 1, 14, tzinfo=timezone.utc)
    assert event.manifest.published_at == datetime(2024, 2, 1, 14, 5, tzinfo=timezone.utc)
    assert "event_time" not in event.model_dump(mode="json")
    assert post.platform is SocialPlatform.REDDIT
    assert post.score == 10
    assert post.comments == 2
    assert observation.observation_date == date(2023, 10, 1)
    assert observation.value == Decimal("27957.026")
    assert observation.model_dump(mode="json")["value"] == "27957.026"
    assert NewsEvent.model_validate_json(event.model_dump_json()) == event
    assert SocialPost.model_validate_json(post.model_dump_json()) == post
    assert MacroObservation.model_validate_json(observation.model_dump_json()) == observation


def test_records_manifests_and_repositories_are_deeply_frozen() -> None:
    event = _event()
    post = _social_post()
    observation = _macro_observation()
    event_repository = _event_repository(event)
    social_repository = _social_repository(post)
    macro_repository = _macro_repository(observation)

    with pytest.raises(ValidationError):
        event.title = "changed"
    with pytest.raises(ValidationError):
        post.manifest.source = "changed"
    with pytest.raises(ValidationError):
        observation.value = Decimal("0")
    with pytest.raises(ValidationError):
        event_repository.events = ()
    with pytest.raises(ValidationError):
        social_repository.posts = ()
    with pytest.raises(ValidationError):
        macro_repository.observations = ()


@pytest.mark.parametrize(
    ("factory", "collection"),
    [
        (NewsEvent.model_validate, "events"),
        (SocialPost.model_validate, "social_posts"),
        (MacroObservation.model_validate, "macro_observations"),
    ],
)
def test_records_forbid_extra_fields_and_require_exact_v1_schema(
    factory: object,
    collection: str,
) -> None:
    payload = _payload(collection, 0)
    with pytest.raises(ValidationError):
        factory({**payload, "provider_payload": {}})  # type: ignore[operator]
    payload["schema_version"] = "v2"
    with pytest.raises(ValidationError):
        factory(payload)  # type: ignore[operator]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event_id", ""),
        ("instrument_id", "not stable"),
        ("title", ""),
        ("title", " padded"),
        ("body", " "),
        ("publisher", "Synthetic Wire "),
        ("url", ""),
        ("url", " https://example.invalid/item"),
    ],
)
def test_news_requires_stable_ids_and_nonempty_trimmed_text(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        _event(overrides={field: value})


def test_optional_news_fields_are_explicit_and_validated_when_present() -> None:
    assert _event(overrides={"instrument_id": None, "url": None}).instrument_id is None
    for missing in ("instrument_id", "url"):
        payload = _payload("events", 0)
        payload.pop(missing)
        with pytest.raises(ValidationError):
            NewsEvent.model_validate(payload)


@pytest.mark.parametrize("field", ["event_time", "published_at", "available_at"])
@pytest.mark.parametrize("collection", ["events", "social_posts", "macro_observations"])
def test_every_record_requires_event_publication_and_availability_timestamps(
    collection: str,
    field: str,
) -> None:
    payload = _payload(collection, 0)
    manifest = payload["manifest"]
    assert isinstance(manifest, dict)
    manifest.pop(field)
    model = {
        "events": NewsEvent,
        "social_posts": SocialPost,
        "macro_observations": MacroObservation,
    }[collection]
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize("field", ["event_time", "published_at"])
@pytest.mark.parametrize("collection", ["events", "social_posts", "macro_observations"])
def test_every_record_rejects_explicitly_undated_event_or_publication(
    collection: str,
    field: str,
) -> None:
    payload = _payload(collection, 0)
    manifest = payload["manifest"]
    assert isinstance(manifest, dict)
    manifest[field] = None
    model = {
        "events": NewsEvent,
        "social_posts": SocialPost,
        "macro_observations": MacroObservation,
    }[collection]
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_news_publication_cannot_precede_event_time() -> None:
    with pytest.raises(ValidationError):
        _event(manifest_overrides={"published_at": "2024-02-01T13:59:59Z"})


def test_social_post_time_is_the_equal_nested_event_and_publication_time() -> None:
    post = _social_post()
    assert post.manifest.event_time == post.manifest.published_at
    with pytest.raises(ValidationError):
        _social_post(manifest_overrides={"published_at": "2024-02-01T13:00:00.000001Z"})


@pytest.mark.parametrize("field", ["score", "comments"])
@pytest.mark.parametrize("value", [-1, 1.0, "1", True, False, None])
def test_social_counts_are_required_strict_nonnegative_integers(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        _social_post(overrides={field: value})


@pytest.mark.parametrize("field", ["score", "comments"])
def test_social_counts_have_no_implicit_default(field: str) -> None:
    payload = _payload("social_posts", 0)
    payload.pop(field)
    with pytest.raises(ValidationError):
        SocialPost.model_validate(payload)


@pytest.mark.parametrize("value", [1.25, True, "NaN", "Infinity", "", " 1", None])
def test_macro_value_is_an_exact_finite_decimal(value: object) -> None:
    with pytest.raises(ValidationError):
        _macro_observation(overrides={"value": value})


@pytest.mark.parametrize(
    "observation_date",
    [datetime(2023, 10, 1, tzinfo=timezone.utc), "2023-10-01T00:00:00Z", 20231001],
)
def test_macro_observation_date_is_an_exact_date(observation_date: object) -> None:
    with pytest.raises(ValidationError):
        _macro_observation(overrides={"observation_date": observation_date})


def test_macro_event_utc_date_must_equal_observation_date() -> None:
    with pytest.raises(ValidationError):
        _macro_observation(manifest_overrides={"event_time": "2023-09-30T23:59:59Z"})


def test_macro_publication_cannot_precede_event_time() -> None:
    with pytest.raises(ValidationError):
        _macro_observation(
            manifest_overrides={
                "published_at": "2023-09-30T23:59:59Z",
                "available_at": "2023-10-01T00:00:00Z",
            }
        )


def test_macro_query_cannot_select_bypassed_observation_before_its_event_time() -> None:
    valid = _macro_observation()
    before_event = datetime(2023, 9, 30, 23, 59, 59, tzinfo=timezone.utc)
    invalid_manifest = valid.manifest.model_copy(
        update={"published_at": before_event, "available_at": before_event}
    )
    invalid = valid.model_copy(update={"manifest": invalid_manifest})
    bypassed_repository = _macro_repository(valid).model_copy(
        update={"observations": (invalid,)}
    )

    with pytest.raises(MacroQueryError):
        _macro_query(bypassed_repository, knowledge_cutoff=before_event)


def test_repositories_are_tuples_canonically_sorted_and_round_trip() -> None:
    events = _event_repository(_event(2), _event(1), _event(0))
    posts = _social_repository(_social_post(2), _social_post(1), _social_post(0))
    observations = _macro_repository(_macro_observation(1), _macro_observation(0))

    assert isinstance(events.events, tuple)
    assert isinstance(posts.posts, tuple)
    assert isinstance(observations.observations, tuple)
    assert events == EventRepository.model_validate_json(events.model_dump_json())
    assert posts == SocialRepository.model_validate_json(posts.model_dump_json())
    assert observations == MacroRepository.model_validate_json(observations.model_dump_json())
    assert events.events == _event_repository(*reversed(events.events)).events
    assert posts.posts == _social_repository(*reversed(posts.posts)).posts
    assert (
        observations.observations
        == _macro_repository(*reversed(observations.observations)).observations
    )


@pytest.mark.parametrize("repository_kind", ["event", "social", "macro"])
def test_repositories_reject_duplicate_business_id_revision_pairs(
    repository_kind: str,
) -> None:
    if repository_kind == "event":
        original = _event()
        duplicate = _event(
            overrides={"title": "Duplicate payload"},
            manifest_overrides={"manifest_id": "news-aapl-earnings-duplicate"},
        )
        factory = _event_repository
    elif repository_kind == "social":
        original = _social_post()
        duplicate = _social_post(
            overrides={"text": "Duplicate payload"},
            manifest_overrides={"manifest_id": "reddit-aapl-thread-duplicate"},
        )
        factory = _social_repository
    else:
        original = _macro_observation()
        duplicate = _macro_observation(
            overrides={"value": "1.0"},
            manifest_overrides={"manifest_id": "gdp-2023q4-duplicate"},
        )
        factory = _macro_repository
    with pytest.raises(ValidationError):
        factory(original, duplicate)  # type: ignore[arg-type]


def test_event_repository_public_errors_and_signature_are_stable() -> None:
    assert issubclass(EventMissingError, EventRepositoryError)
    assert issubclass(EventFutureError, EventRepositoryError)
    assert issubclass(HistoricalReplayBlockedError, EventRepositoryError)
    assert issubclass(EventQueryError, EventRepositoryError)
    signature = inspect.signature(EventRepository.as_of)
    assert tuple(signature.parameters) == (
        "self",
        "start_time",
        "end_time",
        "knowledge_cutoff",
        "source",
        "event_kind",
        "instrument_id",
    )
    for name in ("knowledge_cutoff", "source", "event_kind", "instrument_id"):
        assert signature.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
        assert signature.parameters[name].default is inspect.Parameter.empty


def test_event_as_of_uses_half_open_window_inclusive_cutoff_and_highest_revision() -> None:
    repository = _event_repository(_event(2), _event(1), _event(0))

    at_initial = _event_query(repository, knowledge_cutoff="2024-02-01T14:07:00Z")
    assert tuple(item.event_id for item in at_initial) == (
        "news-aapl-earnings",
        "news-aapl-guidance",
    )
    assert at_initial[0].manifest.revision == 0
    after_revision = _event_query(repository)
    assert after_revision[0].manifest.revision == 1
    assert tuple(item.event_id for item in after_revision) == (
        "news-aapl-earnings",
        "news-aapl-guidance",
    )

    with pytest.raises(EventMissingError):
        _event_query(
            repository,
            start_time="2024-02-01T13:59:00Z",
            end_time="2024-02-01T14:00:00Z",
        )
    with pytest.raises(EventMissingError):
        _event_query(
            repository,
            start_time="2024-02-01T14:00:00.000001Z",
            end_time="2024-02-01T14:01:00Z",
        )


def test_event_as_of_distinguishes_future_missing_and_live_only_replay() -> None:
    repository = _event_repository(_event(0), _event(4))

    with pytest.raises(EventFutureError):
        _event_query(repository, knowledge_cutoff="2024-02-01T14:05:59.999999Z")
    with pytest.raises(EventMissingError):
        _event_query(repository, source="other-news")
    with pytest.raises(HistoricalReplayBlockedError):
        _event_query(
            repository,
            start_time="2024-02-01T15:00:00Z",
            end_time="2024-02-01T15:01:00Z",
            knowledge_cutoff="2024-02-01T15:01:00Z",
            source="polymarket-live",
            event_kind=EventKind.PREDICTION_MARKET,
            instrument_id=None,
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"source": "other-news"},
        {"event_kind": EventKind.PREDICTION_MARKET},
        {"instrument_id": "MSFT"},
    ],
)
def test_event_as_of_never_falls_back_across_explicit_selectors(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(EventMissingError):
        _event_query(_event_repository(_event(0), _event(1), _event(2)), **overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"start_time": datetime(2024, 2, 1, 14)},
        {"end_time": "2024-02-01"},
        {"knowledge_cutoff": 1706796000},
        {"source": "not stable"},
        {"event_kind": "social"},
        {"instrument_id": "not stable"},
    ],
)
def test_event_as_of_rejects_malformed_queries(overrides: dict[str, object]) -> None:
    with pytest.raises(EventQueryError):
        _event_query(_event_repository(_event(0)), **overrides)


def test_event_as_of_rejects_empty_or_reversed_windows() -> None:
    repository = _event_repository(_event(0))
    for start, end in (
        ("2024-02-01T14:00:00Z", "2024-02-01T14:00:00Z"),
        ("2024-02-01T14:01:00Z", "2024-02-01T14:00:00Z"),
    ):
        with pytest.raises(EventQueryError):
            _event_query(repository, start_time=start, end_time=end)


def test_social_repository_public_errors_signature_and_revision_selection_are_stable() -> None:
    assert issubclass(SocialMissingError, SocialRepositoryError)
    assert issubclass(SocialFutureError, SocialRepositoryError)
    assert issubclass(SocialHistoricalReplayBlockedError, SocialRepositoryError)
    assert issubclass(SocialQueryError, SocialRepositoryError)
    signature = inspect.signature(SocialRepository.as_of)
    assert tuple(signature.parameters) == (
        "self",
        "instrument_id",
        "knowledge_cutoff",
        "source",
        "platform",
    )
    for name in ("knowledge_cutoff", "source", "platform"):
        assert signature.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
        assert signature.parameters[name].default is inspect.Parameter.empty

    repository = _social_repository(_social_post(2), _social_post(1), _social_post(0))
    before_revision = _social_query(repository, knowledge_cutoff="2024-02-01T13:02:00Z")
    assert tuple(item.post_id for item in before_revision) == (
        "reddit-aapl-thread",
        "reddit-aapl-tied",
    )
    assert before_revision[0].manifest.revision == 0
    after_revision = _social_query(repository)
    assert after_revision[0].manifest.revision == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"instrument_id": "MSFT"},
        {"source": "other-social"},
        {"platform": SocialPlatform.STOCKTWITS},
    ],
)
def test_social_as_of_never_falls_back_across_explicit_selectors(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(SocialMissingError):
        _social_query(_social_repository(_social_post(0), _social_post(1)), **overrides)


def test_social_as_of_distinguishes_future_and_blocks_stocktwits_and_reddit_live() -> None:
    archived = _social_post(0)
    stocktwits = _social_post(3)
    reddit = _social_post(4)
    repository = _social_repository(archived, stocktwits, reddit)

    with pytest.raises(SocialFutureError):
        _social_query(repository, knowledge_cutoff="2024-02-01T13:00:59.999999Z")
    with pytest.raises(SocialHistoricalReplayBlockedError):
        _social_query(
            repository,
            knowledge_cutoff="2024-02-01T13:11:00Z",
            source="stocktwits-live",
            platform=SocialPlatform.STOCKTWITS,
        )
    with pytest.raises(SocialHistoricalReplayBlockedError):
        _social_query(
            repository,
            knowledge_cutoff="2024-02-01T13:21:00Z",
            source="reddit-live",
            platform=SocialPlatform.REDDIT,
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"instrument_id": "not stable"},
        {"knowledge_cutoff": datetime(2024, 2, 1, 13, 31)},
        {"source": ""},
        {"platform": "twitter"},
    ],
)
def test_social_as_of_rejects_malformed_queries(overrides: dict[str, object]) -> None:
    with pytest.raises(SocialQueryError):
        _social_query(_social_repository(_social_post(0)), **overrides)


def test_macro_repository_public_errors_and_signature_are_stable() -> None:
    assert issubclass(MacroMissingError, MacroRepositoryError)
    assert issubclass(MacroFutureError, MacroRepositoryError)
    assert issubclass(MacroHistoricalReplayBlockedError, MacroRepositoryError)
    assert issubclass(MacroQueryError, MacroRepositoryError)
    signature = inspect.signature(MacroRepository.as_of)
    assert tuple(signature.parameters) == (
        "self",
        "series_id",
        "observation_date",
        "knowledge_cutoff",
        "source",
        "units",
        "frequency",
    )
    for name in ("knowledge_cutoff", "source", "units", "frequency"):
        assert signature.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
        assert signature.parameters[name].default is inspect.Parameter.empty


def test_macro_as_of_selects_archived_vintage_by_inclusive_availability() -> None:
    original = _macro_observation(0)
    restatement = _macro_observation(1)
    repository = _macro_repository(restatement, original)

    assert (
        _macro_query(
            repository,
            knowledge_cutoff=original.manifest.available_at,
        ).manifest.revision
        == 0
    )
    selected = _macro_query(repository, knowledge_cutoff=restatement.manifest.available_at)
    assert selected.manifest.revision == 1
    assert selected.value == Decimal("27950.000")


@pytest.mark.parametrize(
    "overrides",
    [
        {"series_id": "DFF"},
        {"observation_date": "2024-02-01"},
        {"source": "other-macro"},
        {"units": "percent"},
        {"frequency": MacroFrequency.DAILY},
    ],
)
def test_macro_as_of_never_falls_back_across_exact_series_selectors(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(MacroMissingError):
        _macro_query(_macro_repository(_macro_observation(0), _macro_observation(1)), **overrides)


def test_macro_as_of_distinguishes_missing_future_and_live_only() -> None:
    archived = _macro_observation(0)
    live = _macro_observation(2)
    repository = _macro_repository(archived, live)

    with pytest.raises(MacroFutureError):
        _macro_query(repository, knowledge_cutoff="2024-01-25T13:30:59.999999Z")
    with pytest.raises(MacroMissingError):
        _macro_query(repository, series_id="CPI")
    with pytest.raises(MacroHistoricalReplayBlockedError):
        _macro_query(
            repository,
            knowledge_cutoff="2024-03-01T13:31:00Z",
            source="fred-live",
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"series_id": "not stable"},
        {"observation_date": datetime(2023, 10, 1, tzinfo=timezone.utc)},
        {"knowledge_cutoff": "2024-02-28"},
        {"source": ""},
        {"units": "not stable"},
        {"frequency": "yearly"},
    ],
)
def test_macro_as_of_rejects_malformed_queries(overrides: dict[str, object]) -> None:
    with pytest.raises(MacroQueryError):
        _macro_query(_macro_repository(_macro_observation(0)), **overrides)


@pytest.mark.parametrize("repository_kind", ["event", "social", "macro"])
def test_public_queries_defensively_revalidate_model_copy_bypasses(
    repository_kind: str,
) -> None:
    if repository_kind == "event":
        valid = _event()
        invalid = valid.model_copy(update={"title": ""})
        repository = _event_repository(valid).model_copy(update={"events": (invalid,)})
        with pytest.raises(EventQueryError):
            _event_query(repository)
    elif repository_kind == "social":
        valid = _social_post()
        invalid = valid.model_copy(update={"score": -1})
        repository = _social_repository(valid).model_copy(update={"posts": (invalid,)})
        with pytest.raises(SocialQueryError):
            _social_query(repository)
    else:
        valid = _macro_observation()
        invalid_manifest = valid.manifest.model_copy(update={"published_at": None})
        invalid = valid.model_copy(update={"manifest": invalid_manifest})
        repository = _macro_repository(valid).model_copy(update={"observations": (invalid,)})
        with pytest.raises(MacroQueryError):
            _macro_query(repository)


@pytest.mark.parametrize("record_kind", ["event", "social", "macro"])
def test_repository_construction_revalidates_supplied_model_candidates(
    record_kind: str,
) -> None:
    if record_kind == "event":
        invalid = _event().model_copy(update={"body": ""})
        with pytest.raises(ValidationError):
            _event_repository(invalid)
    elif record_kind == "social":
        invalid = _social_post().model_copy(update={"comments": -1})
        with pytest.raises(ValidationError):
            _social_repository(invalid)
    else:
        invalid = _macro_observation().model_copy(update={"value": Decimal("NaN")})
        with pytest.raises(ValidationError):
            _macro_repository(invalid)


@pytest.mark.parametrize("repository_kind", ["event", "social", "macro"])
def test_ingested_after_cutoff_remains_eligible_until_pit_06(
    repository_kind: str,
) -> None:
    late_ingestion = "2025-01-01T00:00:00Z"
    if repository_kind == "event":
        item = _event(manifest_overrides={"ingested_at": late_ingestion})
        assert _event_query(
            _event_repository(item), knowledge_cutoff=item.manifest.available_at
        ) == (item,)
    elif repository_kind == "social":
        item = _social_post(manifest_overrides={"ingested_at": late_ingestion})
        assert _social_query(
            _social_repository(item), knowledge_cutoff=item.manifest.available_at
        ) == (item,)
    else:
        item = _macro_observation(manifest_overrides={"ingested_at": late_ingestion})
        assert (
            _macro_query(_macro_repository(item), knowledge_cutoff=item.manifest.available_at)
            == item
        )


def test_pit_04_historical_selection_uses_no_network_file_io_or_wall_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event_repository = _event_repository(_event(0), _event(1), _event(2))
    social_repository = _social_repository(_social_post(0), _social_post(1), _social_post(2))
    macro_repository = _macro_repository(_macro_observation(0), _macro_observation(1))

    def deny_side_effect(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("PIT-04 historical selection attempted an external side effect")

    monkeypatch.setattr(socket, "socket", deny_side_effect)
    monkeypatch.setattr(builtins, "open", deny_side_effect)
    for module in (events_module, social_module, macro_module):
        if hasattr(module, "time"):
            monkeypatch.setattr(module.time, "time", deny_side_effect)  # type: ignore[attr-defined]

    assert _event_query(event_repository)[0].manifest.revision == 1
    assert _social_query(social_repository)[0].manifest.revision == 1
    assert _macro_query(macro_repository).manifest.revision == 1


def test_pit_04_does_not_pull_forward_generic_observation_or_provider_adapters() -> None:
    for module in (events_module, social_module, macro_module):
        assert not hasattr(module, "Observation")
        assert not hasattr(module, "HistoricalDataProvider")
        assert not hasattr(module, "EvidenceBundle")
