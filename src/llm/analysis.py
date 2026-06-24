"""LLM 深度分析模块。

用高质量模型（Sonnet）对初筛保留的 episode 做两层分析：
  - 逐集：key_points（3–5 条关键论点）、summary（一句话摘要）
  - 整体：cross_episode_insight（跨集综合洞察 / 本期核心判断）

会结合每集命中的 framework_ids，把对应的分析框架问题喂给模型。
返回一个 dict：{"cross_episode_insight": [...], "episodes": [...]}。
"""

from __future__ import annotations

import json

import yaml

from src.llm.client import LLMClient, extract_json
from src.utils.config import get_filters, load_prompt
from src.utils.logger import get_logger

log = get_logger(__name__)

# 注意：深度分析会把每集的【完整】全文喂给模型，不再截断。
# 成本估算见 src/main.py 启动时打印的“成本估算”日志。

# 结构化输出 schema：API 据此保证返回合法 JSON（中文引号会被正确转义）
_EPISODE_SCHEMA = {
    "type": "object",
    "properties": {
        "source_name": {"type": "string"},
        "episode_title": {"type": "string"},
        "guests": {"type": "string"},
        "episode_link": {"type": "string"},
        "summary": {"type": "string"},
        "podcast_key_points": {"type": "array", "items": {"type": "string"}},
        "key_quotes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "speaker": {"type": "string"},
                    "quote": {"type": "string"},
                },
                "required": ["speaker", "quote"],
                "additionalProperties": False,
            },
        },
        "competitive_moves": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "point": {"type": "string"},      # 数据/动作描述（中文）
                    "evidence": {"type": "string"},   # 文字稿逐字原文（原始语言）
                },
                "required": ["point", "evidence"],
                "additionalProperties": False,
            },
        },
        "strategic_relevance": {"type": "string"},
    },
    "required": [
        "source_name", "episode_title", "guests", "episode_link", "summary",
        "podcast_key_points", "key_quotes", "competitive_moves", "strategic_relevance",
    ],
    "additionalProperties": False,
}

ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "cross_episode_insight": {"type": "array", "items": {"type": "string"}},
        "episodes": {"type": "array", "items": _EPISODE_SCHEMA},
    },
    "required": ["cross_episode_insight", "episodes"],
    "additionalProperties": False,
}


def _frameworks_text(episodes: list[dict], filters: dict) -> str:
    """只挑出本期实际命中的 framework，连同它们的问题，序列化成文本。"""
    triggered: set[str] = set()
    for ep in episodes:
        for fid in ep.get("framework_ids", []) or []:
            triggered.add(fid)

    all_fw = {fw["id"]: fw for fw in filters.get("analysis_framework", [])}
    chosen = [all_fw[fid] for fid in triggered if fid in all_fw]

    if not chosen:
        # 没命中任何框架就给一个通用提示
        return "（本期未命中特定分析框架，请按通用情报视角提炼关键论点。）"
    return yaml.safe_dump(chosen, allow_unicode=True, sort_keys=False)


def _build_payload(episodes: list[dict]) -> str:
    items = []
    for ep in episodes:
        items.append(
            {
                "source_name": ep.get("source_name", ""),
                "episode_title": ep.get("episode_title", ""),
                "guests": ep.get("guests", ""),
                "episode_link": ep.get("episode_link", ""),
                "tags": ep.get("tags", []),
                "framework_ids": ep.get("framework_ids", []),
                # 优先用增强后的【完整】全文（如 The Verge 文字稿）；没有则回退 Show Notes
                "content": ep.get("full_text") or ep.get("clean_shownotes") or "",
            }
        )
    return json.dumps(items, ensure_ascii=False, indent=2)


def analyze(episodes: list[dict]) -> dict:
    """对初筛保留（is_relevant=True）的 episode 做深度分析。"""
    kept = [e for e in episodes if e.get("is_relevant")]
    if not kept:
        log.warning("没有相关 episode，跳过深度分析。")
        return {"cross_episode_insight": [], "episodes": []}

    client = LLMClient()
    prompt_tpl = load_prompt("analysis_prompt.txt")
    filters = get_filters()

    prompt = (
        prompt_tpl.replace("<<FRAMEWORKS>>", _frameworks_text(kept, filters))
        .replace("<<EPISODES_PAYLOAD>>", _build_payload(kept))
    )

    log.info("开始深度分析 %d 集（模型：%s）…", len(kept), client.analysis_model)
    raw = client.analyze(prompt, output_schema=ANALYSIS_SCHEMA)
    try:
        result = extract_json(raw)
    except Exception as e:  # noqa: BLE001
        log.error("深度分析结果解析失败：%s", e)
        raise

    # 把每集的内容来源标记（full_transcript / show_notes only）回填到 LLM 输出上，
    # 这样最终报告能逐集显示用的是全文还是 Show Notes。
    by_title = {e.get("episode_title", "").strip(): e.get("content_source", "")
                for e in kept}
    for ep in result.get("episodes", []):
        ep["content_source"] = by_title.get(ep.get("episode_title", "").strip(), "")

    n_ins = len(result.get("cross_episode_insight", []))
    n_eps = len(result.get("episodes", []))
    log.info("深度分析完成：%d 条核心判断，%d 集摘要。", n_ins, n_eps)
    return result


if __name__ == "__main__":
    # 单独测试：python -m src.llm.analysis （需要 ANTHROPIC_API_KEY）
    from src.fetch.rss_fetcher import fetch_all
    from src.parse.shownotes_parser import parse_all
    from src.llm.screening import screen_all

    res = analyze(screen_all(parse_all(fetch_all())))
    print("\n" + "=" * 60)
    print(json.dumps(res, ensure_ascii=False, indent=2))
