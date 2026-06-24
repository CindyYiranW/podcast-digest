"""LLM 调用的统一入口（facade）。

业务逻辑（screening / analysis）只用这里的 LLMClient，不直接接触任何厂商 SDK。

职责：
  1. 根据 .env 的 LLM_PROVIDER 选一个 provider 实现（anthropic / ark）
  2. 根据任务（初筛 / 分析）选对应的模型名
  3. 把调用转给 provider

==== 怎么切换厂商 ====
只改 .env（和对应 provider 文件），业务代码不动：
  LLM_PROVIDER=anthropic   # 默认；用 Claude
  LLM_PROVIDER=ark         # 切到火山方舟（需 pip install openai，并填 ARK_API_KEY）
"""

from __future__ import annotations

import json
import re

from src.llm.base import LLMProvider
from src.utils.config import get_env
from src.utils.logger import get_logger

log = get_logger(__name__)

# 每个 provider 的默认模型：（初筛模型, 分析模型）。
# .env 里的 LLM_SCREENING_MODEL / LLM_ANALYSIS_MODEL 会覆盖这里。
_DEFAULT_MODELS = {
    "anthropic": ("claude-haiku-4-5", "claude-sonnet-4-6"),
    # 火山的模型名/接入点ID因账号而异，这里只是占位，请在 .env 里指定真实值
    "ark": ("doubao-lite", "doubao-seed"),
}


def _build_provider(name: str) -> LLMProvider:
    if name == "anthropic":
        from src.llm.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider()
    if name == "ark":
        from src.llm.providers.ark_provider import ArkProvider

        return ArkProvider()
    raise RuntimeError(
        f"未知的 LLM_PROVIDER：{name!r}。目前支持：anthropic、ark。"
    )


class LLMClient:
    def __init__(self) -> None:
        provider_name = (get_env("LLM_PROVIDER", "anthropic") or "anthropic").lower()
        default_screen, default_analysis = _DEFAULT_MODELS.get(
            provider_name, (None, None)
        )
        self.provider = _build_provider(provider_name)
        self.provider_name = provider_name
        self.screening_model = get_env("LLM_SCREENING_MODEL", default_screen)
        self.analysis_model = get_env("LLM_ANALYSIS_MODEL", default_analysis)
        log.info(
            "LLM provider=%s | 初筛=%s | 分析=%s",
            provider_name, self.screening_model, self.analysis_model,
        )

    def screen(self, prompt: str, output_schema: dict | None = None) -> str:
        """初筛：用便宜模型。"""
        return self.provider.complete(
            model=self.screening_model, prompt=prompt,
            max_tokens=1024, schema=output_schema,
        )

    def analyze(self, prompt: str, output_schema: dict | None = None) -> str:
        """深度分析：用高质量模型。"""
        return self.provider.complete(
            model=self.analysis_model, prompt=prompt,
            max_tokens=8000, schema=output_schema,
        )


def extract_json(text: str):
    """从模型返回的文本里稳健地提取 JSON。

    用了结构化输出后一般直接就是合法 JSON；这个函数仍做兜底：
    先直接解析；失败再去掉 ```json``` 包裹 / 截取最外层大括号重试。
    """
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"无法把模型输出解析成 JSON。原始输出：\n{text[:800]}")
