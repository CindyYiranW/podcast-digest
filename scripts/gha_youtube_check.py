#!/usr/bin/env python3
"""YouTube 字幕抓取可用性自检（本地或 GitHub Actions 里跑）。

目的：判断【当前机器 / 当前 IP】能不能抓到 YouTube 字幕——主要用来验证
GitHub Actions 的数据中心 IP 是否被 YouTube 拦截（即便配了 cookie 也可能被拦）。

做法：从 Your Morning Coffee 频道 RSS 取最近几条视频，逐个尝试抓字幕，
打印每条的 status（success / blocked / no_captions）和字幕长度，最后给结论。
与正式管线一致，读取 YOUTUBE_COOKIES_FILE / YOUTUBE_COOKIES_FROM_BROWSER。

退出码：0 = 至少一条成功；1 = 全部失败（很可能被 IP 拦）；2 = 环境/网络错误。
用法：PYTHONPATH=. python scripts/gha_youtube_check.py [N]   # N 默认 3
"""
from __future__ import annotations

import re
import sys
import tempfile
import urllib.request

from src.fetch.youtube_captions_fetcher import (
    clean_vtt_to_text,
    cookies_configured,
    fetch_youtube_captions,
)

# Your Morning Coffee 频道 RSS（含最近视频，免登录可读）。
YMC_CHANNEL_RSS = "https://www.youtube.com/feeds/videos.xml?channel_id=UC7Wp25QkW7B6uBjSldHDc2g"


def recent_video_ids(n: int) -> list[str]:
    req = urllib.request.Request(YMC_CHANNEL_RSS, headers={"User-Agent": "Mozilla/5.0"})
    raw = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
    return re.findall(r"<yt:videoId>([^<]+)</yt:videoId>", raw)[:n]


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    print(f"cookies_configured: {cookies_configured()}")
    try:
        vids = recent_video_ids(n)
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: 无法读取 YMC 频道 RSS：{e}")
        sys.exit(2)
    if not vids:
        print("ERROR: 频道 RSS 里没解析到视频 ID。")
        sys.exit(2)
    print(f"testing {len(vids)} recent videos: {vids}\n")

    statuses: list[str] = []
    for vid in vids:
        url = f"https://www.youtube.com/watch?v={vid}"
        res = fetch_youtube_captions(url, tempfile.mkdtemp())
        chars = len(clean_vtt_to_text(res["vtt_path"])) if res["status"] == "success" else 0
        print(f"  {vid}: status={res['status']} type={res['caption_type']} chars={chars}")
        if res["status"] != "success":
            print(f"      └ {res['error']}")
        statuses.append(res["status"])

    ok = statuses.count("success")
    blocked = statuses.count("blocked")
    print(
        f"\nVERDICT: {ok}/{len(statuses)} success | {blocked} blocked | "
        f"{statuses.count('no_captions')} no_captions"
    )
    if ok == 0:
        why = (
            "（已配 cookie 仍失败 → 很可能此 IP 被 YouTube 拦截）"
            if cookies_configured()
            else "（未配 cookie，属预期）"
        )
        print(f"❌ 本机/本 IP 抓不到 YouTube 字幕{why}。")
        sys.exit(1)
    print("✅ 本机/本 IP 能抓到 YouTube 字幕。")


if __name__ == "__main__":
    main()
