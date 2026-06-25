"""Anthropic（Claude）provider 实现。

把中立的 LLMProvider 接口翻译成 Anthropic SDK 调用。
结构化输出用 Anthropic 的 output_config / json_schema。
"""

from __future__ import annotations

import anthropic

from src.llm.base import LLMProvider
from src.utils.config import get_env


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self) -> None:
        api_key = (
            get_env("ANTHROPIC_API_KEY")
            or get_env("LLM_ANALYSIS_API_KEY")
            or get_env("LLM_SCREENING_API_KEY")
        )
        if not api_key:
            raise RuntimeError(
                "没找到 Anthropic API Key。\n"
                "请在项目根目录的 .env 文件里加一行：\n"
                "    ANTHROPIC_API_KEY=sk-ant-你的key\n"
                "（还没有 .env 就先运行： cp .env.example .env ）"
            )
        # max_retries：SDK 自带指数退避，重试 429/529/5xx（如 overloaded_error）。
        # 逐集分析时，单集偶发过载不该丢整集——多给几次重试。
        self.client = anthropic.Anthropic(api_key=api_key, max_retries=5)

    def complete(
        self,
        *,
        model: str,
        prompt: str,
        max_tokens: int,
        schema: dict | None = None,
    ) -> str:
        kwargs: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if schema is not None:
            # Anthropic 结构化输出：保证返回严格符合 schema 的合法 JSON
            kwargs["output_config"] = {
                "format": {"type": "json_schema", "schema": schema}
            }
        # 用流式：分析这类高 max_tokens / 长输出的请求，非流式会被 SDK 拒绝
        #（"Streaming is required for operations that may take longer than 10 minutes"）。
        # 流式对小请求（初筛）也安全，get_final_message() 拿到完整结果。
        with self.client.messages.stream(**kwargs) as stream:
            msg = stream.get_final_message()
        return "".join(b.text for b in msg.content if b.type == "text")
