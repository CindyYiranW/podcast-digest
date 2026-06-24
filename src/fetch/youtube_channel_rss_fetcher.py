"""YouTube Channel RSS 抓取。

以 YouTube 频道的 RSS（atom + yt + media 命名空间）作为主监控源，
解析出每个视频的 video_id / title / published_at / video_url / description。

不依赖 podcast RSS，也不做标题匹配——直接用 YouTube RSS。
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import feedparser
import requests

from src.utils.logger import get_logger

log = get_logger(__name__)

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
_TIMEOUT = 25
_MAX_RETRIES = 3


def _download(url: str) -> bytes | None:
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            r = requests.get(url, headers={"User-Agent": _UA}, timeout=_TIMEOUT)
            r.raise_for_status()
            return r.content
        except Exception as e:  # noqa: BLE001
            log.warning("YouTube RSS 下载失败（%d/%d）：%s", attempt, _MAX_RETRIES, e)
            if attempt < _MAX_RETRIES:
                time.sleep(2 * attempt)
    return None


def _published(entry) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime.fromtimestamp(time.mktime(parsed), tz=timezone.utc)


def _description(entry) -> str:
    # YouTube RSS 把 media:description 通常映射到 summary
    return (
        entry.get("media_description")
        or entry.get("summary")
        or entry.get("description")
        or ""
    )


def fetch_youtube_channel_rss(source: dict) -> list[dict]:
    """解析 source['youtube_rss_url']，返回视频列表。"""
    url = source.get("youtube_rss_url", "")
    if not url:
        log.error("「%s」缺少 youtube_rss_url，跳过。", source.get("name"))
        return []

    log.info("正在抓取 YouTube RSS「%s」… %s", source.get("name"), url)
    raw = _download(url)
    if raw is None:
        log.error("「%s」YouTube RSS 抓取失败。", source.get("name"))
        return []

    feed = feedparser.parse(raw)
    videos: list[dict] = []
    for e in feed.entries:
        vid = e.get("yt_videoid")
        if not vid:
            continue
        videos.append(
            {
                "video_id": vid,
                "title": e.get("title", ""),
                "published_at": _published(e),
                "video_url": f"https://www.youtube.com/watch?v={vid}",
                "description": _description(e),
            }
        )
    log.info("「%s」：YouTube RSS 解析到 %d 个视频。", source.get("name"), len(videos))
    return videos


if __name__ == "__main__":
    # 测试：python -m src.fetch.youtube_channel_rss_fetcher
    from src.utils.config import get_sources

    src = next(
        s for s in get_sources()["sources"]
        if s.get("content_strategy") == "youtube_channel_rss"
    )
    vids = fetch_youtube_channel_rss(src)
    for v in vids[:5]:
        d = v["published_at"].strftime("%Y-%m-%d") if v["published_at"] else "?"
        print(f"  {v['video_id']} | {d} | {v['title'][:55]}")
        print(f"      desc 长度: {len(v['description'])}")
