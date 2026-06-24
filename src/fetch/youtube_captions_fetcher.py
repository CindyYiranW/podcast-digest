"""YouTube 字幕抓取 + 清洗（yt-dlp）。

YouTube 现在对自动字幕加了 PO-token 反爬。实测可用的组合：
  player_client=ios + --ignore-no-formats-error + --skip-download
（PO-token 只影响视频流，字幕不受影响——我们只要字幕文件。）

流程：先试人工字幕(--write-subs)，没有再试自动字幕(--write-auto-subs)。
清洗：去掉 WEBVTT 头、时间轴、内联标签、自动字幕的滚动重复行 → 纯文本，
通常比原始 VTT 减少 60-70% 体积，不截断。
"""

from __future__ import annotations

import glob
import html
import os
import re
import subprocess

from src.utils.logger import get_logger

log = get_logger(__name__)

_YTDLP_TIMEOUT = 180
# 实测能拿到字幕的关键参数
_BASE_ARGS = [
    "--sub-langs", "en",
    "--sub-format", "vtt",
    "--skip-download",
    "--ignore-no-formats-error",
    "--extractor-args", "youtube:player_client=ios",
    "--no-warnings",
    "--quiet",
]


def _run(video_url: str, stem: str, auto: bool) -> str | None:
    """跑一次 yt-dlp，成功则返回生成的 .vtt 路径。"""
    sub_flag = "--write-auto-subs" if auto else "--write-subs"
    out_tmpl = f"{stem}.{'auto' if auto else 'manual'}.%(ext)s"
    cmd = ["yt-dlp", sub_flag, *_BASE_ARGS, "-o", out_tmpl, video_url]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=_YTDLP_TIMEOUT)
    except subprocess.TimeoutExpired:
        log.warning("yt-dlp 超时：%s", video_url)
        return None
    except FileNotFoundError:
        log.error("找不到 yt-dlp，请先 pip install yt-dlp")
        return None
    # 不看退出码（PO-token 可能让退出码非 0），只看有没有生成 .vtt
    files = glob.glob(f"{stem}.{'auto' if auto else 'manual'}*.vtt")
    return files[0] if files else None


def fetch_youtube_captions(video_url: str, output_dir: str) -> dict:
    """抓取英文字幕。返回 status / caption_type / vtt_path / text_path / error。"""
    os.makedirs(output_dir, exist_ok=True)
    vid = video_url.rsplit("=", 1)[-1]
    stem = os.path.join(output_dir, vid)

    # 1) 人工字幕优先
    path = _run(video_url, stem, auto=False)
    if path:
        return {"status": "success", "caption_type": "manual",
                "vtt_path": path, "text_path": None, "error": None}
    # 2) 自动字幕兜底
    path = _run(video_url, stem, auto=True)
    if path:
        return {"status": "success", "caption_type": "auto",
                "vtt_path": path, "text_path": None, "error": None}

    return {"status": "no_captions", "caption_type": None,
            "vtt_path": None, "text_path": None,
            "error": "no English captions (manual or auto) available"}


_TAG_RE = re.compile(r"<[^>]+>")               # <c>、</c>、<00:00:00.000> 等
_CUE_SETTINGS_RE = re.compile(r"\s*(align|position):\S+")
_META_PREFIXES = ("WEBVTT", "Kind:", "Language:", "NOTE", "STYLE", "REGION")


def clean_vtt_to_text(vtt_path: str) -> str:
    """VTT → 纯文本：去时间轴/标签/滚动重复，合并为自然文本。不截断。"""
    with open(vtt_path, "r", encoding="utf-8", errors="ignore") as fh:
        raw = fh.read()

    cleaned: list[str] = []
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith(_META_PREFIXES):
            continue
        if "-->" in s:                          # 时间轴行
            continue
        s = _TAG_RE.sub("", s)                  # 去内联标签
        s = _CUE_SETTINGS_RE.sub("", s).strip()
        if not s:
            continue
        # 自动字幕的滚动机制会让相邻行重复 → 去掉与上一行相同的
        if cleaned and cleaned[-1] == s:
            continue
        cleaned.append(s)

    text = html.unescape(" ".join(cleaned))   # &gt;&gt; → >>，&amp; → & 等
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text


if __name__ == "__main__":
    # 测试：python -m src.fetch.youtube_captions_fetcher
    import tempfile
    url = "https://www.youtube.com/watch?v=nbagqPiXSdA"  # Episode 307
    out = tempfile.mkdtemp()
    res = fetch_youtube_captions(url, out)
    print("status:", res["status"], "| type:", res["caption_type"])
    if res["status"] == "success":
        raw_size = os.path.getsize(res["vtt_path"])
        text = clean_vtt_to_text(res["vtt_path"])
        print(f"原始 VTT: {raw_size} 字符 | 清洗后: {len(text)} 字符 "
              f"| 减少 {100*(1-len(text)/raw_size):.0f}%")
        print("\n前 400 字：\n", text[:400])
    else:
        print("error:", res["error"])
