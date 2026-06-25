"""YouTube 字幕抓取 + 清洗（yt-dlp）。

YouTube 对数据中心/陌生 IP 会弹机器人验证（"Sign in to confirm you're not a bot"），
需要登录 cookie 才能抓字幕——见 _cookie_args() 与 README「cookies setup」。
配了 cookie 后用默认客户端即可下载字幕（曾用的 player_client=ios 反而拿不到字幕）。

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

from src.utils.config import get_env
from src.utils.logger import get_logger

log = get_logger(__name__)

_YTDLP_TIMEOUT = 180
# 抓字幕的关键参数。
# 注意：早期用 player_client=ios 绕 PO-token，但实测 ios 客户端【拿不到字幕】
#（返回 "There are no subtitles"）。改用默认客户端 + cookie，字幕能正常下载；
# 视频流的 PO-token 问题与我们无关（--skip-download，只要字幕）。
_BASE_ARGS = [
    "--sub-langs", "en",
    "--sub-format", "vtt",
    "--skip-download",
    "--ignore-no-formats-error",
    "--no-warnings",
    "--quiet",
]

# YouTube 从数据中心 IP 抓字幕常被拦（"Sign in to confirm you're not a bot"）。
# 这些短语出现在 yt-dlp stderr 里时，说明是「被拦」而不是「真没字幕」。
_BLOCK_MARKERS = (
    "sign in to confirm",
    "not a bot",
    "confirm your age",
    "use --cookies",
    "--cookies-from-browser",
    "http error 429",
)


def _cookie_args() -> list[str]:
    """从环境变量读取 yt-dlp 的 cookie 配置（绕过 YouTube 机器人验证）。

    YOUTUBE_COOKIES_FROM_BROWSER：浏览器名，如 chrome / safari / firefox（用本机登录态）。
    YOUTUBE_COOKIES_FILE：Netscape 格式 cookies.txt 的路径（适合无桌面的服务器）。
    两者都没配就返回空——本地有桌面浏览器时填前者最省事。
    """
    args: list[str] = []
    browser = get_env("YOUTUBE_COOKIES_FROM_BROWSER")
    if browser:
        args += ["--cookies-from-browser", browser]
    cookie_file = get_env("YOUTUBE_COOKIES_FILE")
    if cookie_file:
        args += ["--cookies", cookie_file]
    return args


def cookies_configured() -> bool:
    """是否配了 yt-dlp cookie（浏览器或 cookies.txt 任一）。供启动自检用。"""
    return bool(_cookie_args())


def _probe_block(video_url: str) -> str:
    """字幕没抓到时，探一次真实原因。

    正常抓取带 --ignore-no-formats-error（容忍 ios 客户端拿不到视频流），
    但该参数会把「机器人验证」之类的报错一并吞掉。这里单独跑一次 --list-subs
    （不加 ignore，用默认客户端）让真实报错冒出来，用于区分「被拦」vs「真没字幕」。
    """
    cmd = ["yt-dlp", "--list-subs", "--skip-download", *_cookie_args(), video_url]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=_YTDLP_TIMEOUT)
        return (proc.stderr or "") + "\n" + (proc.stdout or "")
    except Exception:  # noqa: BLE001
        return ""


def _run(video_url: str, stem: str, auto: bool) -> tuple[str | None, str]:
    """跑一次 yt-dlp，返回 (生成的 .vtt 路径或 None, yt-dlp 的 stderr)。"""
    sub_flag = "--write-auto-subs" if auto else "--write-subs"
    out_tmpl = f"{stem}.{'auto' if auto else 'manual'}.%(ext)s"
    cmd = ["yt-dlp", sub_flag, *_BASE_ARGS, *_cookie_args(), "-o", out_tmpl, video_url]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=_YTDLP_TIMEOUT)
        stderr = proc.stderr or ""
    except subprocess.TimeoutExpired:
        log.warning("yt-dlp 超时：%s", video_url)
        return None, "yt-dlp timeout"
    except FileNotFoundError:
        log.error("找不到 yt-dlp，请先 pip install yt-dlp")
        return None, "yt-dlp not found"
    # 不看退出码（PO-token 可能让退出码非 0），只看有没有生成 .vtt
    files = glob.glob(f"{stem}.{'auto' if auto else 'manual'}*.vtt")
    return (files[0] if files else None), stderr


def fetch_youtube_captions(video_url: str, output_dir: str) -> dict:
    """抓取英文字幕。返回 status / caption_type / vtt_path / text_path / error。

    status 取值：
      success    —— 拿到字幕
      blocked    —— 被 YouTube 拦截（机器人验证/限流），需要配 cookie；不是真没字幕
      no_captions—— 确实没有英文字幕
    """
    os.makedirs(output_dir, exist_ok=True)
    vid = video_url.rsplit("=", 1)[-1]
    stem = os.path.join(output_dir, vid)

    # 1) 人工字幕优先
    path, err_manual = _run(video_url, stem, auto=False)
    if path:
        return {"status": "success", "caption_type": "manual",
                "vtt_path": path, "text_path": None, "error": None}
    # 2) 自动字幕兜底
    path, err_auto = _run(video_url, stem, auto=True)
    if path:
        return {"status": "success", "caption_type": "auto",
                "vtt_path": path, "text_path": None, "error": None}

    # 都没拿到——区分「被拦」和「真没字幕」，并把 yt-dlp 的真实报错暴露出来。
    # 正常抓取的 stderr 被 --ignore-no-formats-error 吞掉了，所以再探一次真实原因。
    stderr = (err_auto or err_manual or "").strip()
    if not any(mark in stderr.lower() for mark in _BLOCK_MARKERS):
        stderr = _probe_block(video_url).strip()
    low = stderr.lower()
    if any(mark in low for mark in _BLOCK_MARKERS):
        # 优先取真正含「拦截」关键词的那一行（跳过 urllib3 等无关警告）
        first = next(
            (ln.strip() for ln in stderr.splitlines()
             if any(mark in ln.lower() for mark in _BLOCK_MARKERS)),
            next((ln.strip() for ln in stderr.splitlines() if ln.strip()), stderr),
        )
        has_cookie = bool(_cookie_args())
        hint = "已配 cookie 仍被拦，可能需更新 cookie/换 IP" if has_cookie \
            else "未配 cookie：设 YOUTUBE_COOKIES_FROM_BROWSER 或 YOUTUBE_COOKIES_FILE"
        log.warning("YouTube 拦截字幕抓取（%s）：%s", hint, first)
        return {"status": "blocked", "caption_type": None,
                "vtt_path": None, "text_path": None,
                "error": f"YouTube 拦截（{hint}）：{first}"}

    if stderr:
        log.debug("yt-dlp 无字幕且无拦截迹象，stderr：%s", stderr[:300])
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
