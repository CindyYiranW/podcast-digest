"""Show Notes 清洗模块。

职责：把 RSS 里带 HTML、广告、订阅引导的 Show Notes 原文，清洗成干净纯文本，
供 LLM 使用。会在 episode 字典上补充：
  clean_shownotes  清洗后的纯文本
  low_content      bool，正文过短（< 阈值）时为 True，交给初筛决定是否丢弃
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from src.utils.config import get_filters
from src.utils.logger import get_logger

log = get_logger(__name__)

# 噪声行：只删“明显是广告/订阅引导/纯链接”的行。
# 原则：宁可少删、保留正文，也不要因为一个品牌词（如 Patreon）就误删整段内容。
# —— 这些都用 search 整行匹配，命中才删；正文段落不会被波及。
_NOISE_PATTERNS = [
    re.compile(r"^\s*(sponsored by|brought to you by)\b", re.I),
    re.compile(r"\b(promo code|use code|discount code|coupon code)\b", re.I),
    re.compile(r"^\s*https?://\S+\s*$"),                       # 整行只有一个链接
    re.compile(r"\b(subscribe to|sign up for)\b.*\b(newsletter|ad-free)\b", re.I),
]


def _strip_html(raw: str) -> str:
    """去掉 HTML 标签，但保留段落结构（每个块级元素之间换行）。"""
    soup = BeautifulSoup(raw or "", "lxml")
    # 去掉 script/style
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    return text


def _drop_noise_lines(text: str) -> str:
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if any(p.search(stripped) for p in _NOISE_PATTERNS):
            continue
        kept.append(stripped)
    return "\n".join(kept)


def _collapse_blank(text: str) -> str:
    # 合并多余空白
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_shownotes(raw: str) -> str:
    text = _strip_html(raw)
    text = _drop_noise_lines(text)
    text = _collapse_blank(text)
    return text


def parse_episode(ep: dict, low_content_threshold: int) -> dict:
    cleaned = clean_shownotes(ep.get("raw_description", ""))
    ep["clean_shownotes"] = cleaned
    ep["low_content"] = len(cleaned) < low_content_threshold
    return ep


def parse_all(episodes: list[dict]) -> list[dict]:
    """对一批 episode 批量清洗。阈值从 filters.yaml 读取。"""
    try:
        threshold = int(get_filters().get("low_content_threshold", 100))
    except Exception:  # noqa: BLE001  —— filters.yaml 里没这个字段也没关系
        threshold = 100

    out = []
    for ep in episodes:
        out.append(parse_episode(ep, threshold))
    low = sum(1 for e in out if e["low_content"])
    log.info("已清洗 %d 集；其中 %d 集正文过短被标记 low_content。", len(out), low)
    return out


if __name__ == "__main__":
    # 单独测试：python -m src.parse.shownotes_parser
    # 抓一条真实数据，打印清洗前后对比。
    from src.fetch.rss_fetcher import fetch_all

    eps = parse_all(fetch_all())
    if not eps:
        print("没抓到 episode，无法测试清洗。")
    else:
        ep = eps[0]
        print("\n" + "=" * 60)
        print(f"示例：{ep['source_name']} - {ep['episode_title']}\n")
        print("---- 清洗前（前 500 字）----")
        print(ep["raw_description"][:500])
        print("\n---- 清洗后（前 500 字）----")
        print(ep["clean_shownotes"][:500])
        print(f"\nlow_content = {ep['low_content']}")
