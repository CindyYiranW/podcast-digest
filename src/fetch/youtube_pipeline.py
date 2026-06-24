"""YouTube 源的子流水线（接入主 pipeline）。

对每个 content_strategy == "youtube_channel_rss" 的源：
  1. 抓 YouTube channel RSS 拿视频列表
  2. 时间窗口过滤（最近 window_days 天）
  3. 关键词初筛（不调用 Claude）——未命中则跳过
  4. 通过初筛才抓字幕（yt-dlp）→ 清洗成纯文本
  5. 产出可直接进入深度分析的 episode dict（is_relevant=True，full_text=字幕全文）

去重：成功处理过的视频记入缓存，下次跳过；跳过/失败的不记，下次重试。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.fetch.youtube_channel_rss_fetcher import fetch_youtube_channel_rss
from src.fetch.youtube_captions_fetcher import clean_vtt_to_text, fetch_youtube_captions
from src.llm.screening import screen_dispatch
from src.utils.cache import already_processed, mark_processed
from src.utils.config import PROJECT_ROOT, get_sources
from src.utils.logger import get_logger

log = get_logger(__name__)

_CAPTIONS_DIR = str(PROJECT_ROOT / "data" / "cache" / "captions")


def _within_window(published: datetime | None, window_days: int) -> bool:
    if published is None:
        return True  # 没时间就不卡窗口，交给后续判断
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    return published >= cutoff


def _candidate(source: dict, video: dict, key: str) -> dict:
    """建一个"候选" episode（还没抓字幕）：用 description 当 show notes 给初筛。"""
    return {
        "source_name": source["name"],
        "source_lang": source.get("lang", "en"),
        "content_strategy": "youtube_channel_rss",
        "screening": source.get("screening", "claude"),  # 该源的初筛方式
        "episode_title": video["title"],
        "published_at": video["published_at"],
        "episode_link": video["video_url"],
        "guests": "",
        "clean_shownotes": video.get("description", ""),
        "_video": video,
        "_key": key,
    }


def collect_ready_youtube_episodes(window_days: int) -> list[dict]:
    """处理所有 YouTube 源，返回可进入深度分析的 episode 列表。

    流程：抓 RSS → 建候选 → 初筛（按该源 screening：keyword 或 claude，基于
    description）→ 仅对通过初筛的视频抓字幕 → 产出含 full_text 的 episode。
    """
    ready: list[dict] = []
    for source in get_sources().get("sources", []):
        if not source.get("enabled", False):
            continue
        if source.get("content_strategy") != "youtube_channel_rss":
            continue

        source_id = source.get("id", source["name"])
        videos = fetch_youtube_channel_rss(source)
        videos = [v for v in videos if _within_window(v["published_at"], window_days)]
        log.info("「%s」窗口内 %d 个视频。", source["name"], len(videos))

        # 1) 建候选，去掉已处理过的
        cands = []
        for v in videos:
            key = f"{source_id}:{v['video_id']}"
            if already_processed(key):
                log.info("  已处理过，跳过：%s", v["title"][:50])
                continue
            cands.append(_candidate(source, v, key))
        if not cands:
            continue

        # 2) 初筛（keyword 或 claude，由该源的 screening 决定）
        screen_dispatch(cands)

        # 3) 仅对通过初筛的视频抓字幕（省 yt-dlp + Claude 分析成本）
        for ep in cands:
            video = ep.pop("_video")
            key = ep.pop("_key")
            if not ep.get("is_relevant"):
                log.info("  ❌ %s，跳过：%s",
                         ep.get("reason", "not_relevant"), video["title"][:50])
                continue

            res = fetch_youtube_captions(video["video_url"], _CAPTIONS_DIR)
            if res["status"] != "success":
                log.warning("  ⚠️ 抓字幕失败(%s)，下次重试：%s",
                            res.get("error") or res["status"], video["title"][:50])
                continue

            text = clean_vtt_to_text(res["vtt_path"])
            txt_path = res["vtt_path"].rsplit(".vtt", 1)[0] + ".txt"
            try:
                with open(txt_path, "w", encoding="utf-8") as fh:
                    fh.write(text)
            except Exception:  # noqa: BLE001
                txt_path = ""

            ep["full_text"] = text
            ep["content_source"] = f"youtube_transcript ({res['caption_type']})"
            ep["enriched"] = True
            ep["transcript_txt_path"] = txt_path
            log.info("  ✅ %s 字幕 %d 字符：%s",
                     res["caption_type"], len(text), video["title"][:50])
            ready.append(ep)
            mark_processed(key, {"title": video["title"], "caption_type": res["caption_type"]})

    if ready:
        log.info("YouTube 源共产出 %d 集可分析内容。", len(ready))
    return ready
