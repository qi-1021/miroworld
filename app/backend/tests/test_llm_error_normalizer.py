"""llm_error_normalizer 单元测试。"""

from app.services.llm_error_normalizer import normalize_llm_error


def test_none_returns_default():
    assert normalize_llm_error(None, default="X") == "X"
    assert normalize_llm_error(None) == "未知错误"


def test_missing_config_value_error():
    exc = ValueError("LLM_API_KEY 未配置")
    out = normalize_llm_error(exc)
    assert "模型配置缺失" in out
    assert "模型设置" in out


def test_authentication_error():
    # 用同名异常类型触发鉴权分支（_is_subclass_of 按类名匹配）
    class AuthenticationError(Exception):
        pass
    out = normalize_llm_error(AuthenticationError("Incorrect API key provided"))
    assert "鉴权" in out or "API Key" in out
    assert "原始信息" in out


def test_bad_request_unknown_model():
    class BadRequestError(Exception):
        pass
    out = normalize_llm_error(
        BadRequestError("Request failed with status code 400: model does not exist")
    )
    assert "模型" in out
    assert "模型设置" in out


def test_connection_error():
    class APIConnectionError(Exception):
        pass
    out = normalize_llm_error(APIConnectionError("connection refused"))
    assert "无法连接到模型接口" in out


def test_generic_error_preserves_message():
    out = normalize_llm_error(RuntimeError("其它问题"))
    assert "其它问题" in out


def test_raw_400_string_gets_guidance():
    # 常见：provider 返回带 400 与"model not found"的文本
    class FakeExc(Exception):
        pass
    out = normalize_llm_error(FakeExc("Request failed with status code 400: model does not exist"))
    assert "模型" in out
    assert "原始信息" in out
