"""图谱 API 中 LLM 错误信息的可读化测试。"""
from app.api.graph import _llm_error_message


class FakeResponse:
    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


class FakeAPIError(Exception):
    def __init__(self, message, response=None):
        super().__init__(message)
        self.message = message
        self.response = response


def test_llm_error_message_extracts_provider_message():
    error = FakeAPIError(
        "Error code: 402",
        response=FakeResponse(
            {"error": {"message": "Insufficient Balance", "type": "unknown_error"}}
        ),
    )

    assert _llm_error_message(error) == "Insufficient Balance"


def test_llm_error_message_falls_back_to_exception_text():
    error = FakeAPIError("connection refused")

    assert _llm_error_message(error) == "connection refused"
