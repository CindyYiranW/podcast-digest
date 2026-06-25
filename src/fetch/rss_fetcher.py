"""RSS 抓取模块。

职责：读取 config/sources.yaml 里 enabled=true 的播客，拉取它们的 RSS，
只保留“过去 window_days 天内发布”的 episode，输出标准化的字典列表。

每条 episode 字典包含：
  source_name     播客名
  source_lang     语言（en / zh）
  episode_title   集标题
  published_at    发布时间（datetime，UTC）
  episode_link    原集网页链接
  audio_url       音频文件链接（如有）
  raw_description Show Notes 原文（通常含 HTML，下一步清洗）
  guests          嘉宾（如能从字段解析，否则空）
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone

import feedparser
import requests

from src.utils.config import get_sources
from src.utils.logger import get_logger

log = get_logger(__name__)

REQUEST_TIMEOUT = 20      # 秒
MAX_RETRIES = 3
USER_AGENT = "podcast-digest/0.1 (+https://github.com/)"


def _download_feed(url: str) -> bytes | None:
    """下载 RSS 原始内容，带超时和最多 3 次重试。失败返回 None。"""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(
                url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT}
            )
            resp.raise_for_status()
            return resp.content
        except Exception as e:  # noqa: BLE001  —— 网络错误种类多，统一兜底
            log.warning("下载 RSS 失败（第 %d/%d 次）：%s", attempt, MAX_RETRIES, e)
            if attempt < MAX_RETRIES:
                time.sleep(2 * attempt)  # 退避：2s, 4s
    return None


# transcript 格式优先级：纯文本/HTML 最好用，其次字幕(vtt/srt)，再次 json
_TRANSCRIPT_TYPE_PRIORITY = [
    "text/plain", "text/html", "text/vtt", "application/srt", "application/json"
]


def _norm_title(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "").lower()).strip(" .!?:：。！？")


def _extract_transcripts(raw: bytes) -> dict:
    """从 RSS 原文里解析每个 item 的 <podcast:transcript> 标签。

    返回 {guid 或 标准化标题: (transcript_url, type)}。
    一个 item 可能有多种格式，按 _TRANSCRIPT_TYPE_PRIORITY 选最优。
    feed 没有 transcript 标签时返回空字典。
    """
    text = raw.decode("utf-8", "ignore")
    index: dict[str, tuple[str, str]] = {}

    for item in re.findall(r"<item\b.*?</item>", text, re.S | re.I):
        cands: list[tuple[str, str]] = []
        for tag in re.findall(r"<podcast:transcript\b[^>]*>", item, re.I):
            u = re.search(r'\burl=["\']([^"\']+)["\']', tag, re.I)
            ty = re.search(r'\btype=["\']([^"\']+)["\']', tag, re.I)
            if u:
                cands.append((u.group(1), (ty.group(1).lower() if ty else "")))
        if not cands:
            continue

        def _rank(c: tuple[str, str]) -> int:
            for i, p in enumerate(_TRANSCRIPT_TYPE_PRIORITY):
                if p in c[1]:
                    return i
            return len(_TRANSCRIPT_TYPE_PRIORITY)

        best = sorted(cands, key=_rank)[0]
        guid = re.search(r"<guid[^>]*>(.*?)</guid>", item, re.S | re.I)
        title = re.search(r"<title[^>]*>(.*?)</title>", item, re.S | re.I)
        if guid:
            index[guid.group(1).strip()] = best
        if title:
            raw_t = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", title.group(1), flags=re.S)
            index[_norm_title(raw_t)] = best
    return index


def _lookup_transcript(entry, index: dict) -> tuple[str | None, str]:
    if not index:
        return (None, "")
    gid = entry.get("id") or entry.get("guid")
    if gid and gid in index:
        return index[gid]
    key = _norm_title(entry.get("title", ""))
    if key in index:
        return index[key]
    return (None, "")


def _entry_published(entry) -> datetime | None:
    """从一条 RSS entry 解析发布时间，返回带时区的 UTC datetime。"""
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    # parsed 是 time.struct_time（UTC），转成带时区的 datetime
    return datetime.fromtimestamp(time.mktime(parsed), tz=timezone.utc)


def _extract_guests(entry) -> str:
    """尽力从字段里解析嘉宾，解析不到就返回空字符串。"""
    for key in ("author", "itunes_author", "dc_creator"):
        val = entry.get(key)
        if val:
            return str(val)
    return ""


def _best_link(entry) -> str:
    """优先取集的网页链接；有的 feed（如 Megaphone）没有网页链接，
    这时回退用音频链接，保证报告里至少有个可点的地址。"""
    if entry.get("link"):
        return entry["link"]
    for link in entry.get("links", []) or []:
        if link.get("rel") != "enclosure" and link.get("href"):
            return link["href"]
    return _audio_url(entry)


def _audio_url(entry) -> str:
    for enc in entry.get("enclosures", []) or []:
        href = enc.get("href") or enc.get("url")
        if href:
            return href
    return ""


def fetch_source(source: dict, window_days: int) -> list[dict]:
    """抓取单个播客源，返回时间窗口内的 episode 列表。"""
    name = source.get("name", "未命名播客")
    url = source.get("rss", "")
    lang = source.get("lang", "")
    content_strategy = source.get("content_strategy", "show_notes")
    screening = source.get("screening", "claude")
    base_url = source.get("base_url", "")
    yt_channel_id = source.get("youtube_channel_id", "")
    yt_channel_url = source.get("youtube_channel_url", "")

    if not url or url.startswith("<"):
        log.warning("跳过「%s」：RSS 地址还没填好（%s）", name, url)
        return []

    log.info("正在抓取「%s」… %s", name, url)
    raw = _download_feed(url)
    if raw is None:
        log.error("「%s」抓取失败，跳过这个源。", name)
        return []

    feed = feedparser.parse(raw)
    if feed.bozo and not feed.entries:
        log.error("「%s」RSS 解析失败：%s", name, getattr(feed, "bozo_exception", ""))
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    transcript_index = _extract_transcripts(raw)  # {guid/title: (url, type)}
    episodes: list[dict] = []

    for entry in feed.entries:
        published = _entry_published(entry)
        if published is None:
            log.debug("「%s」有一条没有发布时间，跳过：%s", name, entry.get("title"))
            continue
        if published < cutoff:
            continue  # 太旧，超出时间窗口

        transcript_url, transcript_type = _lookup_transcript(entry, transcript_index)
        episodes.append(
            {
                "source_name": name,
                "source_id": source.get("id", name),     # 跨次去重用（与 YouTube 源约定一致）
                # 稳定的单集标识：优先 RSS guid/id，缺失时退回链接/标题
                "guid": entry.get("id") or entry.get("guid") or _best_link(entry) or entry.get("title", ""),
                "source_lang": lang,
                "content_strategy": content_strategy,   # 抓取策略（来自配置）
                "screening": screening,                  # 初筛方式：claude / keyword（来自配置）
                "base_url": base_url,                    # website_scrape 用的站点地址（来自配置）
                "youtube_channel_id": yt_channel_id,     # youtube_match_captions 用
                "youtube_channel_url": yt_channel_url,
                "transcript_url": transcript_url,        # <podcast:transcript> 的 URL（可能为 None）
                "transcript_type": transcript_type,      # transcript 格式（srt/vtt/html/...）
                "episode_title": entry.get("title", "（无标题）"),
                "published_at": published,
                "episode_link": _best_link(entry),
                "audio_url": _audio_url(entry),
                # RSS 里 Show Notes 可能在 content 或 summary 字段
                "raw_description": _entry_content(entry),
                "guests": _extract_guests(entry),
            }
        )

    log.info("「%s」：最近 %d 天内共 %d 集。", name, window_days, len(episodes))
    return episodes


def _entry_content(entry) -> str:
    """取 Show Notes 原文：优先 content（更完整），其次 summary/description。"""
    if entry.get("content"):
        # content 是一个列表，每项有 .value
        return entry["content"][0].get("value", "")
    return entry.get("summary") or entry.get("description") or ""


def fetch_all() -> list[dict]:
    """读取 sources.yaml，抓取所有 enabled=true 的源，合并成一个 episode 列表。"""
    cfg = get_sources()
    window_days = int(cfg.get("window_days", 14))
    all_episodes: list[dict] = []

    for source in cfg.get("sources", []):
        if not source.get("enabled", False):
            log.info("已跳过未启用的源：%s", source.get("name"))
            continue
        if source.get("content_strategy") == "youtube_channel_rss":
            # YouTube 源走专门的子流水线（见 src/fetch/youtube_pipeline.py）
            continue
        all_episodes.extend(fetch_source(source, window_days))

    log.info("全部源合计抓到 %d 集。", len(all_episodes))
    return all_episodes


if __name__ == "__main__":
    # 单独测试：python -m src.fetch.rss_fetcher
    eps = fetch_all()
    print("\n" + "=" * 60)
    print(f"共抓到 {len(eps)} 集：\n")
    for i, ep in enumerate(eps, 1):
        print(f"[{i}] {ep['source_name']} | {ep['published_at']:%Y-%m-%d}")
        print(f"    标题：{ep['episode_title']}")
        print(f"    链接：{ep['episode_link']}")
        print(f"    Show Notes 原文长度：{len(ep['raw_description'])} 字符")
        print()
