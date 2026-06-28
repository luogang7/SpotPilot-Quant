from __future__ import annotations

import html
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx

from app.core.config import Settings
from app.domain.models import NewsArticle, NewsSentimentSummary, RiskLevel, SentimentLabel


POSITIVE_KEYWORDS = {
    "accumulate",
    "accumulation",
    "adopt",
    "adoption",
    "approval",
    "approve",
    "ath",
    "bull",
    "bullish",
    "buy",
    "etf inflow",
    "gain",
    "gains",
    "growth",
    "inflow",
    "launch",
    "legal win",
    "partnership",
    "rally",
    "rebound",
    "record high",
    "reserve",
    "rise",
    "surge",
    "upgrade",
}

NEGATIVE_KEYWORDS = {
    "bankrupt",
    "bankruptcy",
    "ban",
    "bear",
    "bearish",
    "breach",
    "crackdown",
    "crash",
    "depeg",
    "delist",
    "delisting",
    "drain",
    "exploit",
    "fine",
    "fraud",
    "hack",
    "insolvency",
    "investigation",
    "lawsuit",
    "liquidation",
    "outage",
    "outflow",
    "plunge",
    "probe",
    "regulatory",
    "sanction",
    "sanctions",
    "sec",
    "selloff",
    "slump",
}

EVENT_RISK_KEYWORDS = {
    "bankruptcy",
    "ban",
    "breach",
    "crackdown",
    "depeg",
    "delisting",
    "exploit",
    "fraud",
    "hack",
    "investigation",
    "lawsuit",
    "liquidation",
    "outage",
    "probe",
    "regulatory",
    "sanctions",
    "sec",
}

SYMBOL_ALIASES: dict[str, set[str]] = {
    "BTC": {"btc", "bitcoin", "xbt"},
    "ETH": {"eth", "ether", "ethereum"},
    "SOL": {"sol", "solana"},
    "BNB": {"bnb", "binance coin"},
    "XRP": {"xrp", "ripple"},
    "DOGE": {"doge", "dogecoin"},
    "ADA": {"ada", "cardano"},
    "USDT": {"usdt", "tether"},
    "USDC": {"usdc", "usd coin"},
}

GENERAL_CRYPTO_TERMS = {"crypto", "cryptocurrency", "digital asset", "stablecoin", "bitcoin"}
MARKET_SYMBOL = "MARKET"
TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class RawNewsArticle:
    source: str
    title: str
    url: str
    published_at: datetime | None = None
    summary: str = ""


class CryptoNewsSentimentAnalyzer:
    def analyze_article(self, article: RawNewsArticle, requested_symbol: str) -> NewsArticle:
        text = self._analysis_text(article)
        positive = self._matches(text, POSITIVE_KEYWORDS)
        negative = self._matches(text, NEGATIVE_KEYWORDS)
        event_matches = self._matches(text, EVENT_RISK_KEYWORDS)
        symbols = self._detect_symbols(text)
        score = self._score(positive=positive, negative=negative, event_matches=event_matches)
        label = self._label(score)

        return NewsArticle(
            source=article.source,
            title=article.title,
            url=article.url,
            published_at=article.published_at,
            summary=article.summary,
            symbols=symbols or [self._symbol_base(requested_symbol)],
            sentiment_score=score,
            sentiment_label=label,
            event_risk=bool(event_matches),
            matched_keywords=sorted(set([*positive, *negative, *event_matches])),
        )

    def aggregate(
        self,
        symbol: str,
        articles: list[NewsArticle],
        status: str,
        message: str = "",
    ) -> NewsSentimentSummary:
        if not articles:
            return NewsSentimentSummary(
                symbol=symbol,
                sentiment_score=0,
                sentiment_label=SentimentLabel.NEUTRAL,
                risk_level=RiskLevel.MEDIUM if status == "fetch_error" else RiskLevel.LOW,
                event_risk=status == "fetch_error",
                status=status,
                message=message,
                rationale=[message] if message else [],
            )

        weighted_scores = [
            article.sentiment_score * self._recency_weight(article.published_at)
            for article in articles
        ]
        weights = [self._recency_weight(article.published_at) for article in articles]
        aggregate_score = sum(weighted_scores) / max(sum(weights), 1)
        aggregate_score = max(-1, min(1, aggregate_score))
        event_count = sum(1 for article in articles if article.event_risk)
        label = self._label(aggregate_score)
        risk_level = self._risk_level(aggregate_score, event_count)
        top_articles = sorted(
            articles,
            key=lambda item: (
                abs(item.sentiment_score),
                item.published_at or datetime.min.replace(tzinfo=timezone.utc),
            ),
            reverse=True,
        )[:5]
        rationale = [
            (
                f"News sentiment {label.value}: score={aggregate_score:.2f}, "
                f"articles={len(articles)}, event_risk={str(event_count > 0).lower()}."
            ),
            *[
                (
                    f"{article.source}: {article.title} "
                    f"({article.sentiment_label.value} {article.sentiment_score:.2f})"
                )
                for article in top_articles
            ],
        ]
        return NewsSentimentSummary(
            symbol=symbol,
            sentiment_score=round(aggregate_score, 4),
            sentiment_label=label,
            risk_level=risk_level,
            event_risk=event_count > 0,
            article_count=len(articles),
            source_count=len({article.source for article in articles}),
            status=status,
            message=message,
            rationale=rationale,
            articles=articles,
        )

    @staticmethod
    def _analysis_text(article: RawNewsArticle) -> str:
        return f"{article.title} {article.title} {article.summary}".lower()

    @staticmethod
    def _matches(text: str, keywords: set[str]) -> list[str]:
        return [
            keyword
            for keyword in keywords
            if re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text)
        ]

    @staticmethod
    def _score(
        positive: list[str],
        negative: list[str],
        event_matches: list[str],
    ) -> float:
        positive_count = len(positive)
        negative_count = len(negative)
        total = max(positive_count + negative_count, 2)
        score = (positive_count - negative_count) / total
        if event_matches and score > -0.25:
            score -= 0.25
        return round(max(-1, min(1, score)), 4)

    @staticmethod
    def _label(score: float) -> SentimentLabel:
        if score >= 0.15:
            return SentimentLabel.POSITIVE
        if score <= -0.15:
            return SentimentLabel.NEGATIVE
        return SentimentLabel.NEUTRAL

    @staticmethod
    def _risk_level(score: float, event_count: int) -> RiskLevel:
        if score <= -0.75 and event_count >= 2:
            return RiskLevel.EXTREME
        if score <= -0.45 or event_count >= 3:
            return RiskLevel.HIGH
        if score <= -0.2 or event_count:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    @staticmethod
    def _recency_weight(published_at: datetime | None) -> float:
        if published_at is None:
            return 0.75
        now = datetime.now(timezone.utc)
        age_hours = max((now - published_at.astimezone(timezone.utc)).total_seconds() / 3600, 0)
        if age_hours <= 24:
            return 1.0
        if age_hours <= 72:
            return 0.75
        return 0.5

    @staticmethod
    def _detect_symbols(text: str) -> list[str]:
        detected: list[str] = []
        for symbol, aliases in SYMBOL_ALIASES.items():
            if any(
                re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", text)
                for alias in aliases
            ):
                detected.append(symbol)
        return detected

    @staticmethod
    def _symbol_base(symbol: str) -> str:
        return symbol.split("/")[0].upper()


class CryptoNewsService:
    def __init__(
        self,
        settings: Settings,
        client: httpx.Client | None = None,
        analyzer: CryptoNewsSentimentAnalyzer | None = None,
    ) -> None:
        self.settings = settings
        self.client = client
        self.analyzer = analyzer or CryptoNewsSentimentAnalyzer()

    def get_news_sentiment(self, symbol: str, limit: int) -> NewsSentimentSummary:
        if not self.settings.enable_news_sentiment:
            return self.analyzer.aggregate(
                symbol=symbol,
                articles=[],
                status="disabled",
                message="News sentiment is disabled.",
            )

        feed_urls = self._feed_urls()
        if not feed_urls:
            return self.analyzer.aggregate(
                symbol=symbol,
                articles=[],
                status="disabled",
                message="No news RSS feeds configured.",
            )

        raw_articles, failures = self._fetch_feeds(feed_urls)

        deduped = self._dedupe(raw_articles)
        filtered = [
            article
            for article in deduped
            if self._matches_symbol_or_market(article, symbol)
        ][: max(1, limit)]
        articles = [
            self.analyzer.analyze_article(article, requested_symbol=symbol)
            for article in filtered
        ]
        status = "ok" if articles else ("fetch_error" if failures and not raw_articles else "empty")
        message = "; ".join(failures[:3])
        return self.analyzer.aggregate(
            symbol=symbol,
            articles=articles,
            status=status,
            message=message,
        )

    def _fetch_feeds(self, feed_urls: list[str]) -> tuple[list[RawNewsArticle], list[str]]:
        if self.client is not None or len(feed_urls) <= 1:
            return self._fetch_feeds_sequential(feed_urls)

        raw_articles: list[RawNewsArticle] = []
        failures: list[str] = []
        worker_count = min(len(feed_urls), 4)
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_to_url = {
                executor.submit(self._fetch_feed, feed_url): feed_url
                for feed_url in feed_urls
            }
            for future in as_completed(future_to_url):
                feed_url = future_to_url[future]
                try:
                    raw_articles.extend(future.result())
                except (httpx.HTTPError, ElementTree.ParseError, ValueError) as exc:
                    failures.append(f"{self._source_name(feed_url)}: {self._public_error(exc)}")
        return raw_articles, failures

    def _fetch_feeds_sequential(self, feed_urls: list[str]) -> tuple[list[RawNewsArticle], list[str]]:
        raw_articles: list[RawNewsArticle] = []
        failures: list[str] = []
        for feed_url in feed_urls:
            try:
                raw_articles.extend(self._fetch_feed(feed_url))
            except (httpx.HTTPError, ElementTree.ParseError, ValueError) as exc:
                failures.append(f"{self._source_name(feed_url)}: {self._public_error(exc)}")
        return raw_articles, failures

    def _feed_urls(self) -> list[str]:
        return [
            item.strip()
            for item in self.settings.news_feed_urls.split(",")
            if item.strip()
        ]

    def _fetch_feed(self, feed_url: str) -> list[RawNewsArticle]:
        if self.client is not None:
            response = self.client.get(feed_url)
            response.raise_for_status()
            return self._parse_feed(response.text, feed_url)

        with httpx.Client(timeout=self.settings.news_fetch_timeout_seconds) as client:
            response = client.get(feed_url)
            response.raise_for_status()
            return self._parse_feed(response.text, feed_url)

    def _parse_feed(self, text: str, feed_url: str) -> list[RawNewsArticle]:
        root = ElementTree.fromstring(text)
        source = self._source_name(feed_url)
        channel = next(
            (item for item in list(root) if self._local_name(item.tag) == "channel"),
            None,
        )
        if channel is not None:
            return [
                self._parse_rss_item(item, source)
                for item in [
                    child for child in list(channel) if self._local_name(child.tag) == "item"
                ][: self.settings.news_max_articles_per_feed]
            ]

        entries = self._findall_by_local_name(root, "entry")
        return [
            self._parse_atom_entry(entry, source)
            for entry in entries[: self.settings.news_max_articles_per_feed]
        ]

    def _parse_rss_item(self, item: ElementTree.Element, source: str) -> RawNewsArticle:
        title = self._clean_text(self._child_text(item, "title"))
        url = self._clean_text(self._child_text(item, "link"))
        summary = self._clean_text(self._child_text(item, "description"))
        published_at = self._parse_datetime(
            self._child_text(item, "pubDate") or self._child_text(item, "published"),
        )
        item_source = self._clean_text(self._child_text(item, "source")) or source
        return RawNewsArticle(
            source=item_source,
            title=title,
            url=url,
            published_at=published_at,
            summary=summary,
        )

    def _parse_atom_entry(self, entry: ElementTree.Element, source: str) -> RawNewsArticle:
        title = self._clean_text(self._child_text(entry, "title"))
        url = self._atom_link(entry)
        summary = self._clean_text(
            self._child_text(entry, "summary") or self._child_text(entry, "content"),
        )
        published_at = self._parse_datetime(
            self._child_text(entry, "published") or self._child_text(entry, "updated"),
        )
        return RawNewsArticle(
            source=source,
            title=title,
            url=url,
            published_at=published_at,
            summary=summary,
        )

    @staticmethod
    def _dedupe(articles: list[RawNewsArticle]) -> list[RawNewsArticle]:
        deduped: list[RawNewsArticle] = []
        seen: set[str] = set()
        for article in articles:
            key = article.url or article.title.lower()
            if not article.title or key in seen:
                continue
            seen.add(key)
            deduped.append(article)
        return sorted(
            deduped,
            key=lambda item: item.published_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

    @staticmethod
    def _matches_symbol_or_market(article: RawNewsArticle, symbol: str) -> bool:
        text = f"{article.title} {article.summary}".lower()
        if symbol.upper() == MARKET_SYMBOL:
            return any(term in text for term in GENERAL_CRYPTO_TERMS) or any(
                re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", text)
                for aliases in SYMBOL_ALIASES.values()
                for alias in aliases
            )
        base = symbol.split("/")[0].upper()
        aliases = SYMBOL_ALIASES.get(base, {base.lower()})
        if any(
            re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", text)
            for alias in aliases
        ):
            return True
        return any(term in text for term in GENERAL_CRYPTO_TERMS)

    @staticmethod
    def _child_text(element: ElementTree.Element, local_name: str) -> str:
        child = next(
            (item for item in list(element) if CryptoNewsService._local_name(item.tag) == local_name),
            None,
        )
        if child is None or child.text is None:
            return ""
        return child.text

    @staticmethod
    def _findall_by_local_name(element: ElementTree.Element, local_name: str) -> list[ElementTree.Element]:
        return [
            item
            for item in element.iter()
            if CryptoNewsService._local_name(item.tag) == local_name
        ]

    @staticmethod
    def _local_name(tag: str) -> str:
        return tag.rsplit("}", 1)[-1] if "}" in tag else tag

    @staticmethod
    def _atom_link(entry: ElementTree.Element) -> str:
        for child in list(entry):
            if CryptoNewsService._local_name(child.tag) != "link":
                continue
            href = child.attrib.get("href")
            if href:
                return href
            if child.text:
                return child.text
        return ""

    @staticmethod
    def _parse_datetime(value: str) -> datetime | None:
        text = value.strip()
        if not text:
            return None
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError, IndexError):
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _clean_text(value: str) -> str:
        text = TAG_RE.sub(" ", html.unescape(value or ""))
        return WHITESPACE_RE.sub(" ", text).strip()

    @staticmethod
    def _source_name(feed_url: str) -> str:
        host = urlparse(feed_url).netloc.lower().removeprefix("www.")
        if not host:
            return "unknown"
        return host.split(":")[0]

    @staticmethod
    def _public_error(exc: Exception) -> str:
        text = str(exc).replace("\n", " ").strip()
        return text[:160] + ("..." if len(text) > 160 else "")
