"""简单的处理记录缓存（避免重复抓字幕/分析同一个视频）。

存在 data/cache/processed.json，key 形如 "source_id:external_id"。
只记录"成功处理完"的条目；关键词未命中或抓字幕失败的不记，下次会重试。
"""

from __future__ import annotations

import json

from src.utils.config import PROJECT_ROOT
from src.utils.logger import get_logger

log = get_logger(__name__)

_CACHE_FILE = PROJECT_ROOT / "data" / "cache" / "processed.json"


def _load() -> dict:
    if not _CACHE_FILE.exists():
        return {}
    try:
        return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def already_processed(key: str) -> bool:
    return key in _load()


def mark_processed(key: str, info: dict | None = None) -> None:
    data = _load()
    data[key] = info or {}
    _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def dedup_key(ep: dict) -> str:
    """单集去重键 "source:external_id"。对 RSS 和 YouTube 两种 episode 形状都健壮。"""
    src = ep.get("source_id") or ep.get("source_name", "")
    ext = (
        ep.get("guid")
        or ep.get("video_id")
        or ep.get("episode_link")
        or ep.get("episode_title", "")
    )
    return f"{src}:{ext}"


def filter_unprocessed(episodes: list[dict]) -> list[dict]:
    """丢掉本地缓存里已处理过（终态）的 episode，返回需要本次处理的列表。"""
    cache = _load()
    fresh = [ep for ep in episodes if dedup_key(ep) not in cache]
    skipped = len(episodes) - len(fresh)
    if skipped:
        log.info("跨次去重：跳过 %d 集上次已处理过的 episode，本次处理 %d 集。", skipped, len(fresh))
    return fresh


def mark_terminal(episodes: list[dict]) -> None:
    """把进入终态的 episode 记入缓存（一次读、一次写）。

    终态 = 判定不相关，或「相关且已拿到文字稿(enriched)」。
    「相关但没拿到文字稿」不记——下次重试（文字稿可能晚些才出现）。
    """
    data = _load()
    changed = False
    for ep in episodes:
        if ep.get("is_relevant") and not ep.get("enriched"):
            continue  # pending：留待下次重试
        status = "relevant" if ep.get("is_relevant") else "irrelevant"
        data[dedup_key(ep)] = {
            "title": ep.get("episode_title", ""),
            "status": status,
            "enriched": bool(ep.get("enriched")),
        }
        changed = True
    if changed:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
