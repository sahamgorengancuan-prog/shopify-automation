"""Reddit — where a trend either has a community or does not.

Anonymous JSON endpoints work from a residential IP; from a datacentre they are
often 403'd, so app-only OAuth is used whenever a client id/secret pair is
configured. Either way a failure reports itself instead of raising.
"""

from __future__ import annotations

import base64
import math
import time
from dataclasses import dataclass, field
from typing import Any

from .. import http

ANON_BASE = "https://www.reddit.com"
OAUTH_BASE = "https://oauth.reddit.com"
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
DEFAULT_UA = "archivist/1.0 (trend discovery; +https://github.com/)"


@dataclass
class Post:
    title: str
    score: int
    comments: int
    subreddit: str
    created_utc: float
    permalink: str
    upvote_ratio: float = 0.0

    @property
    def engagement(self) -> int:
        return self.score + self.comments * 2  # a comment is worth more than an upvote

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title, "score": self.score, "comments": self.comments,
            "subreddit": self.subreddit, "url": f"https://reddit.com{self.permalink}",
        }


@dataclass
class RedditHeat:
    query: str
    posts: int = 0
    avg_score: float = 0.0
    avg_comments: float = 0.0
    avg_engagement: float = 0.0
    subreddits: list[str] = field(default_factory=list)
    recent_share: float = 0.0     # fraction of hits from the last 7 days
    heat: float = 0.0             # 0..100
    top: list[dict[str, Any]] = field(default_factory=list)
    ok: bool = True
    error: str = ""


class Reddit:
    name = "reddit"

    def __init__(
        self,
        *,
        client_id: str = "",
        client_secret: str = "",
        user_agent: str = DEFAULT_UA,
        timeout: int = 30,
        request_delay: float = 0.8,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_agent = user_agent
        self.timeout = timeout
        self.request_delay = request_delay
        self._token = ""
        self._token_expires = 0.0
        self.last_error = ""

    @property
    def authenticated(self) -> bool:
        return bool(self.client_id and self.client_secret)

    # -- transport --------------------------------------------------------
    def _access_token(self) -> str:
        if self._token and time.time() < self._token_expires:
            return self._token
        credentials = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        status, content = http.request(
            "POST",
            TOKEN_URL,
            data=b"grant_type=client_credentials",
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": self.user_agent,
            },
            timeout=self.timeout,
            retries=2,
        )
        if status >= 400:
            raise http.HttpError(f"reddit token -> HTTP {status}", status, content.decode("utf-8", "replace"))
        import json as jsonlib

        payload = jsonlib.loads(content.decode("utf-8", "replace"))
        self._token = payload.get("access_token", "")
        self._token_expires = time.time() + float(payload.get("expires_in", 3600)) - 60
        if not self._token:
            raise http.HttpError("reddit token response had no access_token")
        return self._token

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        time.sleep(self.request_delay)
        if self.authenticated:
            headers = {"Authorization": f"Bearer {self._access_token()}", "User-Agent": self.user_agent}
            url = f"{OAUTH_BASE}{path}"
        else:
            headers = {"User-Agent": self.user_agent}
            url = f"{ANON_BASE}{path}.json"
        return http.get_json(url, params=params, headers=headers, timeout=self.timeout,
                             user_agent=self.user_agent, retries=2)

    @staticmethod
    def _posts(payload: dict[str, Any]) -> list[Post]:
        children = (payload.get("data", {}) or {}).get("children", [])
        posts: list[Post] = []
        for child in children:
            data = child.get("data", {}) or {}
            if data.get("over_18"):
                continue
            posts.append(Post(
                title=str(data.get("title", ""))[:200],
                score=int(data.get("score") or 0),
                comments=int(data.get("num_comments") or 0),
                subreddit=str(data.get("subreddit", "")),
                created_utc=float(data.get("created_utc") or 0),
                permalink=str(data.get("permalink", "")),
                upvote_ratio=float(data.get("upvote_ratio") or 0),
            ))
        return posts

    # -- queries ----------------------------------------------------------
    def search(self, query: str, *, limit: int = 50, period: str = "month", sort: str = "top") -> list[Post]:
        payload = self._get("/search", {
            "q": query, "limit": min(100, limit), "t": period, "sort": sort,
            "raw_json": 1, "type": "link", "include_over_18": "off",
        })
        return self._posts(payload)

    def hot(self, subreddit: str = "all", *, limit: int = 50) -> list[Post]:
        payload = self._get(f"/r/{subreddit}/hot", {"limit": min(100, limit), "raw_json": 1})
        return self._posts(payload)

    def rising(self, subreddit: str = "all", *, limit: int = 50) -> list[Post]:
        payload = self._get(f"/r/{subreddit}/rising", {"limit": min(100, limit), "raw_json": 1})
        return self._posts(payload)

    # -- measurement ------------------------------------------------------
    def heat(self, query: str, *, limit: int = 50) -> RedditHeat:
        try:
            posts = self.search(query, limit=limit, period="month", sort="top")
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return RedditHeat(query=query, ok=False, error=self.last_error)

        if not posts:
            return RedditHeat(query=query, posts=0, heat=0.0, ok=True, error="no posts in the last month")

        now = time.time()
        week = 7 * 24 * 3600
        avg_score = sum(p.score for p in posts) / len(posts)
        avg_comments = sum(p.comments for p in posts) / len(posts)
        avg_engagement = sum(p.engagement for p in posts) / len(posts)
        recent_share = sum(1 for p in posts if now - p.created_utc <= week) / len(posts)
        subreddits = sorted({p.subreddit for p in posts if p.subreddit})

        # Volume, engagement and freshness, each capped so one viral post cannot
        # carry a topic on its own.
        volume = min(1.0, len(posts) / 40.0)
        engagement = min(1.0, math.log10(1 + avg_engagement) / math.log10(5000))
        spread = min(1.0, len(subreddits) / 12.0)
        heat = 100.0 * (0.32 * volume + 0.33 * engagement + 0.20 * recent_share + 0.15 * spread)

        return RedditHeat(
            query=query,
            posts=len(posts),
            avg_score=round(avg_score, 1),
            avg_comments=round(avg_comments, 1),
            avg_engagement=round(avg_engagement, 1),
            subreddits=subreddits[:12],
            recent_share=round(recent_share, 2),
            heat=round(heat, 1),
            top=[p.to_dict() for p in sorted(posts, key=lambda p: -p.engagement)[:3]],
        )

    def check(self) -> tuple[bool, str]:
        try:
            posts = self.search("design", limit=3)
        except Exception as exc:
            mode = "oauth" if self.authenticated else "anonymous"
            return False, f"{mode}: {type(exc).__name__}: {exc}"
        mode = "oauth" if self.authenticated else "anonymous (set REDDIT_CLIENT_ID/SECRET if this is blocked)"
        return bool(posts), f"ok — {mode}, {len(posts)} posts on a probe query"
