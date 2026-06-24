"""入口：串联整条流水线（P0 版本，最后只打印报告，不写飞书）。

运行：python -m src.main

流程：
  [1] RSS 抓取        src/fetch/rss_fetcher.py        （只拿 Show Notes）
  [2] Show Notes 清洗  src/parse/shownotes_parser.py
  [3] LLM 初筛         src/llm/screening.py            （基于 Show Notes 判相关性）
  [4] 全文增强        src/fetch/content_enricher.py   （仅对相关 episode 抓全文）
  [5] LLM 深度分析     src/llm/analysis.py             （基于全文）
  [6] 打印报告         （P1 阶段再换成写入飞书）
"""

from __future__ import annotations

from datetime import datetime

from src.fetch.rss_fetcher import fetch_all
from src.fetch.content_enricher import enrich_all
from src.fetch.youtube_pipeline import collect_ready_youtube_episodes
from src.parse.shownotes_parser import parse_all
from src.utils.config import get_sources
from src.llm.screening import screen_dispatch
from src.llm.analysis import analyze
from src.output.feishu_webhook import is_configured as feishu_configured, send_report
from src.utils.logger import get_logger

log = get_logger(__name__)


def render_report(result: dict) -> str:
    """把深度分析结果渲染成易读的中文文本报告（终端预览用）。"""
    today = datetime.now().strftime("%Y-%m-%d")
    lines: list[str] = []
    lines.append("=" * 64)
    lines.append(f"  {today} 播客情报周报")
    lines.append("=" * 64)

    insights = result.get("cross_episode_insight", [])
    lines.append("\n【本期核心判断】")
    if insights:
        for i, ins in enumerate(insights, 1):
            lines.append(f"  {i}. {ins}")
    else:
        lines.append("  （无）")

    lines.append("\n【各集摘要】")
    episodes = result.get("episodes", [])
    if not episodes:
        lines.append("  （本期没有相关 episode）")
    for ep in episodes:
        lines.append("\n" + "-" * 60)
        lines.append(f"  播客：{ep.get('source_name', '')}")
        lines.append(f"  集名：{ep.get('episode_title', '')}")
        if ep.get("content_source"):
            lines.append(f"  内容来源：{ep.get('content_source')}")
        if ep.get("guests"):
            lines.append(f"  嘉宾：{ep.get('guests')}")
        lines.append(f"  一句话摘要：{ep.get('summary', '')}")

        # 主体（80%）：播客实际讲了什么
        # 兼容旧字段名 key_points
        points = ep.get("podcast_key_points") or ep.get("key_points") or []
        if points:
            lines.append("\n  📌 播客要点（实际内容）：")
            for kp in points:
                lines.append(f"    • {kp}")

        quotes = ep.get("key_quotes") or []
        if quotes:
            lines.append("\n  💬 关键原话 / 论断：")
            for q in quotes:
                speaker = q.get("speaker", "") if isinstance(q, dict) else ""
                quote = q.get("quote", "") if isinstance(q, dict) else str(q)
                lines.append(f"    “{quote}”  —— {speaker}")

        moves = ep.get("competitive_moves") or []
        if moves:
            lines.append("\n  🏢 竞品动向（附文字稿原文）：")
            for m in moves:
                if isinstance(m, dict):
                    lines.append(f"    • {m.get('point', '')}")
                    if m.get("evidence"):
                        lines.append(f"        ↳ 原文：{m.get('evidence')}")
                else:  # 兼容旧格式（纯字符串）
                    lines.append(f"    • {m}")

        rel = ep.get("strategic_relevance", "")
        if rel:
            lines.append(f"\n  🎯 对我们的意义：{rel}")

        if ep.get("episode_link"):
            lines.append(f"\n  原集链接：{ep.get('episode_link')}")

    lines.append("\n" + "=" * 64)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 成本估算（深度分析用 claude-sonnet-4-6，价格与 claude-sonnet-4-5 相同：
#   输入约 $3 / 百万 tokens，输出约 $15 / 百万 tokens）
#
# 单集 Decoder 完整文字稿 ≈ 66,000 字符 ≈ 16,500 tokens：
#   - 深度分析输入  ≈ 16,500（全文）+ ~2,000（框架/指令）≈ 18,500 tokens
#       → 18,500 / 1e6 × $3  ≈ $0.056
#   - 深度分析输出  ≈ 2,000 tokens（结构化报告）
#       → 2,000 / 1e6 × $15  ≈ $0.030
#   - 合计 ≈ $0.086 / 集（初筛用 Haiku，约 $0.003/集，可忽略）
#   - 每周 2–3 集相关 ≈ $0.17 – $0.26 / 周
# 说明：分析是“所有相关集合并成一次调用”，故“每集”为边际近似；
#       输出长度会随集数和篇幅浮动。
# ---------------------------------------------------------------------------
_COST_NOTE = (
    "成本估算（Sonnet，$3/$15 每百万 tokens）：单集完整文字稿"
    "≈1.65万 tokens输入 + ~2千输出 ≈ $0.09/集；每周 2–3 集 ≈ $0.17–0.26。"
    "初筛(Haiku)可忽略。"
)


def main() -> None:
    log.info("===== 播客摘要流水线开始 =====")
    log.info("💰 %s", _COST_NOTE)

    episodes = fetch_all()                 # [1] 抓取
    if not episodes:
        log.warning("没有抓到任何 episode，流程结束。请检查 sources.yaml 的 RSS 地址。")
        return

    episodes = parse_all(episodes)         # [2] 清洗 Show Notes
    episodes = screen_dispatch(episodes)   # [3] 初筛（按各源 screening：claude / keyword）

    # [4] 仅对「相关」的 episode 补全全文（如 The Verge 文字稿），省时省钱
    relevant = [e for e in episodes if e.get("is_relevant")]
    if relevant:
        log.info("对 %d 集相关 episode 补全全文…", len(relevant))
        enrich_all(relevant)

    # [4b] YouTube 源：关键词初筛(不花 Claude) → 抓字幕 → 直接得到可分析全文
    window_days = int(get_sources().get("window_days", 14))
    yt_episodes = collect_ready_youtube_episodes(window_days)
    episodes = episodes + yt_episodes

    result = analyze(episodes)             # [5] 深度分析（基于全文）

    report = render_report(result)         # [6] 渲染报告
    print("\n" + report)

    # [7] 推送到飞书（仅当 .env 配置了 FEISHU_WEBHOOK_URL）
    if feishu_configured():
        log.info("检测到 FEISHU_WEBHOOK_URL，推送报告到飞书…")
        send_report(result)
    else:
        log.info("未配置 FEISHU_WEBHOOK_URL，跳过飞书推送（仅终端打印）。")

    log.info("===== 流水线结束 =====")


if __name__ == "__main__":
    main()
