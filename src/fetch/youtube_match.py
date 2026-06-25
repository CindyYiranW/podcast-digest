"""在一个 YouTube 频道里，按标题（+发布日期）找到与某播客集对应的视频。

用于"播客 RSS 做监控，YouTube 抓字幕"的源（如 The Town）：频道里混有完整集和
clips，但完整集的标题与播客集标题一致，所以按标题匹配能可靠定位完整集。

两级查找：
  1) YouTube channel RSS（约15条，带日期）——快，且能用日期校验
  2) yt-dlp flat-playlist（覆盖更多历史视频，无日期）——标题精确匹配兜底
"""

from __future__ import annotations

import difflib
import re
import subprocess
import time
from datetime import datetime, timezone

import feedparser
import requests

from src.utils.logger import get_logger

log = get_logger(__name__)

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124 Safari/537.36"
_MATCH_CUTOFF = 0.85
_FLAT_LIMIT = 150


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "").lower()).strip(" .!?:：。！？")


def _yt_rss_candidates(channel_id: str) -> dict[str, tuple[str, datetime | None]]:
    out: dict[str, tuple[str, datetime | None]] = {}
    try:
        raw = requests.get(
            f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}",
            headers={"User-Agent": _UA}, timeout=20,
        ).content
    except Exception:  # noqa: BLE001
        return out
    for e in feedparser.parse(raw).entries:
        vid = e.get("yt_videoid")
        if not vid:
            continue
        p = e.get("published_parsed")
        d = datetime.fromtimestamp(time.mktime(p), tz=timezone.utc) if p else None
        out[_norm(e.get("title", ""))] = (f"https://www.youtube.com/watch?v={vid}", d)
    return out


def _flat_playlist_candidates(channel_url: str) -> dict[str, tuple[str, None]]:
    url = channel_url.rstrip("/")
    if not url.endswith("/videos"):
        url += "/videos"
    cmd = [
        "yt-dlp", "--flat-playlist", "--playlist-end", str(_FLAT_LIMIT),
        "--extractor-args", "youtube:player_client=ios", "--no-warnings", "--quiet",
        "--print", "%(id)s\t%(title)s", url,
    ]
    out: dict[str, tuple[str, None]] = {}
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception:  # noqa: BLE001
        return out
    for line in proc.stdout.splitlines():
        if "\t" in line:
            vid, title = line.split("\t", 1)
            out[_norm(title)] = (f"https://www.youtube.com/watch?v={vid}", None)
    return out


def _best_match(key: str, cand: dict, published_at: datetime | None,
                tol_days: int) -> str | None:
    if not cand:
        return None
    match = key if key in cand else None
    if match is None:
        m = difflib.get_close_matches(key, list(cand.keys()), n=1, cutoff=_MATCH_CUTOFF)
        match = m[0] if m else None
    if not match:
        return None
    url, vdate = cand[match]
    # 有日期就校验 ±tol_days；没日期（flat-playlist）就只靠标题
    if published_at and vdate and abs((published_at - vdate).days) > tol_days:
        return None
    return url


def find_youtube_video(channel_id: str | None, channel_url: str | None,
                       episode_title: str, published_at: datetime | None,
                       tol_days: int = 3) -> str | None:
    """返回匹配视频的 watch URL，找不到返回 None。"""
    key = _norm(episode_title)
    if channel_id:
        url = _best_match(key, _yt_rss_candidates(channel_id), published_at, tol_days)
        if url:
            return url
    if channel_url:
        # flat-playlist 没日期，标题精确/高相似匹配足够
        url = _best_match(key, _flat_playlist_candidates(channel_url), None, tol_days)
        if url:
            return url
    return None
