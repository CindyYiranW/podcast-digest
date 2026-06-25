"""飞书表格日志（审计用）。

每次流水线跑完后，把【所有处理过的 episode】（Relevant / Irrelevant / Skipped）
批量追加到一张飞书电子表格，作为审计/留档——避免我们已经花算力处理过的数据丢失。

与飞书 Webhook（src/output/feishu_webhook.py）是两套独立机制：
  - Webhook：群机器人，只需一个 URL，推送精选报告。
  - 本模块：飞书开放平台「自建应用」+ Sheets API，需要 App ID/Secret + 表格权限，
            追加全量明细行。

设计要点：
  - tenant_access_token 带缓存，过期前自动刷新。
  - 一次 API 调用批量追加所有行（不是一行一调）。
  - 任何失败只记日志，绝不抛异常、绝不阻塞主流程。
  - 表格第 1 行已有表头，本模块只追加数据行，不写表头。
"""

from __future__ import annotations

import time
from datetime import datetime

import requests

from src.utils.config import get_env
from src.utils.logger import get_logger

log = get_logger(__name__)

# API 基础域名可配置：飞书(中国)=open.feishu.cn（默认）；Lark(国际)=open.larksuite.com。
# 注意要和你的 App、表格所在实例一致——本项目的 Webhook 在 larkoffice 上，若 App 也在
# Lark 国际版，请把 FEISHU_API_BASE 设为 https://open.larksuite.com。
_DEFAULT_API_BASE = "https://open.feishu.cn"
_TOKEN_PATH = "/open-apis/auth/v3/tenant_access_token/internal"
_APPEND_PATH = "/open-apis/sheets/v2/spreadsheets/{token}/values_append"
_TIMEOUT = 20

# tenant_access_token 缓存
_token_cache: dict = {"token": None, "expires_at": 0.0}


def _api_base() -> str:
    return (get_env("FEISHU_API_BASE") or _DEFAULT_API_BASE).rstrip("/")


def get_tenant_access_token() -> str | None:
    """获取 tenant_access_token（带缓存，过期前 5 分钟刷新）。失败返回 None。"""
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"]:
        return _token_cache["token"]

    app_id = get_env("FEISHU_APP_ID")
    app_secret = get_env("FEISHU_APP_SECRET")
    if not (app_id and app_secret):
        log.error("飞书表格：缺少 FEISHU_APP_ID / FEISHU_APP_SECRET。")
        return None
    try:
        r = requests.post(
            _api_base() + _TOKEN_PATH,
            json={"app_id": app_id, "app_secret": app_secret},
            timeout=_TIMEOUT,
        )
        data = r.json()
    except Exception as e:  # noqa: BLE001
        log.error("飞书表格：获取 token 请求失败：%s", e)
        return None

    if data.get("code") == 0 and data.get("tenant_access_token"):
        _token_cache["token"] = data["tenant_access_token"]
        # expire 单位秒；提前 5 分钟过期
        _token_cache["expires_at"] = now + int(data.get("expire", 7200)) - 300
        return _token_cache["token"]
    log.error("飞书表格：获取 token 返回错误：%s", data)
    return None


def _relevance_status(ep: dict) -> str:
    """Relevant / Irrelevant / Skipped。"""
    if ep.get("is_relevant"):
        return "Relevant"
    # 关键词初筛未命中 → Skipped；Claude 判定不相关 → Irrelevant
    if ep.get("screening") == "keyword":
        return "Skipped"
    return "Irrelevant"


def _published_date(ep: dict) -> str:
    pub = ep.get("published_at")
    if hasattr(pub, "strftime"):
        return pub.strftime("%Y-%m-%d")
    return str(pub) if pub else ""


def _episode_to_row(ep: dict, run_id: str, run_date: str, processed_at: str) -> list:
    """把一个 episode 映射成表格的 12 列（顺序固定，对应 A:L）。"""
    status = _relevance_status(ep)
    if status == "Relevant":
        skip_reason = "" if ep.get("enriched") else "no_transcript"
    else:
        skip_reason = ep.get("reason", "") or ""
    return [
        ep.get("source_name", ""),                                  # A podcast_name
        ep.get("episode_title", ""),                                # B episode_title
        _published_date(ep),                                        # C published_date
        status,                                                     # D relevance_status
        ep.get("relevance_score", ""),                              # E relevance_score
        skip_reason,                                                # F skip_reason
        ep.get("episode_link") or ep.get("youtube_url") or "",      # G podcast_url
        ep.get("content_source", ""),                               # H transcript_source_type
        ep.get("summary", "") or ep.get("reason", ""),              # I summary
        processed_at,                                               # J processed_at
        run_id,                                                     # K pipeline_run_id
        run_date,                                                   # L run_date
    ]


def append_episodes_to_sheet(episodes: list[dict]) -> None:
    """把所有处理过的 episode 一次性批量追加到飞书表格。失败只记日志，不抛异常。"""
    if not episodes:
        log.info("飞书表格：本次没有可写入的 episode。")
        return
    try:
        spreadsheet_token = get_env("FEISHU_SHEET_SPREADSHEET_TOKEN")
        sheet_id = get_env("FEISHU_SHEET_SHEET_ID")
        if not (spreadsheet_token and sheet_id):
            log.error("飞书表格：缺少 FEISHU_SHEET_SPREADSHEET_TOKEN / FEISHU_SHEET_SHEET_ID。")
            return

        token = get_tenant_access_token()
        if not token:
            return  # 已记日志

        now = datetime.now()
        run_id = f"run-{now:%Y%m%d-%H%M%S}"
        run_date = now.strftime("%Y-%m-%d")
        processed_at = now.isoformat(timespec="seconds")
        values = [_episode_to_row(ep, run_id, run_date, processed_at) for ep in episodes]

        url = _api_base() + _APPEND_PATH.format(token=spreadsheet_token)
        body = {"valueRange": {"range": f"{sheet_id}!A:L", "values": values}}
        r = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            json=body,
            timeout=_TIMEOUT,
        )
        data = r.json()
        if data.get("code") == 0:
            log.info("✅ 已追加 %d 行到飞书表格（run_id=%s）。", len(values), run_id)
        else:
            log.error("飞书表格：追加失败：%s", data)
    except Exception as e:  # noqa: BLE001
        log.error("飞书表格：写入异常（不影响主流程）：%s", e)


if __name__ == "__main__":
    # 离线测试行映射（不连飞书）：python -m src.integrations.feishu_sheet
    from datetime import datetime as _dt
    sample = [
        {"source_name": "Trapital", "episode_title": "Apple Music VP on streaming",
         "published_at": _dt(2026, 6, 9), "is_relevant": True, "relevance_score": 9,
         "enriched": True, "content_source": "youtube_transcript (auto)",
         "episode_link": "https://x", "summary": "访谈摘要", "screening": "claude"},
        {"source_name": "Big Technology", "episode_title": "Some chip story",
         "published_at": _dt(2026, 6, 20), "is_relevant": False, "relevance_score": 2,
         "reason": "硬件话题，不相关", "screening": "claude"},
        {"source_name": "Your Morning Coffee", "episode_title": "Random ep",
         "published_at": _dt(2026, 6, 22), "is_relevant": False, "relevance_score": 2,
         "reason": "keyword_filter_not_matched", "screening": "keyword"},
    ]
    rid, rd, pa = "run-test", "2026-06-24", "2026-06-24T10:00:00"
    print("12 列：podcast_name, episode_title, published_date, relevance_status, "
          "relevance_score, skip_reason, podcast_url, transcript_source_type, summary, "
          "processed_at, pipeline_run_id, run_date\n")
    for ep in sample:
        print(_episode_to_row(ep, rid, rd, pa))
