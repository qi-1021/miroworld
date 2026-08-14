"""OpenAI-compatible 服务商模板。

模板只提供识别和默认路径，不限制用户在专家模式中覆盖端点。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ProviderTemplate:
    provider_id: str
    name: str
    host_markers: tuple[str, ...]
    default_base_path: str = "/v1"
    models_path: str = "/models"
    chat_path: str = "/chat/completions"
    embedding_path: str = "/embeddings"
    allow_empty_key: bool = False


PROVIDER_TEMPLATES: tuple[ProviderTemplate, ...] = (
    ProviderTemplate("openai", "OpenAI", ("api.openai.com",)),
    ProviderTemplate(
        "dashscope",
        "阿里百炼",
        ("dashscope.aliyuncs.com",),
        default_base_path="/compatible-mode/v1",
    ),
    ProviderTemplate("deepseek", "DeepSeek", ("api.deepseek.com",)),
    ProviderTemplate("openrouter", "OpenRouter", ("openrouter.ai",)),
    ProviderTemplate(
        "ollama",
        "Ollama",
        ("localhost:11434", "127.0.0.1:11434", "ollama"),
        models_path="/api/tags",
        allow_empty_key=True,
    ),
    ProviderTemplate(
        "lm-studio",
        "LM Studio",
        ("localhost:1234", "127.0.0.1:1234", "lmstudio"),
        allow_empty_key=True,
    ),
    ProviderTemplate(
        "vllm",
        "vLLM",
        ("vllm",),
        allow_empty_key=True,
    ),
)

CUSTOM_PROVIDER = ProviderTemplate(
    "custom", "自定义 OpenAI-compatible", tuple(), allow_empty_key=True
)


def match_provider(host_with_port: str) -> ProviderTemplate:
    target = host_with_port.lower()
    for template in PROVIDER_TEMPLATES:
        if any(marker in target for marker in template.host_markers):
            return template
    return CUSTOM_PROVIDER


def list_provider_templates() -> Iterable[ProviderTemplate]:
    return (*PROVIDER_TEMPLATES, CUSTOM_PROVIDER)
