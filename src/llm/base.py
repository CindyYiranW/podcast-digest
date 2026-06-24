"""LLM provider 抽象接口。

所有具体厂商（Anthropic / 火山方舟 / OpenAI…）都实现这个接口。
业务逻辑只依赖这个抽象，不关心底层是谁。

切换厂商时，只需新增一个实现这个接口的 provider，业务代码不用动。
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """一个 LLM 厂商的最小能力：给定模型名和提示词，返回文本。"""

    @abstractmethod
    def complete(
        self,
        *,
        model: str,
        prompt: str,
        max_tokens: int,
        schema: dict | None = None,
    ) -> str:
        """调用模型，返回它输出的文本。

        参数：
          model       要用的模型名（由上层根据任务选好）
          prompt      完整提示词
          max_tokens  最大输出 token 数
          schema      若提供，则要求输出是“严格符合该 JSON Schema 的合法 JSON”。
                      各 provider 负责把这个中立的 schema 翻译成自己的结构化输出机制
                      （Anthropic 用 output_config；OpenAI/火山用 response_format）。

        返回：模型输出的字符串（schema 非空时应为合法 JSON 文本）。
        """
        raise NotImplementedError
