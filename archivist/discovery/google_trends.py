"""Google Trends — the primary demand signal.

Google publishes no official Trends API, so this speaks the same endpoints the
website does:

* ``/trending/rss``            what is trending right now, with traffic estimates
* ``/trends/api/explore``      hands out a token per widget for a search term
* ``widgetdata/multiline``     the interest-over-time series behind that token
* ``widgetdata/relatedsearches`` rising related queries, including "Breakout"

All of it is rate limited and occasionally blocked, so every call degrades to an
empty result with a reason rather than raising, and results are cached on disk
for the length of a discovery cycle.
"""

from __future__ import annotations

import json
import random
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import http

BASE = "https://trends.google.com"
RSS = BASE + "/trending/rss"
EXPLORE = BASE + "/trends/api/explore"
MULTILINE = BASE + "/trends/api/widgetdata/multiline"
RELATED = BASE + "/trends/api/widgetdata/relatedsearches"

# Google prefixes its JSON with an anti-hijacking guard.
GUARD = re.compile(r"^\)\]\}',?\s*")

BREAKOUT_VALUE = 5000  # what Google returns instead of a percentage for a breakout


@dataclass
class TrendPoint:
    time: str
    value: float


@dataclass
class InterestSeries:
    keyword: str
    points: list[TrendPoint] = field(default_factory=list)
    ok: bool = True
    error: str = ""

    @property
    def values(self) -> list[float]:
        return [point.value for point in self.points]

    def _mean(self, window: list[float]) -> float:
        return sum(window) / len(window) if window else 0.0

    def growth_pct(self, window: int = 14) -> float:
        """Change from the first weeks of the window to the last, in percent.

        A small floor on the baseline keeps a term that started at zero from
        reporting an infinite rise — that is a new term, not a 10000% winner.
        """
        values = self.values
        if len(values) < window * 2:
            window = max(2, len(values) // 3)
        if len(values) < 4:
            return 0.0
        first = self._mean(values[:window])
        last = self._mean(values[-window:])
        baseline = max(first, 1.5)
        return round((last - baseline) / baseline * 100.0, 1)

    def momentum_pct(self) -> float:
        """Short-term acceleration: the last quarter of the window vs the rest."""
        values = self.values
        if len(values) < 8:
            return 0.0
        cut = max(2, len(values) // 4)
        recent = self._mean(values[-cut:])
        prior = self._mean(values[-cut * 3 : -cut]) or 1.5
        return round((recent - prior) / max(prior, 1.5) * 100.0, 1)

    def mean(self) -> float:
        return round(self._mean(self.values), 1)

    def peak_ratio(self) -> float:
        values = self.values
        peak = max(values) if values else 0.0
        if not peak:
            return 0.0
        recent = self._mean(values[-3:]) if len(values) >= 3 else values[-1]
        return round(recent / peak, 3)


@dataclass
class RisingQuery:
    query: str
    value: int
    breakout: bool = False


def _strip_guard(payload: bytes | str) -> Any:
    text = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else payload
    text = GUARD.sub("", text.strip())
    return json.loads(text)


class GoogleTrends:
    """Small, defensive Google Trends client."""

    name = "google_trends"

    def __init__(
        self,
        *,
        geo: str = "US",
        hl: str = "en-US",
        timeframe: str = "today 3-m",
        timeout: int = 30,
        request_delay: float = 1.2,
        user_agent: str = http.DEFAULT_UA,
        cache_dir: Path | str | None = None,
    ):
        self.geo = geo
        self.hl = hl
        self.timeframe = timeframe
        self.timeout = timeout
        self.request_delay = request_delay
        self.user_agent = user_agent
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.last_error = ""
        self.throttled = 0
        self._session = None
        self._cookies_ready = False
        self._widget_cache: dict[tuple[str, str, str], list[dict[str, Any]]] = {}

    # -- transport --------------------------------------------------------
    @property
    def session(self):
        """A cookie-keeping session; Trends refuses most calls without one."""
        if self._session is None and http.HAVE_REQUESTS:
            self._session = http.requests.Session()  # type: ignore[union-attr]
            self._session.headers.update({"User-Agent": self.user_agent, "Accept-Language": self.hl})
        return self._session

    def _warm_cookies(self) -> None:
        if self._cookies_ready or self.session is None:
            return
        try:
            self.session.get(f"{BASE}/trends/?geo={self.geo}", timeout=self.timeout)
        except Exception:
            pass
        self._cookies_ready = True

    def _get(self, url: str, params: dict[str, Any], *, attempts: int = 3) -> Any:
        """One Trends request, with the throttling this endpoint actually does.

        Trends answers 429 freely and sometimes sends Retry-After. Backing off
        here (rather than failing the caller) is what keeps a long discovery
        cycle from collapsing into partial data.
        """
        self._warm_cookies()
        last_error: Exception | None = None
        for attempt in range(max(1, attempts)):
            time.sleep(self.request_delay)
            try:
                if self.session is not None:
                    response = self.session.get(url, params=params, timeout=self.timeout)
                    status, content, headers = response.status_code, response.content, response.headers
                else:
                    status, content = http.request(
                        "GET", url, params=params, timeout=self.timeout,
                        user_agent=self.user_agent, retries=1,
                    )
                    headers = {}
                if status == 429:
                    self.throttled += 1
                    wait = _retry_after(headers) or (2.0 ** (attempt + 1) + random.random())
                    last_error = http.HttpError(f"{url} -> HTTP 429 (throttled)", 429)
                    if attempt + 1 < attempts:
                        time.sleep(min(30.0, wait))
                        continue
                    raise last_error
                if status >= 400:
                    raise http.HttpError(f"{url} -> HTTP {status}", status)
                return _strip_guard(content)
            except http.HttpError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt + 1 >= attempts:
                    break
                time.sleep(2.0 ** (attempt + 1))
        raise http.HttpError(f"{url}: {last_error}")

    # -- cache ------------------------------------------------------------
    def _cached(self, key: str) -> Any | None:
        if not self.cache_dir:
            return None
        path = self.cache_dir / f"{key}.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _store(self, key: str, value: Any) -> None:
        if not self.cache_dir:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            (self.cache_dir / f"{key}.json").write_text(json.dumps(value), encoding="utf-8")
        except OSError:
            pass

    # -- endpoints --------------------------------------------------------
    def trending_now(self, limit: int = 25) -> list[dict[str, Any]]:
        """What is trending in the region right now, with traffic estimates."""
        try:
            status, content = http.request(
                "GET", RSS, params={"geo": self.geo}, timeout=self.timeout,
                user_agent=self.user_agent, retries=2,
            )
            if status >= 400:
                raise http.HttpError(f"trending rss -> HTTP {status}", status)
            root = ET.fromstring(content)
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return []

        namespace = {"ht": "https://trends.google.com/trending/rss"}
        rows: list[dict[str, Any]] = []
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            if not title:
                continue
            traffic = (item.findtext("ht:approx_traffic", namespaces=namespace) or "").strip()
            news = [
                (node.findtext("ht:news_item_title", namespaces=namespace) or "").strip()
                for node in item.findall("ht:news_item", namespaces=namespace)
            ]
            rows.append({
                "title": title,
                "traffic": _traffic_to_int(traffic),
                "traffic_label": traffic,
                "news": [n for n in news if n][:3],
                "link": (item.findtext("link") or "").strip(),
            })
            if len(rows) >= limit:
                break
        return rows

    def _widgets(self, keyword: str, timeframe: str | None = None) -> list[dict[str, Any]]:
        """Explore tokens for one keyword, cached per process.

        The timeseries and the rising-query widgets come from the *same* explore
        response, so caching halves the requests for every candidate measured.
        """
        cache_key = (keyword, timeframe or self.timeframe, self.geo)
        if cache_key in self._widget_cache:
            return self._widget_cache[cache_key]
        request = {
            "comparisonItem": [
                {"keyword": keyword, "geo": self.geo, "time": timeframe or self.timeframe}
            ],
            "category": 0,
            "property": "",
        }
        payload = self._get(
            EXPLORE, {"hl": self.hl, "tz": "0", "req": json.dumps(request, separators=(",", ":"))}
        )
        widgets = payload.get("widgets", []) if isinstance(payload, dict) else []
        self._widget_cache[cache_key] = widgets
        return widgets

    def compare(self, terms: list[str], *, benchmark: str = "archive",
                timeframe: str | None = None) -> dict[str, float]:
        """Relative search volume for several terms against one shared benchmark.

        Trends only ever returns *relative* numbers, so terms measured in
        different requests are not comparable. Sending them in one comparison
        with a fixed benchmark (benchmark = 100) makes a ranking meaningful —
        and costs one request per four terms instead of one per term.
        """
        terms = [term for term in terms if term]
        if not terms:
            return {}
        payload_terms = [benchmark] + terms
        request = {
            "comparisonItem": [
                {"keyword": term, "geo": self.geo, "time": timeframe or self.timeframe}
                for term in payload_terms
            ],
            "category": 0,
            "property": "",
        }
        explore = self._get(
            EXPLORE, {"hl": self.hl, "tz": "0", "req": json.dumps(request, separators=(",", ":"))}
        )
        widgets = explore.get("widgets", []) if isinstance(explore, dict) else []
        widget = next((item for item in widgets if item.get("id") == "TIMESERIES"), None)
        if widget is None:
            raise http.HttpError("no TIMESERIES widget in the comparison response")

        payload = self._get(
            MULTILINE,
            {
                "hl": self.hl, "tz": "0",
                "req": json.dumps(widget["request"], separators=(",", ":")),
                "token": widget["token"],
            },
        )
        rows = (payload.get("default", {}) or {}).get("timelineData", [])
        columns: dict[str, list[float]] = {term: [] for term in payload_terms}
        for row in rows:
            values = row.get("value", []) or []
            for index, term in enumerate(payload_terms):
                if index < len(values):
                    columns[term].append(float(values[index] or 0))
        means = {term: (sum(values) / len(values) if values else 0.0) for term, values in columns.items()}
        base = means.get(benchmark, 0.0) or 0.01
        return {term: round(100.0 * means.get(term, 0.0) / base, 2) for term in terms}

    def interest_over_time(self, keyword: str, timeframe: str | None = None) -> InterestSeries:
        cache_key = f"series-{_slug(keyword)}-{_slug(timeframe or self.timeframe)}-{self.geo}"
        cached = self._cached(cache_key)
        if cached is not None:
            return InterestSeries(
                keyword=keyword,
                points=[TrendPoint(**point) for point in cached.get("points", [])],
                ok=cached.get("ok", True),
                error=cached.get("error", ""),
            )
        try:
            widgets = self._widgets(keyword, timeframe)
            widget = next((w for w in widgets if w.get("id") == "TIMESERIES"), None)
            if widget is None:
                raise http.HttpError("no TIMESERIES widget in the explore response")
            payload = self._get(
                MULTILINE,
                {
                    "hl": self.hl,
                    "tz": "0",
                    "req": json.dumps(widget["request"], separators=(",", ":")),
                    "token": widget["token"],
                },
            )
            rows = (payload.get("default", {}) or {}).get("timelineData", [])
            points = [
                TrendPoint(time=str(row.get("formattedTime", row.get("time", ""))),
                           value=float((row.get("value") or [0])[0]))
                for row in rows
            ]
            series = InterestSeries(keyword=keyword, points=points, ok=bool(points))
            if not points:
                series.error = "no timeline data (term too rare to chart)"
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            series = InterestSeries(keyword=keyword, ok=False, error=self.last_error)

        self._store(cache_key, {
            "points": [{"time": p.time, "value": p.value} for p in series.points],
            "ok": series.ok, "error": series.error,
        })
        return series

    def rising_queries(self, keyword: str, limit: int = 10) -> list[RisingQuery]:
        """Related searches that are rising fastest — the richest seed source."""
        cache_key = f"rising-{_slug(keyword)}-{self.geo}"
        cached = self._cached(cache_key)
        if cached is not None:
            return [RisingQuery(**row) for row in cached]
        rows: list[RisingQuery] = []
        try:
            widgets = self._widgets(keyword)
            widget = next(
                (w for w in widgets if w.get("id", "").startswith("RELATED_QUERIES")), None
            )
            if widget is not None:
                payload = self._get(
                    RELATED,
                    {
                        "hl": self.hl,
                        "tz": "0",
                        "req": json.dumps(widget["request"], separators=(",", ":")),
                        "token": widget["token"],
                    },
                )
                ranked = (payload.get("default", {}) or {}).get("rankedList", [])
                # rankedList[0] is "top", rankedList[1] is "rising" — we want rising.
                rising = ranked[1] if len(ranked) > 1 else (ranked[0] if ranked else {})
                for row in rising.get("rankedKeyword", [])[:limit]:
                    value = int(row.get("value") or 0)
                    rows.append(RisingQuery(
                        query=str(row.get("query", "")).strip(),
                        value=value,
                        breakout=value >= BREAKOUT_VALUE,
                    ))
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
        rows = [row for row in rows if row.query]
        self._store(cache_key, [{"query": r.query, "value": r.value, "breakout": r.breakout} for r in rows])
        return rows

    def check(self) -> tuple[bool, str]:
        rows = self.trending_now(limit=3)
        if rows:
            return True, f"ok — {len(rows)} trending now in {self.geo}: {rows[0]['title'][:40]}"
        return False, self.last_error or "no trending data returned (rate limited or geo unsupported)"


def _retry_after(headers: Any) -> float:
    """Honour Retry-After when Trends sends it; fall back to exponential backoff."""
    try:
        value = (headers or {}).get("Retry-After") or (headers or {}).get("retry-after")
        return float(value) if value else 0.0
    except (TypeError, ValueError, AttributeError):
        return 0.0


def _traffic_to_int(label: str) -> int:
    """'20K+' -> 20000, '1M+' -> 1000000."""
    match = re.match(r"([\d.,]+)\s*([KMB]?)", (label or "").replace(" ", "").upper())
    if not match:
        return 0
    try:
        number = float(match.group(1).replace(",", ""))
    except ValueError:
        return 0
    return int(number * {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[match.group(2)])


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", urllib.parse.unquote(value).lower()).strip("-")[:60]
