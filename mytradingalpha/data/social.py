"""Captured social-post contracts and point-in-time historical selection."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import (
    BeforeValidator,
    Field,
    StrictInt,
    StrictStr,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from mytradingalpha.contracts.common import StableId, UtcDateTime
from mytradingalpha.contracts.schemas import ContractModel
from mytradingalpha.contracts.versions import CURRENT_SCHEMA_VERSION

from .events import HistoricalReplayBlockedError, ReplayPolicy
from .provenance import SourceManifest

_STABLE_ID_ADAPTER = TypeAdapter(StableId)
_UTC_DATETIME_ADAPTER = TypeAdapter(UtcDateTime)


def _validate_required_text(value: object) -> object:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("invalid_text: expected a non-empty trimmed string")
    return value


RequiredText = Annotated[StrictStr, BeforeValidator(_validate_required_text)]


class SocialRepositoryError(ValueError):
    """Base class for public historical social query failures."""


class SocialMissingError(SocialRepositoryError):
    """Raised when no social series matches every explicit selector."""


class SocialFutureError(SocialRepositoryError):
    """Raised when matching posts exist but none is available by the cutoff."""


class SocialHistoricalReplayBlockedError(
    SocialRepositoryError,
    HistoricalReplayBlockedError,
):
    """Raised when current-only social evidence is requested historically."""


class SocialQueryError(SocialRepositoryError):
    """Raised when a social query or repository state is invalid."""


class SocialPlatform(str, Enum):
    """Stable supported social platform identifiers."""

    STOCKTWITS = "stocktwits"
    REDDIT = "reddit"


class SocialPost(ContractModel):
    """One immutable captured social-post revision."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    post_id: StableId
    instrument_id: StableId
    platform: SocialPlatform
    text: RequiredText
    score: StrictInt = Field(ge=0)
    comments: StrictInt = Field(ge=0)
    replay_policy: ReplayPolicy
    manifest: SourceManifest

    @field_validator("manifest", mode="before")
    @classmethod
    def revalidate_manifest(cls, value: object) -> SourceManifest:
        return SourceManifest.model_validate(
            value.model_dump(mode="python") if isinstance(value, SourceManifest) else value
        )

    @model_validator(mode="after")
    def validate_post_time(self) -> SocialPost:
        if self.manifest.event_time is None:
            raise ValueError("social_event_time_required")
        if self.manifest.published_at is None:
            raise ValueError("social_publication_required")
        if self.manifest.event_time != self.manifest.published_at:
            raise ValueError("social_event_time_must_equal_publication_time")
        return self


def _post_series_key(post: SocialPost) -> tuple[object, ...]:
    return (
        post.post_id,
        post.instrument_id,
        post.platform,
        post.manifest.source,
        post.manifest.event_time,
        post.replay_policy,
    )


def _post_sort_key(post: SocialPost) -> tuple[object, ...]:
    return (
        post.manifest.event_time,
        post.post_id,
        post.manifest.revision,
        post.manifest.source,
    )


def _query_stable_id(value: object, *, field: str) -> str:
    try:
        return _STABLE_ID_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise SocialQueryError(f"invalid_{field}: expected a stable identifier") from exc


def _query_cutoff(value: object) -> datetime:
    try:
        return _UTC_DATETIME_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise SocialQueryError("invalid_knowledge_cutoff: expected an aware ISO timestamp") from exc


def _query_platform(value: object) -> SocialPlatform:
    if isinstance(value, SocialPlatform):
        return value
    if isinstance(value, str):
        try:
            return SocialPlatform(value)
        except ValueError as exc:
            raise SocialQueryError("invalid_platform") from exc
    raise SocialQueryError("invalid_platform")


class SocialRepository(ContractModel):
    """A frozen, canonical collection of captured social-post revisions."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    posts: tuple[SocialPost, ...]

    @field_validator("posts", mode="before")
    @classmethod
    def revalidate_and_sort_posts(cls, value: object) -> tuple[SocialPost, ...]:
        if not isinstance(value, (tuple, list)):
            raise ValueError("invalid_posts: expected a social-post sequence")
        posts = tuple(
            SocialPost.model_validate(
                item.model_dump(mode="python") if isinstance(item, SocialPost) else item
            )
            for item in value
        )
        return tuple(sorted(posts, key=_post_sort_key))

    @model_validator(mode="after")
    def validate_repository(self) -> SocialRepository:
        business_revisions: set[tuple[str, int]] = set()
        by_post_id: dict[str, list[SocialPost]] = {}
        for post in self.posts:
            business_revision = (post.post_id, post.manifest.revision)
            if business_revision in business_revisions:
                raise ValueError("duplicate_post_id_revision")
            business_revisions.add(business_revision)
            by_post_id.setdefault(post.post_id, []).append(post)

        for series in by_post_id.values():
            first_key = _post_series_key(series[0])
            previous: SocialPost | None = None
            for post in sorted(series, key=lambda item: item.manifest.revision):
                if _post_series_key(post) != first_key:
                    raise ValueError("social_revision_series_mismatch")
                if (
                    previous is not None
                    and post.manifest.available_at < previous.manifest.available_at
                ):
                    raise ValueError("social_revision_chronology_regressed")
                previous = post
        return self

    def as_of(
        self,
        instrument_id: str,
        *,
        knowledge_cutoff: datetime | str,
        source: str,
        platform: SocialPlatform | str,
    ) -> tuple[SocialPost, ...]:
        """Return deterministic archived post revisions for one exact source series."""

        repository = self._revalidate_for_query()
        return repository._select_as_of(
            instrument_id,
            knowledge_cutoff=knowledge_cutoff,
            source=source,
            platform=platform,
        )

    def _revalidate_for_query(self) -> SocialRepository:
        try:
            return SocialRepository.model_validate(self.model_dump(mode="python"))
        except (TypeError, ValidationError, ValueError) as exc:
            raise SocialQueryError("invalid_social_repository_state") from exc

    def _select_as_of(
        self,
        instrument_id: object,
        *,
        knowledge_cutoff: object,
        source: object,
        platform: object,
    ) -> tuple[SocialPost, ...]:
        query_instrument = _query_stable_id(instrument_id, field="instrument_id")
        cutoff = _query_cutoff(knowledge_cutoff)
        query_source = _query_stable_id(source, field="source")
        query_platform = _query_platform(platform)

        matching = tuple(
            post
            for post in self.posts
            if post.instrument_id == query_instrument
            and post.manifest.source == query_source
            and post.platform is query_platform
        )
        if not matching:
            raise SocialMissingError("no social posts match the exact query")
        if any(post.replay_policy is ReplayPolicy.LIVE_NOW_ONLY for post in matching):
            raise SocialHistoricalReplayBlockedError(
                "live-now-only social evidence cannot be replayed historically"
            )

        eligible = tuple(post for post in matching if post.manifest.available_at <= cutoff)
        if not eligible:
            raise SocialFutureError("matching social posts are unavailable at the cutoff")

        selected_by_id: dict[str, SocialPost] = {}
        for post in eligible:
            selected = selected_by_id.get(post.post_id)
            if selected is None or post.manifest.revision > selected.manifest.revision:
                selected_by_id[post.post_id] = post
        return tuple(
            sorted(
                selected_by_id.values(),
                key=lambda post: (post.manifest.event_time, post.post_id),
            )
        )


__all__ = [
    "SocialFutureError",
    "SocialHistoricalReplayBlockedError",
    "SocialMissingError",
    "SocialPlatform",
    "SocialPost",
    "SocialQueryError",
    "SocialRepository",
    "SocialRepositoryError",
]
