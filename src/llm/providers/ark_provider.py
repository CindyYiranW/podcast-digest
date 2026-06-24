"""火山方舟（Volcengine Ark）provider 实现。

火山方舟提供 OpenAI 兼容接口，所以这里用 openai SDK，指向火山的 base_url。

==== 将来要切到火山方舟时，你只需要做 3 件事 ====
1. 安装依赖：   pip install openai
2. 在 .env 里：
       LLM_PROVIDER=ark
       ARK_API_KEY=你的火山方舟 API Key
       LLM_SCREENING_MODEL=<火山的初筛模型/接入点ID，如 doubao-lite-...>
       LLM_ANALYSIS_MODEL=<火山的分析模型/接入点ID，如 doubao-seed-... 或 doubao-pro-...>
3. 不用改任何业务代码——facade 会自动用这个 provider。

（结构化输出：火山兼容 OpenAI 的 response_format。不同模型对 json_schema 的支持
程度不同；若某模型只支持 json_object，可把下面 _RESPONSE_FORMAT_MODE 改成 "json_object"。）
"""

from __future__ import annotations

import json

from src.llm.base import LLMProvider
from src.utils.config import get_env

ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"

# "json_schema"（更严格）或 "json_object"（更宽松、靠 prompt 保证字段）
_RESPONSE_FORMAT_MODE = "json_schema"


class ArkProvider(LLMProvider):
    name = "ark"

    def __init__(self) -> None:
        try:
            from openai import OpenAI  # 懒加载：只有真正用火山时才需要
        except ImportError as e:  # noqa: BLE001
            raise RuntimeError(
                "要使用火山方舟，请先安装 openai 库：pip install openai"
            ) from e

        api_key = get_env("ARK_API_KEY") or get_env("LLM_ANALYSIS_API_KEY")
        if not api_key:
            raise RuntimeError(
                "没找到火山方舟 API Key。请在 .env 里设置 ARK_API_KEY=..."
            )
        base_url = get_env("ARK_BASE_URL", ARK_BASE_URL)
        self.client = OpenAI(api_key=api_key, base_url=base_url)

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
            if _RESPONSE_FORMAT_MODE == "json_schema":
                kwargs["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "output", "schema": schema, "strict": True},
                }
            else:
                kwargs["response_format"] = {"type": "json_object"}

        resp = self.client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""
