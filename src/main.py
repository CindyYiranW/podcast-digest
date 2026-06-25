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

import os
from datetime import datetime

from src.fetch.rss_fetcher import fetch_all
from src.fetch.content_enricher import enrich_all
from src.fetch.youtube_captions_fetcher import cookies_configured
from src.fetch.youtube_pipeline import collect_youtube_episodes
from src.integrations.feishu_sheet import append_episodes_to_sheet
from src.parse.shownotes_parser import parse_all
from src.utils.cache import filter_unprocessed, mark_terminal
from src.utils.config import get_sources
from src.llm.screening import screen_dispatch
from src.llm.analysis import analyze
from src.output.feishu_webhook import is_configured as feishu_configured, send_report
from src.utils.logger import get_logger

log = get_logger(__name__)


def _render_episode(ep: dict) -> list[str]:
    """渲染单集的详情块（访谈区/话题区共用）。"""
    lines: list[str] = []
    lines.append("\n" + "-" * 60)
    lines.append(f"  播客：{ep.get('source_name', '')}")
    lines.append(f"  集名：{ep.get('episode_title', '')}")
    if ep.get("content_source"):
        lines.append(f"  内容来源：{ep.get('content_source')}")
    guest = ep.get("guest") or ep.get("guests") or ""
    if guest:
        gt = ep.get("guest_title", "")
        star = " ⭐竞品高管" if ep.get("guest_is_priority") else ""
        lines.append(f"  嘉宾：{guest}" + (f" — {gt}" if gt else "") + star)
    lines.append(f"  一句话摘要：{ep.get('summary', '')}")

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
        for mv in moves:
            if isinstance(mv, dict):
                lines.append(f"    • {mv.get('point', '')}")
                if mv.get("evidence"):
                    lines.append(f"        ↳ 原文：{mv.get('evidence')}")
            else:
                lines.append(f"    • {mv}")

    rel = ep.get("strategic_relevance", "")
    if rel:
        lines.append(f"\n  🎯 对我们的意义：{rel}")

    if ep.get("episode_link"):
        lines.append(f"\n  原集链接：{ep.get('episode_link')}")
    return lines


def render_report(result: dict, no_transcript: list | None = None) -> str:
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

    episodes = result.get("episodes", [])
    interviews = [e for e in episodes if e.get("guest_is_priority")]
    topics = [e for e in episodes if not e.get("guest_is_priority")]

    # —— 主板块：竞品高管访谈 ——
    lines.append("\n" + "█" * 64)
    lines.append("  🎙️ 本期竞品高管访谈（重点）")
    lines.append("█" * 64)
    if interviews:
        for ep in interviews:
            lines.extend(_render_episode(ep))
    else:
        lines.append("\n  （本期没有竞品高管访谈）")

    # —— 次板块：其他强相关行业话题 ——
    if topics:
        lines.append("\n" + "─" * 64)
        lines.append("  📌 其他强相关行业话题")
        lines.append("─" * 64)
        for ep in topics:
            lines.extend(_render_episode(ep))

    if no_transcript:
        # 优先访谈排前面
        nt = sorted(no_transcript, key=lambda e: e.get("guest_is_priority", False), reverse=True)
        lines.append("\n【相关但无文字稿 · 未做深度分析】")
        for ep in nt:
            star = " ⭐竞品高管访谈" if ep.get("guest_is_priority") else ""
            lock = " 🔒付费墙" if ep.get("paywalled") else ""
            lines.append(f"  • {ep.get('source_name', '')}｜{ep.get('episode_title', '')}{star}{lock}")
            if ep.get("guest"):
                gt = ep.get("guest_title", "")
                lines.append(f"      嘉宾：{ep.get('guest')}" + (f" — {gt}" if gt else ""))
            link = ep.get("episode_link") or ep.get("youtube_url")
            if link:
                lines.append(f"      {link}")

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


_YOUTUBE_STRATEGIES = ("youtube_channel_rss", "youtube_match_captions")


def _warn_if_youtube_unauthed() -> None:
    """启动自检：有 YouTube 源但没配 cookie 时，提前大声提醒。

    无人值守/服务器 IP 抓 YouTube 字幕几乎一定被 bot 拦。没 cookie 不会报错，
    只是这些源会静默退化成「相关但无文字稿」，容易被忽略——所以这里先警告一次。
    """
    if cookies_configured():
        return
    yt_sources = [
        s.get("name", "?")
        for s in get_sources().get("sources", [])
        if s.get("enabled", False) and s.get("content_strategy") in _YOUTUBE_STRATEGIES
    ]
    if not yt_sources:
        return
    log.warning(
        "⚠️ 检测到 YouTube 源但未配 cookie：%s\n"
        "    无人值守/服务器 IP 抓字幕大概率被 YouTube 拦截（status=blocked），"
        "这些源会退化成「相关但无文字稿」。\n"
        "    解决：在 .env 里设 YOUTUBE_COOKIES_FILE=/路径/cookies.txt（服务器）"
        "或 YOUTUBE_COOKIES_FROM_BROWSER=safari（本机）。\n"
        "    详见 README「YouTube transcripts: cookies setup」。",
        "、".join(yt_sources),
    )


def main() -> None:
    log.info("===== 播客摘要流水线开始 =====")
    log.info("💰 %s", _COST_NOTE)
    _warn_if_youtube_unauthed()            # [0] 启动自检：YouTube cookie

    rss_episodes = fetch_all()             # [1] 抓取
    if not rss_episodes:
        log.warning("没有抓到任何 episode，流程结束。请检查 sources.yaml 的 RSS 地址。")
        return

    rss_episodes = parse_all(rss_episodes)        # [2] 清洗 Show Notes
    # [2b] 跨次去重：跳过上次已处理到终态的 episode（兜底，主要靠 4 天窗口）
    rss_episodes = filter_unprocessed(rss_episodes)
    rss_episodes = screen_dispatch(rss_episodes)  # [3] 初筛（按各源 screening：claude / keyword）

    # [4] 仅对「相关」的 episode 补全全文（如 The Verge 文字稿），省时省钱
    relevant = [e for e in rss_episodes if e.get("is_relevant")]
    if relevant:
        log.info("对 %d 集相关 episode 补全全文…", len(relevant))
        enrich_all(relevant)

    # [4b] YouTube 源：关键词初筛(不花 Claude) → 抓字幕 → 直接得到可分析全文
    #      （返回所有处理过的候选，含未通过初筛/无字幕的，供审计日志用）
    #      YouTube 源自带去重（youtube_pipeline 内部 already_processed/mark_processed）。
    window_days = int(get_sources().get("window_days", 14))
    yt_episodes = collect_youtube_episodes(window_days)
    episodes = rss_episodes + yt_episodes

    # 相关但没拿到文字稿（只剩 show notes）：标记，但不做深度分析
    no_transcript = [e for e in episodes if e.get("is_relevant") and not e.get("enriched")]

    result = analyze(episodes)             # [5] 深度分析（仅「相关且有文字稿」）

    # 把分析得到的一句话摘要回填到原 episode 上（飞书表格审计日志要用）
    summaries = {e.get("episode_title", "").strip(): e.get("summary", "")
                 for e in result.get("episodes", [])}
    for ep in episodes:
        if not ep.get("summary"):
            ep["summary"] = summaries.get(ep.get("episode_title", "").strip(), "")

    report = render_report(result, no_transcript)  # [6] 渲染报告
    print("\n" + report)

    # [7] 推送到飞书（仅当 .env 配置了 FEISHU_WEBHOOK_URL）
    if feishu_configured():
        log.info("检测到 FEISHU_WEBHOOK_URL，推送报告到飞书…")
        send_report(result, no_transcript)
    else:
        log.info("未配置 FEISHU_WEBHOOK_URL，跳过飞书推送（仅终端打印）。")

    # [8] 飞书表格审计日志：把【所有处理过的 episode】追加进表格（默认关闭）
    if os.getenv("FEISHU_SHEET_ENABLED") == "true":
        log.info("FEISHU_SHEET_ENABLED=true，写入飞书表格审计日志…")
        append_episodes_to_sheet(episodes)

    # [9] 跨次去重：把进入终态的 RSS episode 记入本地缓存（下次跳过）。
    #     YouTube 源已在 youtube_pipeline 内部自行记录，这里只管 RSS 源。
    mark_terminal(rss_episodes)

    log.info("===== 流水线结束 =====")


if __name__ == "__main__":
    main()
