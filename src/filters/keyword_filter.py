"""关键词初筛（不调用 Claude，省 token）。

用 config/filters.yaml 里的关键词，对 title + description 做简单字符串匹配。
命中任一关键词 → 该集值得抓字幕送 Claude；未命中 → 跳过。

目的：只有通过初筛的集子才花 Claude token。YouTube/播客的 show notes 多是
话题列表，关键词匹配足够准确。
"""

from __future__ import annotations

import re

from src.utils.config import get_filters
from src.utils.logger import get_logger

log = get_logger(__name__)

# 太短/太通用的词不作为关键词（避免误命中）
_MIN_LEN = 4
_STOP = {"news", "the", "and", "for", "with", "live", "show", "data", "tech", "app", "apps"}

_KEYWORDS_CACHE: set[str] | None = None


def _split_terms(raw: str) -> list[str]:
    """把 "short drama / micro-drama / vertical drama" 拆成多个词，去掉括号注释。"""
    out = []
    for part in str(raw).split("/"):
        t = re.sub(r"\(.*?\)", "", part)        # 去括号
        t = re.sub(r"[#].*$", "", t)            # 去行内注释
        t = t.strip().lower()
        if len(t) >= _MIN_LEN and t not in _STOP:
            out.append(t)
    return out


def load_keywords() -> set[str]:
    """从 filters.yaml 抽取扁平关键词集合（带缓存）。"""
    global _KEYWORDS_CACHE
    if _KEYWORDS_CACHE is not None:
        return _KEYWORDS_CACHE

    f = get_filters()
    terms: set[str] = set()

    # 1) relevant_topics 的 keywords
    for topic in f.get("relevant_topics", []) or []:
        for kw in topic.get("keywords", []) or []:
            terms.update(_split_terms(kw))

    # 2) 竞品公司名
    comps = f.get("competitor_companies", {}) or {}
    for grp in comps.values():
        if isinstance(grp, dict):
            for c in grp.get("companies", []) or []:
                name = re.sub(r"\(.*?\)", "", str(c)).strip().lower()
                if len(name) >= 3 and name not in _STOP:
                    terms.add(name)

    _KEYWORDS_CACHE = terms
    log.info("关键词初筛词表：共 %d 个关键词。", len(terms))
    return terms


def match_keywords(title: str, description: str) -> list[str]:
    """返回命中的关键词列表（可能为空）。"""
    text = f"{title}\n{description}".lower()
    return sorted({kw for kw in load_keywords() if kw in text})


def should_fetch_transcript(title: str, description: str, source_config: dict | None = None) -> bool:
    """命中任一关键词 → True（值得抓字幕）。"""
    return len(match_keywords(title, description)) > 0


if __name__ == "__main__":
    # 测试：python -m src.filters.keyword_filter
    samples = [
        ("Spotify's Plans For AI Generated Music", "streaming, royalties, creators"),
        ("How Google Built Its Ad Business", "advertising infrastructure history"),
    ]
    for t, d in samples:
        hits = match_keywords(t, d)
        print(f"[{'✅' if hits else '❌'}] {t}\n    命中: {hits}\n")
