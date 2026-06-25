"""内容增强模块：在初筛之后，为「相关」的 episode 补全更丰富的全文。

策略由 episode 的 content_source 决定（来自 config/sources.yaml）：
  - "theverge_scrape"：抓 theverge.com 上对应文章的正文（含完整文字稿），
                       存进 episode["full_text"]，并把 episode_link 指向该文章。
  - "show_notes"（默认）：full_text 就用清洗后的 Show Notes，不额外抓取。

为什么放在初筛之后：抓全文较慢/有网络成本，只对筛选保留的 episode 做，省时省钱。

注意：theverge.com 的 RSS 里没有文章链接，所以这里改用「抓 Decoder 文章索引页 →
按标题匹配 → 进文章抓正文」的方式。任何一步失败都安全回退到 Show Notes。
"""

from __future__ import annotations

import difflib
import json
import re
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.fetch.youtube_captions_fetcher import clean_vtt_to_text, fetch_youtube_captions
from src.fetch.youtube_match import find_youtube_video
from src.utils.config import PROJECT_ROOT
from src.utils.logger import get_logger

log = get_logger(__name__)

# 用浏览器 UA：theverge.com 对默认/爬虫 UA 可能拒绝，对浏览器 UA 正常返回。
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
)
_TIMEOUT = 25
_MAX_RETRIES = 3

# Decoder 在 The Verge 的文章索引页（列出每集对应文章链接）
THEVERGE_DECODER_INDEX = "https://www.theverge.com/decoder-with-nilay-patel"

# 标题模糊匹配的最低相似度（0~1）
_MATCH_CUTOFF = 0.82

# 人类可读的内容来源标记（写进 episode["content_source"]，在日志和报告里展示）
FLAG_FULL = "full_transcript (The Verge)"
FLAG_RSS = "full_transcript (RSS transcript)"
FLAG_SUBSTACK = "full_transcript (Substack)"
FLAG_TRAPITAL = "full_text (Trapital site)"
FLAG_SHOW = "show_notes only"

# 抓到的 YouTube 字幕存放目录
_CAPTIONS_DIR = str(PROJECT_ROOT / "data" / "cache" / "captions")

# 站点索引页缓存（避免对同一索引页重复抓取），key=索引页URL
_INDEX_CACHE: dict[str, dict] = {}

# Substack 文章页里指向自动转写文件的链接
_SUBSTACK_TRANSCRIPTION_RE = re.compile(
    r"https://substackcdn\.com/[^\"'\\\s]*transcription\.json[^\"'\\\s]*"
)


def _fetch_html(url: str) -> bytes | None:
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            r = requests.get(url, headers={"User-Agent": _BROWSER_UA}, timeout=_TIMEOUT)
            r.raise_for_status()
            return r.content
        except Exception as e:  # noqa: BLE001
            log.warning("抓取网页失败（第 %d/%d 次）：%s | %s", attempt, _MAX_RETRIES, url, e)
            if attempt < _MAX_RETRIES:
                time.sleep(2 * attempt)
    return None


def _normalize(title: str) -> str:
    t = (title or "").lower().strip()
    t = re.sub(r"\s+", " ", t)
    t = t.strip(" .!?:：。！？")
    return t


def build_theverge_index(index_url: str = THEVERGE_DECODER_INDEX) -> dict[str, str]:
    """抓索引页，返回 {标准化标题: 文章URL}。失败返回空字典。"""
    html = _fetch_html(index_url)
    if html is None:
        return {}
    soup = BeautifulSoup(html, "lxml")
    mapping: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # The Verge 文章链接形如 /podcast/952607/... 或 /tech/12345/...
        if not re.search(r"/\d{5,}/", href):
            continue
        text = a.get_text(strip=True)
        if not text:
            continue
        full = href if href.startswith("http") else "https://www.theverge.com" + href
        mapping.setdefault(_normalize(text), full)
    log.info("The Verge 索引页解析到 %d 个候选文章链接。", len(mapping))
    return mapping


def find_article_url(title: str, index_map: dict[str, str]) -> str | None:
    """按标题在索引里找文章 URL：先精确匹配，再模糊匹配。"""
    if not index_map:
        return None
    key = _normalize(title)
    if key in index_map:
        return index_map[key]
    match = difflib.get_close_matches(key, index_map.keys(), n=1, cutoff=_MATCH_CUTOFF)
    if match:
        return index_map[match[0]]
    return None


def _extract_article_text(html: bytes) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "figure"]):
        tag.decompose()
    paras = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    paras = [p for p in paras if p]
    text = "\n".join(paras)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def _captions_to_text(s: str) -> str:
    """把 SRT / WebVTT 字幕去掉序号和时间轴，只留台词文本。"""
    out: list[str] = []
    for line in s.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.upper().startswith("WEBVTT"):
            continue
        if "-->" in line:           # 时间轴行
            continue
        if re.fullmatch(r"\d+", line):  # 字幕序号
            continue
        out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def _scrape_substack_transcript(episode: dict) -> tuple[str | None, str | None]:
    """Big Technology 等 Substack 播客：进文章页 → 找 transcription.json → 拼成文字稿。

    返回 (full_text, post_url)。任何一步失败返回 (None, post_url/None)。
    """
    post_url = episode.get("episode_link")
    if not post_url:
        return (None, None)
    page = _fetch_html(post_url)
    if not page:
        return (None, post_url)

    page_text = page.decode("utf-8", "ignore")
    m = _SUBSTACK_TRANSCRIPTION_RE.search(page_text)
    if not m:
        # 没有公开转写。区分两种情况：付费墙锁住 vs 该文章本就没有转写。
        # 付费集的公开 HTML 里没有 transcription.json，但带 only_paid 受众标记。
        if '"only_paid"' in page_text or '\\"only_paid\\"' in page_text:
            episode["paywalled"] = True
            log.info("🔒 [付费墙] 转写为订阅者专享，无法抓取：%s",
                     episode.get("episode_title", "")[:40])
        return (None, post_url)  # 该文章没有公开转写（付费墙 / 纯文字 newsletter）
    json_url = m.group(0).replace("\\u0026", "&").replace("\\/", "/")

    data = _fetch_html(json_url)
    if not data:
        return (None, post_url)
    try:
        segs = json.loads(data.decode("utf-8", "ignore"))
    except Exception:  # noqa: BLE001
        return (None, post_url)
    if isinstance(segs, dict):
        segs = segs.get("segments") or []

    parts = [s.get("text", "") for s in segs if isinstance(s, dict)]
    text = re.sub(r"\s{2,}", " ", " ".join(p.strip() for p in parts if p)).strip()
    return (text or None, post_url)


def _transcript_to_text(raw: bytes, ttype: str) -> str:
    """根据 transcript 的 type，把下载内容转成纯文本。"""
    s = raw.decode("utf-8", "ignore")
    t = (ttype or "").lower()

    if "html" in t:
        soup = BeautifulSoup(raw, "lxml")
        for tag in soup(["script", "style"]):
            tag.decompose()
        return re.sub(r"\n{3,}", "\n\n", soup.get_text("\n")).strip()
    if "srt" in t or "vtt" in t:
        return _captions_to_text(s)
    if "json" in t:
        try:
            data = json.loads(s)
            segs = data.get("segments") or []
            parts = [seg.get("body") or seg.get("text") or "" for seg in segs]
            joined = " ".join(p for p in parts if p).strip()
            if joined:
                return joined
        except Exception:  # noqa: BLE001
            pass
        return s.strip()
    # text/plain 或未知：直接当纯文本
    return s.strip()


def _build_link_index(index_url: str, href_pattern: str) -> dict[str, str]:
    """抓索引页，返回 {标准化标题: 文章URL}（按 href_pattern 过滤链接）。带缓存。"""
    if index_url in _INDEX_CACHE:
        return _INDEX_CACHE[index_url]
    mapping: dict[str, str] = {}
    html = _fetch_html(index_url)
    if html:
        soup = BeautifulSoup(html, "lxml")
        for a in soup.find_all("a", href=True):
            if not re.search(href_pattern, a["href"]):
                continue
            text = a.get_text(strip=True)
            if text:
                mapping.setdefault(_normalize(text), urljoin(index_url, a["href"]))
    log.info("索引页解析到 %d 个候选文章：%s", len(mapping), index_url)
    _INDEX_CACHE[index_url] = mapping
    return mapping


def _scrape_trapital(episode: dict) -> tuple[str | None, str | None]:
    """Trapital：在 /podcast 索引页按标题匹配到 /episodes/<slug>，抓正文。"""
    base = episode.get("base_url") or "https://www.trapital.com/podcast"
    index = _build_link_index(base, r"/episodes/")
    url = find_article_url(episode.get("episode_title", ""), index)
    if not url:
        return (None, None)
    html = _fetch_html(url)
    if not html:
        return (None, url)
    return (_extract_article_text(html) or None, url)


def enrich_episode_content(episode: dict, index_map: dict[str, str] | None = None) -> dict:
    """为单个 episode 补全 full_text，并打上人类可读的来源标记。

    成功（theverge_scrape 抓到正文）：
        episode["full_text"] = 全文，episode["enriched"] = True，
        episode["episode_link"] 改为文章 URL，
        episode["content_source"] = "full_transcript (The Verge)"。
    其余情况：
        episode["full_text"] = 清洗后的 Show Notes，episode["enriched"] = False，
        episode["content_source"] = "show_notes only"。
    """
    strategy = episode.get("content_strategy", "show_notes")

    if strategy == "theverge_scrape":
        if index_map is None:
            index_map = build_theverge_index()
        url = find_article_url(episode.get("episode_title", ""), index_map)
        if url:
            html = _fetch_html(url)
            if html:
                text = _extract_article_text(html)
                if text and len(text) > len(episode.get("clean_shownotes", "")):
                    episode["full_text"] = text
                    episode["enriched"] = True
                    episode["episode_link"] = url  # 用文章链接替换音频链接
                    episode["content_source"] = FLAG_FULL
                    log.info(
                        "✅ [%s] %s：%d 字符（Show Notes 仅 %d 字符）",
                        FLAG_FULL, episode.get("episode_title", "")[:40],
                        len(text), len(episode.get("clean_shownotes", "")),
                    )
                    return episode
        log.warning(
            "⚠️ 未能抓到全文，回退 Show Notes：%s", episode.get("episode_title", "")[:40]
        )

    elif strategy == "rss_transcript_tag":
        turl = episode.get("transcript_url")
        if turl:
            data = _fetch_html(turl)
            if data:
                text = _transcript_to_text(data, episode.get("transcript_type", ""))
                if text and len(text) > len(episode.get("clean_shownotes", "")):
                    episode["full_text"] = text
                    episode["enriched"] = True
                    episode["content_source"] = FLAG_RSS
                    log.info(
                        "✅ [%s] %s：%d 字符（type=%s）",
                        FLAG_RSS, episode.get("episode_title", "")[:40],
                        len(text), episode.get("transcript_type", ""),
                    )
                    return episode
        log.warning(
            "⚠️ RSS 无 <podcast:transcript> 或抓取失败，回退 Show Notes：%s",
            episode.get("episode_title", "")[:40],
        )

    elif strategy == "website_scrape":
        # 按站点分派适配器（不同站点 HTML 结构不同）
        site = (episode.get("base_url", "") + " " + (episode.get("episode_link") or "")).lower()
        text, url, flag = None, None, None
        if "bigtechnology" in site or "substack" in site:
            text, url = _scrape_substack_transcript(episode)
            flag = FLAG_SUBSTACK
        elif "trapital" in site:
            text, url = _scrape_trapital(episode)
            flag = FLAG_TRAPITAL
        if text and len(text) > len(episode.get("clean_shownotes", "")):
            episode["full_text"] = text
            episode["enriched"] = True
            episode["content_source"] = flag
            if url:
                episode["episode_link"] = url
            log.info(
                "✅ [%s] %s：%d 字符",
                flag, episode.get("episode_title", "")[:40], len(text),
            )
            return episode
        log.warning(
            "⚠️ website_scrape 未取到全文，回退 Show Notes：%s",
            episode.get("episode_title", "")[:40],
        )

    elif strategy == "youtube_match_captions":
        # 播客 RSS 监控 + 去配置的 YouTube 频道里按标题找到对应完整集 → 抓字幕
        vurl = find_youtube_video(
            episode.get("youtube_channel_id"),
            episode.get("youtube_channel_url"),
            episode.get("episode_title", ""),
            episode.get("published_at"),
        )
        if vurl:
            res = fetch_youtube_captions(vurl, _CAPTIONS_DIR)
            if res["status"] == "success":
                text = clean_vtt_to_text(res["vtt_path"])
                if text and len(text) > len(episode.get("clean_shownotes", "")):
                    episode["full_text"] = text
                    episode["enriched"] = True
                    episode["content_source"] = f"youtube_transcript ({res['caption_type']})"
                    episode["youtube_url"] = vurl
                    log.info("✅ [youtube_transcript] %s：%d 字符",
                             episode.get("episode_title", "")[:40], len(text))
                    return episode
        # YouTube 没匹配到 → 若配了网站正文兜底（如 Trapital 文章页），退一步抓它
        if "trapital" in (episode.get("base_url") or "").lower():
            text, url = _scrape_trapital(episode)
            if text and len(text) > len(episode.get("clean_shownotes", "")):
                episode["full_text"] = text
                episode["enriched"] = True
                episode["content_source"] = FLAG_TRAPITAL
                if url:
                    episode["episode_link"] = url
                log.info("↩️ [%s] %s：%d 字符（YouTube 未匹配，用网站正文）",
                         FLAG_TRAPITAL, episode.get("episode_title", "")[:40], len(text))
                return episode
        log.warning(
            "⚠️ 未匹配到 YouTube 视频/无字幕，回退 Show Notes：%s",
            episode.get("episode_title", "")[:40],
        )

    episode["full_text"] = episode.get("clean_shownotes", "")
    episode["enriched"] = False
    episode["content_source"] = FLAG_SHOW
    log.info("ℹ️ [%s] %s", FLAG_SHOW, episode.get("episode_title", "")[:40])
    return episode


def enrich_all(episodes: list[dict]) -> list[dict]:
    """批量增强。对需要抓 The Verge 的 episode，只抓一次索引页复用。"""
    needs_scrape = any(e.get("content_strategy") == "theverge_scrape" for e in episodes)
    index_map = build_theverge_index() if needs_scrape else {}
    for ep in episodes:
        enrich_episode_content(ep, index_map)
    return episodes


if __name__ == "__main__":
    # 单独测试：python -m src.fetch.content_enricher
    # 只检查抓取是否成功（来源标记 + 字符数），不打印正文预览。
    # 想看完整分析报告，请运行： python -m src.main
    from src.fetch.rss_fetcher import fetch_all
    from src.parse.shownotes_parser import parse_all

    eps = parse_all(fetch_all())
    decoder = [e for e in eps if e.get("content_strategy") == "theverge_scrape"]
    if not decoder:
        print("没有 theverge_scrape 类型的 episode。")
    else:
        ep = decoder[0]  # feed 按时间倒序，[0] 即最新一集
        enrich_episode_content(ep)
        print("\n" + "=" * 60)
        print("最近一集：", ep["episode_title"])
        print("content_source：", ep.get("content_source"))
        print("文章链接：", ep.get("episode_link"))
        print("full_text 长度：", len(ep.get("full_text", "")), "字符")
