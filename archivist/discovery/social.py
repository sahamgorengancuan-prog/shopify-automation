"""X and Meta — the other two places a trend proves it has an audience.

Both are gated behind paid or business-account credentials, which is a fact of
the platforms, not a shortcut here:

* **X**    ``X_BEARER_TOKEN`` → /2/tweets/search/recent. ``impression_count`` is
           only returned for tweets the token owns, so "average views" falls back
           to a like/repost/reply composite when it is absent.
* **Meta** ``META_ACCESS_TOKEN`` + ``META_IG_USER_ID`` → the Instagram Graph
           hashtag endpoints (business/creator account required).

Without credentials each returns ``ok=False`` with the reason, the discovery
engine drops that source's weight, and the remaining sources decide.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from .. import http

X_SEARCH = "https://api.x.com/2/tweets/search/recent"
GRAPH = "https://graph.facebook.com/v21.0"


@dataclass
class SocialHeat:
    platform: str
    query: str
    posts: int = 0
    avg_engagement: float = 0.0
    avg_views: float = 0.0
    heat: float = 0.0            # 0..100
    top: list[dict[str, Any]] = field(default_factory=list)
    ok: bool = True
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform, "posts": self.posts,
            "avg_engagement": round(self.avg_engagement, 1),
            "avg_views": round(self.avg_views, 1), "heat": round(self.heat, 1),
            "ok": self.ok, "error": self.error,
        }


def _normalise(value: float, ceiling: float) -> float:
    """Log-scaled 0..1 — social metrics are heavy-tailed, linear scaling lies."""
    if value <= 0:
        return 0.0
    return min(1.0, math.log10(1 + value) / math.log10(1 + ceiling))


class XSignals:
    name = "x"

    def __init__(self, *, bearer_token: str = "", timeout: int = 30):
        self.bearer_token = bearer_token
        self.timeout = timeout
        self.last_error = ""

    @property
    def configured(self) -> bool:
        return bool(self.bearer_token)

    def heat(self, query: str, *, max_results: int = 50) -> SocialHeat:
        if not self.configured:
            return SocialHeat("x", query, ok=False, error="X_BEARER_TOKEN not set")
        try:
            payload = http.get_json(
                X_SEARCH,
                params={
                    "query": f"{query} -is:retweet lang:en",
                    "max_results": max(10, min(100, max_results)),
                    "tweet.fields": "public_metrics,created_at",
                },
                headers={"Authorization": f"Bearer {self.bearer_token}"},
                timeout=self.timeout,
                retries=2,
            )
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return SocialHeat("x", query, ok=False, error=self.last_error)

        tweets = payload.get("data", []) or []
        if not tweets:
            return SocialHeat("x", query, posts=0, ok=True, error="no recent posts")

        engagements: list[float] = []
        views: list[float] = []
        for tweet in tweets:
            metrics = tweet.get("public_metrics", {}) or {}
            engagement = (
                float(metrics.get("like_count", 0))
                + 2 * float(metrics.get("retweet_count", 0))
                + 2 * float(metrics.get("reply_count", 0))
                + float(metrics.get("quote_count", 0))
            )
            engagements.append(engagement)
            impressions = metrics.get("impression_count")
            # Impressions are only exposed for the token's own tweets; estimate
            # otherwise rather than reporting a zero that looks like "no reach".
            views.append(float(impressions) if impressions else engagement * 45)

        avg_engagement = sum(engagements) / len(engagements)
        avg_views = sum(views) / len(views)
        volume = min(1.0, len(tweets) / float(max_results))
        heat = 100.0 * (0.45 * volume + 0.35 * _normalise(avg_engagement, 2000) + 0.20 * _normalise(avg_views, 200_000))

        return SocialHeat(
            "x", query, posts=len(tweets),
            avg_engagement=round(avg_engagement, 1), avg_views=round(avg_views, 1),
            heat=round(heat, 1),
            top=[{"text": t.get("text", "")[:140]} for t in tweets[:3]],
        )

    def check(self) -> tuple[bool, str]:
        if not self.configured:
            return False, "X_BEARER_TOKEN not set (optional — Reddit and Trends still decide)"
        result = self.heat("design", max_results=10)
        return result.ok, result.error or f"ok — {result.posts} recent posts on a probe query"


class MetaSignals:
    """Instagram hashtag insights through the Meta Graph API."""

    name = "meta"

    def __init__(self, *, access_token: str = "", ig_user_id: str = "", timeout: int = 30):
        self.access_token = access_token
        self.ig_user_id = ig_user_id
        self.timeout = timeout
        self.last_error = ""

    @property
    def configured(self) -> bool:
        return bool(self.access_token and self.ig_user_id)

    @staticmethod
    def hashtag(query: str) -> str:
        return re.sub(r"[^a-z0-9]", "", query.lower())[:60]

    def _hashtag_id(self, tag: str) -> str:
        payload = http.get_json(
            f"{GRAPH}/ig_hashtag_search",
            params={"user_id": self.ig_user_id, "q": tag, "access_token": self.access_token},
            timeout=self.timeout, retries=2,
        )
        data = payload.get("data", []) or []
        if not data:
            raise http.HttpError(f"no Instagram hashtag matched #{tag}")
        return str(data[0].get("id", ""))

    def heat(self, query: str, *, limit: int = 25) -> SocialHeat:
        if not self.configured:
            return SocialHeat("meta", query, ok=False, error="META_ACCESS_TOKEN / META_IG_USER_ID not set")
        tag = self.hashtag(query)
        if not tag:
            return SocialHeat("meta", query, ok=False, error="topic has no usable hashtag form")
        try:
            hashtag_id = self._hashtag_id(tag)
            payload = http.get_json(
                f"{GRAPH}/{hashtag_id}/top_media",
                params={
                    "user_id": self.ig_user_id,
                    "fields": "like_count,comments_count,caption,permalink",
                    "limit": limit,
                    "access_token": self.access_token,
                },
                timeout=self.timeout, retries=2,
            )
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return SocialHeat("meta", query, ok=False, error=self.last_error)

        media = payload.get("data", []) or []
        if not media:
            return SocialHeat("meta", query, posts=0, ok=True, error=f"#{tag} has no top media")

        engagements = [
            float(item.get("like_count") or 0) + 3 * float(item.get("comments_count") or 0)
            for item in media
        ]
        avg_engagement = sum(engagements) / len(engagements)
        # Instagram does not expose views for hashtag media; reach is estimated
        # from engagement so the number is comparable, never presented as truth.
        avg_views = avg_engagement * 30
        volume = min(1.0, len(media) / float(limit))
        heat = 100.0 * (0.35 * volume + 0.45 * _normalise(avg_engagement, 20_000) + 0.20 * _normalise(avg_views, 500_000))

        return SocialHeat(
            "meta", query, posts=len(media),
            avg_engagement=round(avg_engagement, 1), avg_views=round(avg_views, 1),
            heat=round(heat, 1),
            top=[{"url": item.get("permalink", "")} for item in media[:3]],
        )

    def check(self) -> tuple[bool, str]:
        if not self.configured:
            return False, "META_ACCESS_TOKEN / META_IG_USER_ID not set (optional)"
        result = self.heat("design", limit=5)
        return result.ok, result.error or f"ok — #{self.hashtag('design')} returned {result.posts} media"
