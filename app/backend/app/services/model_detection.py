"""模型端点规范化、风险校验和智能能力检测。"""

from __future__ import annotations

import ipaddress
import json
import socket
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol
from urllib.parse import urlparse, urlunparse

from ..models.model_config import ConnectionDraft
from .model_providers import ProviderTemplate, match_provider


class UnsafeEndpointError(ValueError):
    pass

class PrivateNetworkRequiredError(UnsafeEndpointError):
    def __init__(self, hostname: str, addresses: list[str]):
        self.hostname = hostname
        self.addresses = list(addresses)
        super().__init__(
            f"接入点 {hostname} 解析到私有/保留地址 {', '.join(addresses)}，请确认是否允许访问"
        )


class DetectionRequestError(RuntimeError):
    pass


@dataclass(frozen=True)
class NormalizedEndpoint:
    provider_id: str
    provider_name: str
    base_url: str
    models_url: str
    chat_url: str
    embedding_url: str
    allow_empty_key: bool


@dataclass(frozen=True)
class HttpResponse:
    status: int
    data: Any
    headers: Dict[str, str] = field(default_factory=dict)


@dataclass
class DetectionResult:
    provider_id: str
    provider_name: str
    normalized_endpoint: str
    capability_urls: Dict[str, str]
    capabilities: Dict[str, Dict[str, Any]]
    models: List[str]
    usable: bool
    manual_model_required: bool
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class HttpTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Dict[str, str],
        json_body: Optional[Dict[str, Any]] = None,
        timeout: float = 10.0,
    ) -> HttpResponse: ...


class UrllibTransport:
    """无自动重定向的轻量 HTTP 传输。"""

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    def __init__(self):
        self._opener = urllib.request.build_opener(self._NoRedirect())

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Dict[str, str],
        json_body: Optional[Dict[str, Any]] = None,
        timeout: float = 10.0,
    ) -> HttpResponse:
        body = None
        request_headers = dict(headers)
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            url=url, data=body, headers=request_headers, method=method.upper()
        )
        try:
            with self._opener.open(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
                try:
                    data = json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    data = {"raw": raw[:1000]}
                return HttpResponse(
                    status=response.status,
                    data=data,
                    headers=dict(response.headers.items()),
                )
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                data = {"raw": raw[:1000]}
            return HttpResponse(exc.code, data, dict(exc.headers.items()))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise DetectionRequestError(str(exc)) from exc


def _join_url(origin: str, prefix: str, endpoint_path: str) -> str:
    combined = "/".join(
        segment.strip("/")
        for segment in (prefix, endpoint_path)
        if segment and segment.strip("/")
    )
    return f"{origin.rstrip('/')}/{combined}"


def normalize_endpoint(value: str) -> NormalizedEndpoint:
    raw = (value or "").strip()
    if not raw:
        raise ValueError("接入点不能为空")
    if "://" not in raw:
        raw = f"http://{raw}"
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("接入点只支持 http 或 https")
    if not parsed.hostname:
        raise ValueError("接入点缺少主机名")
    if parsed.username or parsed.password:
        raise ValueError("请勿在接入点中填写用户名或密码")
    if parsed.query or parsed.fragment:
        raise ValueError("接入点不能包含查询参数或片段")

    host_with_port = parsed.netloc.lower()
    template = match_provider(host_with_port)
    path = parsed.path.rstrip("/")
    known_suffixes = (
        "/chat/completions",
        "/embeddings",
        "/models",
        "/api/tags",
    )
    for suffix in known_suffixes:
        if path.endswith(suffix):
            path = path[: -len(suffix)].rstrip("/")
            break

    if template.provider_id == "ollama":
        # Ollama 的模型发现是原生路径，而 Chat/Embedding 使用兼容的 /v1。
        compatible_prefix = path
        if compatible_prefix.endswith("/v1"):
            compatible_prefix = compatible_prefix[:-3].rstrip("/")
        origin = urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))
        base_url = _join_url(origin, compatible_prefix, "/v1")
        models_url = _join_url(origin, compatible_prefix, template.models_path)
    else:
        if not path:
            path = template.default_base_path
        origin = urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))
        base_url = _join_url(origin, path, "")
        models_url = _join_url(base_url, "", template.models_path)

    return NormalizedEndpoint(
        provider_id=template.provider_id,
        provider_name=template.name,
        base_url=base_url,
        models_url=models_url,
        chat_url=_join_url(base_url, "", template.chat_path),
        embedding_url=_join_url(base_url, "", template.embedding_path),
        allow_empty_key=template.allow_empty_key,
    )


def _default_resolver(hostname: str) -> List[str]:
    records = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    return sorted({record[4][0] for record in records})


def _is_loopback_host(hostname: str) -> bool:
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _is_private_or_reserved(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return not ip.is_global


class ModelConnectionDetector:
    def __init__(
        self,
        *,
        transport: Optional[HttpTransport] = None,
        resolver: Optional[Callable[[str], List[str]]] = None,
    ):
        self.transport = transport or UrllibTransport()
        self.resolver = resolver or _default_resolver

    @staticmethod
    def _headers(draft: ConnectionDraft) -> Dict[str, str]:
        headers = {"Accept": "application/json", **draft.headers}
        if draft.api_key:
            headers["Authorization"] = f"Bearer {draft.api_key}"
        return headers

    def _assert_safe_endpoint(self, endpoint: NormalizedEndpoint, draft: ConnectionDraft) -> None:
        parsed = urlparse(endpoint.base_url)
        if _is_loopback_host(parsed.hostname or ""):
            return
        try:
            addresses = self.resolver(parsed.hostname or "")
        except OSError as exc:
            raise UnsafeEndpointError(f"无法解析接入点主机: {exc}") from exc
        if not addresses:
            raise UnsafeEndpointError("接入点没有可用地址")
        if any(_is_private_or_reserved(address) for address in addresses):
            if not draft.options.get("allow_private_network", False):
                raise PrivateNetworkRequiredError(parsed.hostname or "", addresses)

    @staticmethod
    def _extract_models(provider_id: str, data: Any) -> List[str]:
        if not isinstance(data, dict):
            return []
        if provider_id == "ollama":
            return [
                item.get("name") or item.get("model")
                for item in data.get("models", [])
                if isinstance(item, dict) and (item.get("name") or item.get("model"))
            ]
        return [
            item.get("id")
            for item in data.get("data", [])
            if isinstance(item, dict) and item.get("id")
        ]

    @staticmethod
    def _extract_embedding_dimension(data: Any) -> Optional[int]:
        """从 OpenAI 兼容 /embeddings 响应中提取向量维度；失败返回 None。"""
        if not isinstance(data, dict):
            return None
        items = data.get("data")
        if not isinstance(items, list) or not items:
            return None
        first = items[0]
        if not isinstance(first, dict):
            return None
        emb = first.get("embedding")
        if isinstance(emb, list) and emb:
            try:
                return len(emb)
            except TypeError:
                return None
        return None

    @staticmethod
    def _redact(message: str, secret: Optional[str]) -> str:
        if secret:
            message = message.replace(secret, "[REDACTED]")
        return message[:1000]

    def detect(self, draft: ConnectionDraft) -> DetectionResult:
        endpoint = normalize_endpoint(draft.endpoint)
        self._assert_safe_endpoint(endpoint, draft)
        headers = self._headers(draft)
        capabilities: Dict[str, Dict[str, Any]] = {}
        errors: List[str] = []
        models: List[str] = []

        try:
            response = self.transport.request(
                "GET", endpoint.models_url, headers=headers, timeout=10.0
            )
            models = self._extract_models(endpoint.provider_id, response.data)
            if 200 <= response.status < 300 and models:
                capabilities["models"] = {
                    "status": "available",
                    "url": endpoint.models_url,
                    "count": len(models),
                }
            else:
                capabilities["models"] = {
                    "status": "unavailable",
                    "url": endpoint.models_url,
                    "http_status": response.status,
                }
        except DetectionRequestError as exc:
            capabilities["models"] = {
                "status": "unavailable",
                "url": endpoint.models_url,
            }
            errors.append(self._redact(str(exc), draft.api_key))

        if models:
            body = {
                "model": models[0],
                "messages": [{"role": "user", "content": "Reply with OK."}],
                "max_tokens": 8,
                "temperature": 0,
            }
            try:
                response = self.transport.request(
                    "POST",
                    endpoint.chat_url,
                    headers=headers,
                    json_body=body,
                    timeout=15.0,
                )
                available = 200 <= response.status < 300 and isinstance(response.data, dict) and bool(response.data.get("choices"))
                capabilities["chat"] = {
                    "status": "available" if available else "unavailable",
                    "url": endpoint.chat_url,
                    "http_status": response.status,
                }
            except DetectionRequestError as exc:
                capabilities["chat"] = {"status": "unavailable", "url": endpoint.chat_url}
                errors.append(self._redact(str(exc), draft.api_key))
        else:
            capabilities["chat"] = {
                "status": "not_tested",
                "url": endpoint.chat_url,
                "reason": "需要手动填写模型 ID",
            }

        if models:
            emb_body = {"model": models[0], "input": ["mirofish embedding probe"]}
            try:
                response = self.transport.request(
                    "POST",
                    endpoint.embedding_url,
                    headers=headers,
                    json_body=emb_body,
                    timeout=15.0,
                )
                dimension = self._extract_embedding_dimension(response.data)
                capabilities["embedding"] = {
                    "status": "available" if dimension is not None else "unavailable",
                    "url": endpoint.embedding_url,
                    "http_status": response.status,
                    "dimension": dimension,
                }
            except DetectionRequestError as exc:
                capabilities["embedding"] = {
                    "status": "unavailable",
                    "url": endpoint.embedding_url,
                }
                errors.append(self._redact(str(exc), draft.api_key))
        else:
            capabilities["embedding"] = {
                "status": "not_tested",
                "url": endpoint.embedding_url,
                "reason": "需要手动填写模型 ID",
            }

        usable = capabilities.get("chat", {}).get("status") == "available"
        return DetectionResult(
            provider_id=endpoint.provider_id,
            provider_name=endpoint.provider_name,
            normalized_endpoint=endpoint.base_url,
            capability_urls={
                "models": endpoint.models_url,
                "chat": endpoint.chat_url,
                "embedding": endpoint.embedding_url,
            },
            capabilities=capabilities,
            models=models,
            usable=usable,
            manual_model_required=not models,
            errors=errors,
        )
