"""
LLM客户端封装
统一使用OpenAI格式调用
"""

import json
import time
import logging
from typing import Optional, Dict, Any, List
from openai import OpenAI, BadRequestError, APIConnectionError, APITimeoutError

from ..config import Config

logger = logging.getLogger('mirofish.llm')


class LLMClient:
    """LLM客户端"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        max_empty_retries: int = 2,
        disable_thinking: bool = True,
        connection_retries: int = 1
    ):
        self.api_key = api_key or Config.LLM_API_KEY
        self.base_url = base_url or Config.LLM_BASE_URL
        self.model = model or Config.LLM_MODEL_NAME
        self.max_empty_retries = max_empty_retries
        # 默认关闭推理模型的思考：思考会耗尽 max_tokens 导致空响应，
        # 且大幅拖慢响应。网关不支持该参数时自动降级。
        self.disable_thinking = disable_thinking
        # 网络类错误（连接失败/超时）自动重试次数，指数退避，降低偶发抖动把任务打挂的概率
        self.connection_retries = connection_retries

        if not self.api_key:
            raise ValueError("LLM_API_KEY 未配置")

        # 显式直连：httpx 在 macOS 上会自动读取系统代理（如 Clash），
        # 代理对长连接偶发断开会导致调用随机失败。本地部署应直连。
        try:
            import httpx
            http_client = httpx.Client(trust_env=False, timeout=300)
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                http_client=http_client,
            )
        except Exception:
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url
            )

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Dict] = None
    ) -> str:
        """
        发送聊天请求

        Args:
            messages: 消息列表
            temperature: 温度参数
            max_tokens: 最大token数
            response_format: 响应格式（如JSON模式）

        Returns:
            模型响应文本
        """
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if response_format:
            kwargs["response_format"] = response_format

        extra_body = {"thinking": {"type": "disabled"}} if self.disable_thinking else None
        if extra_body:
            kwargs["extra_body"] = extra_body

        # 兼容代理（如 OpenCode 网关）在长提示下偶发返回空内容，
        # 这里自动重试，避免把偶发问题变成硬失败。
        # 连接类错误（断网/超时）再做一次指数退避重试。
        last_content: Optional[str] = None
        for conn_attempt in range(self.connection_retries + 1):
            try:
                response = self.client.chat.completions.create(**kwargs)
                break
            except Exception as exc:
                if extra_body and ("thinking" in str(exc) or "extra_body" in str(exc) or "400" in str(exc) or "422" in str(exc) or isinstance(exc, BadRequestError)):
                    # 网关不支持"关闭思考"参数，降级为不带该参数重试
                    extra_body = None
                    kwargs.pop("extra_body", None)
                    response = self.client.chat.completions.create(**kwargs)
                    break
                if isinstance(exc, (APIConnectionError, APITimeoutError)) and conn_attempt < self.connection_retries:
                    wait = 1.5 * (conn_attempt + 1)
                    logger.warning(
                        "LLM 连接错误（第 %s 次），%.1fs 后重试: model=%s err=%s",
                        conn_attempt + 1, wait, self.model, exc,
                    )
                    time.sleep(wait)
                    continue
                raise
        else:
            # 所有连接重试耗尽仍失败（正常由上面的 raise 抛出，这里兜底）
            raise RuntimeError(f"LLM 连接重试耗尽: model={self.model}")

        for attempt in range(self.max_empty_retries + 1):
            if attempt > 0:
                time.sleep(1.0 + attempt)
            if response.choices:
                last_content = response.choices[0].message.content
            else:
                last_content = None
            if last_content and last_content.strip():
                return last_content
            if attempt < self.max_empty_retries:
                logger.warning(
                    "LLM 返回空响应，准备重试（%s/%s）: model=%s",
                    attempt + 1, self.max_empty_retries, self.model,
                )
                try:
                    response = self.client.chat.completions.create(**kwargs)
                except (APIConnectionError, APITimeoutError):
                    # 空响应重试阶段遇到连接错误不再叠加重试，由下一次循环尝试
                    if attempt < self.max_empty_retries:
                        time.sleep(1.0 + attempt)
                        response = self.client.chat.completions.create(**kwargs)
                    else:
                        raise
        logger.warning(
            "LLM 多次返回空响应，降级为空字符串（调用方按失败处理）: model=%s",
            self.model,
        )
        return last_content or ""

    def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 8192
    ) -> Dict[str, Any]:
        """
        发送聊天请求并返回JSON

        Args:
            messages: 消息列表
            temperature: 温度参数
            max_tokens: 最大token数

        Returns:
            解析后的JSON对象
        """
        response = self.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"}
        )
        try:
            return self._parse_json_response(response)
        except ValueError:
            # 兼容网关在强制 JSON 模式下可能返回空内容或 Markdown，
            # 去掉 response_format 再试一次，由提示词约束 JSON 输出。
            fallback = self.chat(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=None,
            )
            return self._parse_json_response(fallback)

    @staticmethod
    def _parse_json_response(response: str):
        """解析 LLM JSON 输出，兼容 Markdown 围栏和前后说明文本。"""
        if not response or not response.strip():
            raise ValueError("LLM 返回了空响应，无法解析 JSON")
        import re
        raw = re.sub(r'<think>[\s\S]*?</think>', '', response).strip()
        if not raw:
            raise ValueError("LLM 返回了空内容（或全部为思考标签）")
        candidates = [raw]
        if "```" in raw:
            parts = raw.split("```")
            for part in parts[1::2]:
                cleaned = part.strip()
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:].strip()
                if cleaned:
                    candidates.append(cleaned)
        for candidate in candidates:
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(raw[start:end + 1])
            except json.JSONDecodeError:
                pass
        raise ValueError(
            f"LLM 响应不是有效 JSON，已尝试标准解析、Markdown 围栏和 JSON 块提取"
        )

