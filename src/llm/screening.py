"""LLM 初筛模块。

用便宜模型（Haiku）对每条 episode 做相关性判断、打分、打标签、并选出
应使用的分析框架（framework_ids）。判断标准来自 config/filters.yaml。

在 episode 字典上补充：
  is_relevant      bool
  relevance_score  0-10
  tags             命中的话题/竞品标签
  framework_ids    深度分析阶段要用的框架 id
  reason           一句话理由（中文）
"""

from __future__ import annotations

import yaml

from src.filters.keyword_filter import match_keywords
from src.llm.client import LLMClient, extract_json
from src.utils.config import get_filters, load_prompt
from src.utils.logger import get_logger

log = get_logger(__name__)

# 喂给模型的 Show Notes 最长字符数（控制成本；初筛不需要全文）
SHOWNOTES_LIMIT = 4000

# 结构化输出 schema：API 据此保证返回合法 JSON
SCREENING_SCHEMA = {
    "type": "object",
    "properties": {
        "is_relevant": {"type": "boolean"},
        "relevance_score": {"type": "integer"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "framework_ids": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
        "guest": {"type": "string"},            # 嘉宾姓名（无嘉宾/主持人独白则空）
        "guest_title": {"type": "string"},      # 嘉宾职位 + 公司
        "guest_is_priority": {"type": "boolean"},  # 是否竞品/重要公司高管 → 优先访谈
    },
    "required": [
        "is_relevant", "relevance_score", "tags", "framework_ids", "reason",
        "guest", "guest_title", "guest_is_priority",
    ],
    "additionalProperties": False,
}

# 从 filters.yaml 里挑这些段落注入 Prompt（output_schema 不需要给模型）
_CRITERIA_SECTIONS = [
    "identity",
    "relevant_topics",
    "competitor_companies",
    "analysis_framework",
    "exclude_topics",
    "scoring",
    "guest_priority",
]


def _build_criteria_text(filters: dict) -> str:
    subset = {k: filters[k] for k in _CRITERIA_SECTIONS if k in filters}
    return yaml.safe_dump(subset, allow_unicode=True, sort_keys=False)


def screen_episode(ep: dict, client: LLMClient, prompt_tpl: str, criteria: str) -> dict:
    notes = (ep.get("clean_shownotes") or "")[:SHOWNOTES_LIMIT]
    prompt = (
        prompt_tpl.replace("<<SCREENING_CRITERIA>>", criteria)
        .replace("<<SOURCE_NAME>>", ep.get("source_name", ""))
        .replace("<<EPISODE_TITLE>>", ep.get("episode_title", ""))
        .replace("<<CLEAN_SHOWNOTES>>", notes)
    )

    try:
        raw = client.screen(prompt, output_schema=SCREENING_SCHEMA)
        data = extract_json(raw)
        ep["is_relevant"] = bool(data.get("is_relevant", False))
        ep["relevance_score"] = int(data.get("relevance_score", 0))
        ep["tags"] = data.get("tags", []) or []
        ep["framework_ids"] = data.get("framework_ids", []) or []
        ep["reason"] = data.get("reason", "")
        ep["guest"] = data.get("guest", "") or ""
        ep["guest_title"] = data.get("guest_title", "") or ""
        ep["guest_is_priority"] = bool(data.get("guest_is_priority", False))
        # 竞品高管访谈是本工具的主产物 → 永远视为相关
        if ep["guest_is_priority"]:
            ep["is_relevant"] = True
    except Exception as e:  # noqa: BLE001
        # 解析失败时不要静默丢弃：保守保留，并标记出来，方便你看到。
        log.warning("初筛「%s」失败，保守保留：%s", ep.get("episode_title"), e)
        ep["is_relevant"] = True
        ep["relevance_score"] = 5
        ep["tags"] = []
        ep["framework_ids"] = []
        ep["reason"] = "初筛结果解析失败，已保守保留待人工确认"
        ep["guest"] = ""
        ep["guest_title"] = ""
        ep["guest_is_priority"] = False
    return ep


def screen_all(episodes: list[dict]) -> list[dict]:
    if not episodes:
        return []
    client = LLMClient()
    prompt_tpl = load_prompt("screening_prompt.txt")
    criteria = _build_criteria_text(get_filters())

    log.info("开始初筛 %d 集（模型：%s）…", len(episodes), client.screening_model)
    for i, ep in enumerate(episodes, 1):
        screen_episode(ep, client, prompt_tpl, criteria)
        flag = "✅相关" if ep["is_relevant"] else "❌不相关"
        log.info(
            "  [%d/%d] %s 分%d %s | %s",
            i, len(episodes), flag, ep["relevance_score"],
            ep["episode_title"][:40], ep["reason"],
        )

    kept = [e for e in episodes if e["is_relevant"]]
    log.info("初筛完成：%d 集相关 / 共 %d 集。", len(kept), len(episodes))
    return episodes


def keyword_screen(episodes: list[dict]) -> list[dict]:
    """关键词初筛（不调用 Claude）。用 filters.yaml 的关键词匹配 title+show notes。"""
    if not episodes:
        return episodes
    log.info("关键词初筛 %d 集（不调用 Claude）…", len(episodes))
    for ep in episodes:
        hits = match_keywords(ep.get("episode_title", ""), ep.get("clean_shownotes", ""))
        ep["is_relevant"] = bool(hits)
        ep["relevance_score"] = 7 if hits else 2
        ep["tags"] = hits
        ep["framework_ids"] = []
        ep["reason"] = "keyword_filter_matched" if hits else "keyword_filter_not_matched"
        ep["guest"] = ""           # 关键词初筛不判断嘉宾
        ep["guest_title"] = ""
        ep["guest_is_priority"] = False
        flag = "✅相关" if hits else "❌不相关"
        log.info("  [关键词] %s %s | 命中:%s",
                 flag, ep.get("episode_title", "")[:40], hits[:4])
    return episodes


def screen_dispatch(episodes: list[dict]) -> list[dict]:
    """按每集 source 的 screening 字段分派：claude（默认）或 keyword。"""
    kw_eps = [e for e in episodes if e.get("screening") == "keyword"]
    claude_eps = [e for e in episodes if e.get("screening", "claude") != "keyword"]
    if kw_eps:
        keyword_screen(kw_eps)
    if claude_eps:
        screen_all(claude_eps)
    return episodes


if __name__ == "__main__":
    # 单独测试：python -m src.llm.screening （需要已配置 ANTHROPIC_API_KEY）
    from src.fetch.rss_fetcher import fetch_all
    from src.parse.shownotes_parser import parse_all

    eps = screen_all(parse_all(fetch_all()))
    print("\n" + "=" * 60)
    for ep in eps:
        print(f"[{'相关' if ep['is_relevant'] else '不相关'}] 分{ep['relevance_score']} "
              f"{ep['episode_title']}")
        print(f"    tags={ep['tags']}  frameworks={ep['framework_ids']}")
        print(f"    理由：{ep['reason']}\n")
