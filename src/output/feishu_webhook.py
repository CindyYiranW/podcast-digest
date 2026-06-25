"""飞书自定义机器人 Webhook 推送。

把深度分析结果渲染成飞书「交互卡片」，POST 到群机器人 Webhook：
  - 一张「本期核心判断」汇总卡
  - 每集一张详情卡（要点 / 原话 / 竞品动向 / 对我们的意义 / 链接）

Webhook URL 存在 .env 的 FEISHU_WEBHOOK_URL，不写进代码。
比飞书文档 API 简单：不需要建应用、配文档权限。
"""

from __future__ import annotations

from datetime import datetime

import requests

from src.utils.config import get_env
from src.utils.logger import get_logger

log = get_logger(__name__)

_TIMEOUT = 15


def get_webhook_url() -> str | None:
    return get_env("FEISHU_WEBHOOK_URL")


def is_configured() -> bool:
    url = get_webhook_url()
    return bool(url and url.startswith("http"))


def _post(payload: dict) -> bool:
    """POST 一条消息到飞书。成功返回 True。"""
    url = get_webhook_url()
    if not url:
        log.warning("未配置 FEISHU_WEBHOOK_URL，跳过发送。")
        return False
    try:
        r = requests.post(url, json=payload, timeout=_TIMEOUT)
        data = r.json()
    except Exception as e:  # noqa: BLE001
        log.error("飞书发送请求失败：%s", e)
        return False
    # 飞书成功响应：{"code":0,...} 或旧版 {"StatusCode":0,...}
    code = data.get("code", data.get("StatusCode", -1))
    if code == 0:
        return True
    log.error("飞书返回错误：%s", data)
    return False


def send_text(text: str) -> bool:
    """发送一条纯文本消息（用于连接测试）。"""
    return _post({"msg_type": "text", "content": {"text": text}})


def _card(title: str, markdown: str, template: str = "blue") -> dict:
    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": template,
                "title": {"tag": "plain_text", "content": title},
            },
            "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": markdown}}],
        },
    }


def _insights_markdown(result: dict) -> str:
    lines = ["**【本期核心判断】**", ""]
    insights = result.get("cross_episode_insight", [])
    if insights:
        for i, ins in enumerate(insights, 1):
            lines.append(f"{i}. {ins}")
    else:
        lines.append("（无）")
    return "\n".join(lines)


def _episode_markdown(ep: dict) -> str:
    lines: list[str] = []
    if ep.get("content_source"):
        lines.append(f"**内容来源**：{ep.get('content_source')}")
    guest = ep.get("guest") or ep.get("guests") or ""
    if guest:
        gt = ep.get("guest_title", "")
        star = " ⭐竞品高管" if ep.get("guest_is_priority") else ""
        lines.append(f"**嘉宾**：{guest}" + (f" — {gt}" if gt else "") + star)
    if ep.get("summary"):
        lines.append(f"**一句话摘要**：{ep.get('summary')}")

    points = ep.get("podcast_key_points") or ep.get("key_points") or []
    if points:
        lines.append("\n**📌 播客要点（实际内容）**")
        for kp in points:
            lines.append(f"• {kp}")

    quotes = ep.get("key_quotes") or []
    if quotes:
        lines.append("\n**💬 关键原话 / 论断**")
        for q in quotes:
            if isinstance(q, dict):
                lines.append(f"「{q.get('quote', '')}」 —— {q.get('speaker', '')}")
            else:
                lines.append(f"「{q}」")

    moves = ep.get("competitive_moves") or []
    if moves:
        lines.append("\n**🏢 竞品动向（附文字稿原文）**")
        for m in moves:
            if isinstance(m, dict):
                lines.append(f"• {m.get('point', '')}")
                if m.get("evidence"):
                    lines.append(f"  ↳ 原文：{m.get('evidence')}")
            else:  # 兼容旧格式
                lines.append(f"• {m}")

    rel = ep.get("strategic_relevance", "")
    if rel:
        lines.append(f"\n**🎯 对我们的意义**：{rel}")

    if ep.get("episode_link"):
        lines.append(f"\n[原集链接]({ep.get('episode_link')})")

    return "\n".join(lines)


def send_report(result: dict, no_transcript: list | None = None) -> bool:
    """把整份报告推送到飞书群。返回是否全部成功。"""
    if not is_configured():
        log.info("未配置 FEISHU_WEBHOOK_URL，跳过飞书推送。")
        return False

    today = datetime.now().strftime("%Y-%m-%d")
    ok = True

    # 1) 汇总卡：本期核心判断
    ok &= _post(_card(f"📻 {today} 播客情报周报", _insights_markdown(result), "blue"))

    episodes = result.get("episodes", [])
    interviews = [e for e in episodes if e.get("guest_is_priority")]
    topics = [e for e in episodes if not e.get("guest_is_priority")]

    def _ep_card(ep: dict, template: str) -> None:
        nonlocal ok
        title = f"🎙️ {ep.get('source_name', '')}｜{ep.get('episode_title', '')}"
        if len(title) > 100:
            title = title[:97] + "…"
        ok &= _post(_card(title, _episode_markdown(ep), template))

    # 2) 主板块：竞品高管访谈（分隔卡 + 每集详情，亮色）
    ok &= _post(_card("🎙️ 本期竞品高管访谈（重点）",
                      f"本期共 {len(interviews)} 场竞品/重要公司高管访谈。" if interviews
                      else "本期没有竞品高管访谈。", "turquoise"))
    for ep in interviews:
        _ep_card(ep, "turquoise")

    # 3) 次板块：其他强相关行业话题
    if topics:
        ok &= _post(_card("📌 其他强相关行业话题", f"另有 {len(topics)} 个强相关话题。", "wathet"))
        for ep in topics:
            _ep_card(ep, "wathet")

    # 4) 相关但无文字稿的集子：只列出，不做深度分析
    if no_transcript:
        md = "\n".join(
            f"• {('⭐ ' if ep.get('guest_is_priority') else '')}{ep.get('source_name', '')}"
            f"｜{ep.get('episode_title', '')}"
            f"{'　🔒 付费墙（订阅者专享）' if ep.get('paywalled') else ''}"
            for ep in no_transcript
        )
        ok &= _post(_card("📄 相关但无文字稿（未做深度分析）", md, "grey"))

    if ok:
        log.info("✅ 已推送到飞书：访谈 %d 场 + 话题 %d 个。", len(interviews), len(topics))
    else:
        log.warning("⚠️ 飞书推送部分失败，请看上面的错误日志。")
    return ok


if __name__ == "__main__":
    # 连接测试：python -m src.output.feishu_webhook
    # 发一条文本 + 一张示例卡到你的飞书群，验证 Webhook 是否打通。
    print("发送连接测试到飞书…")
    ok1 = send_text("✅ 播客摘要系统 · 飞书 Webhook 连接测试成功")
    sample = {
        "cross_episode_insight": ["这是一条示例核心判断（连接测试）。"],
        "episodes": [
            {
                "source_name": "示例播客",
                "episode_title": "这是一张示例详情卡",
                "content_source": "full_transcript (The Verge)",
                "guests": "示例嘉宾",
                "summary": "用于验证飞书卡片排版是否正常。",
                "podcast_key_points": ["要点一", "要点二"],
                "key_quotes": [{"speaker": "示例嘉宾", "quote": "这是一句示例原话。"}],
                "competitive_moves": ["示例竞品动作"],
                "strategic_relevance": "示例：对我们的意义一句话。",
                "episode_link": "https://www.theverge.com",
            }
        ],
    }
    ok2 = send_report(sample)
    print("文本测试:", "成功" if ok1 else "失败", "| 卡片测试:", "成功" if ok2 else "失败")
