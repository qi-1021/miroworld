"""LLM / 建图错误归一化。

把 Graphiti 建图、补边、本体生成等流程里抛出的 LLM 提供方原始异常
（openai.BadRequestError/401/连接错误，以及常见的“Request failed with
status code 400”）归一化为可读、可指导的中文错误信息，替代原来的裸 400。

用途：
    在 build/refill 的 except 里调用 normalize_llm_error(e)，
    把 task.error / project.error 设为友好信息，前端即可展示明确引导，
    而不是“Request failed with status code 400”。

设计：
    - 识别“模型配置类错误”，给出定位（哪个模型/哪个端点）与操作指引
      （打开模型设置重新校验 / 换一个模型 / 填 API Key）。
    - 识别网络/连接类错误，给出检查网络与代理的指引。
    - 其余异常原样返回（保留可读最前面一段），不吞信息。
"""

from __future__ import annotations

from typing import Any, Optional


def _is_subclass_of(exc: Exception, *names: str) -> bool:
    """宽松判断异常是否属于指定类名层级（不依赖模块路径，跨 openai/httpx 通用）。"""
    for cls in type(exc).__mro__:
        if cls.__name__ in names:
            return True
    return False


def _snippet(text: str, limit: int = 200) -> str:
    """截断错误文本，保留可读前缀。"""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _looks_like_model_config(err_text: str) -> Optional[str]:
    """从错误文本片段判断是否像“模型名/API Key 配置”问题，返回匹配到的关键词。"""
    t = (err_text or "").lower()
    indicators = [
        # 模型不存在 / 不支持 / 无效模型名
        ("model not found", "模型不存在该端点不支持"), ("unknown model", "模型不存在该端点不支持"),
        ("does not exist", "模型名/资源不存在"), ("model does not exist", "模型名/资源不存在"),
        ("not found", "模型名/资源不存在"), ("model not supported", "该端点不支持该模型"),
        ("unsupported", "该模型不被端点支持"), ("no such model", "该模型不存在"),
        # API Key 类
        ("invalid api key", "API Key 无效"), ("api key", "API Key 问题"),
        ("authentication", "鉴权失败"), ("401", "鉴权失败/API Key 无效"),
        ("bad api key", "API Key 无效"), ("missing api key", "缺少 API Key"),
        # 通用 400
        ("400", "请求参数/模型配置问题"), ("bad request", "请求参数/模型配置问题"),
    ]
    for kw, label in indicators:
        if kw in t:
            return label
    return None


def normalize_llm_error(exc: Exception, *, default: Optional[str] = None) -> str:
    """把 LLM/Graphiti 异常归一化为可指导的中文信息。

    Args:
        exc: 抛出异常
        default: 未识别时是否返回默认引导（None 表示返回原始异常文本）

    Returns:
        归一化后的单行错误信息。
    """
    if exc is None:
        return default or "未知错误"

    err_text = str(exc) or type(exc).__name__
    low = err_text.lower()

    # 1) 未配置（空 key / 空 base_url / 空 model）
    is_openai_err = _is_subclass_of(
        exc, "__httpx__", "APIError", "OpenAIError", "APIConnectionError",
        "BadRequestError", "AuthenticationError", "APITimeoutError",
    )
    if isinstance(exc, (ValueError, TypeError)) and (
        "未配置" in err_text or "not configured" in low or "api_key" in low and ("blank" in low or "missing" in low or "empty" in low)
    ):
        return (
            "模型配置缺失：请打开「模型设置」添加并校验（验证）一个可用模型，"
            "必填 API Key、接口地址与模型名。"
        )

    # 2) API Key / 鉴权错误（401 或 openai.AuthenticationError）
    if _is_subclass_of(exc, "AuthenticationError") or "401" in low or "invalid api key" in low or "authentication" in low:
        snippet = _snippet(err_text)
        return (
            "模型鉴权失败（API Key 无效或过期）：请打开「模型设置」重新校验并保存正确的 API Key。"
            f" 原始信息: {snippet}"
        )

    # 3) 连接类错误（断网/超时/代理拦截）
    if _is_subclass_of(exc, "APIConnectionError", "APITimeoutError") or "connection" in low or "timeout" in low or "RemoteProtocolError" in low:
        snippet = _snippet(err_text)
        return (
            "无法连接到模型接口（网络/超时/代理），请检查网络连接；"
            "macOS 下若本机代理(Clash 等)异常可尝试关闭或设置 HTTP(S)_PROXY 直连。"
            f" 原始信息: {snippet}"
        )

    # 4) 模型名不存在 / 端点不支持该模型（开放 400/404）
    if "400" in low or "404" in low or "not found" in low:
        hint = _looks_like_model_config(err_text)
        if hint:
            snippet = _snippet(err_text)
            return (
                f"{hint}：请打开「模型设置」，确认所选模型名与接口端点匹配并重新校验；"
                f"若刚升级/换端点，请在设置里删除并重新添加模型。 原始信息: {snippet}"
            )
        # 其他 400/404（可能是图数据问题而非模型）
        snippet = _snippet(err_text)
        return f"建图请求失败（HTTP 400/404）：{snippet}"

    # 5) 通用 OpenAI 错误
    if is_openai_err or isinstance(exc, Exception):
        hint = _looks_like_model_config(err_text)
        snippet = _snippet(err_text)
        if hint:
            return (
                f"{hint}：请打开「模型设置」检查并重新校验模型（API Key/接口/模型名）。"
                f" 原始信息: {snippet}"
            )
        return f"图谱构建/模型调用失败：{snippet}"

    return default if default is not None else _snippet(err_text)
