"""HybridRAG rag.config のテスト。"""

import json
import logging

import pytest
from rag.config import JsonFormatter, configure_logging, env_flag, require_openai_api_key


def test_require_openai_api_key_returns_str():
    k = require_openai_api_key()
    assert isinstance(k, str)
    assert len(k) > 0


def test_json_formatter_basic():
    fmt = JsonFormatter()
    r = logging.LogRecord("n", logging.INFO, __file__, 1, "hello", (), None)
    s = fmt.format(r)
    d = json.loads(s)
    assert d["message"] == "hello"
    assert d["level"] == "INFO"


def test_configure_logging_idempotent():
    configure_logging()
    n = len(logging.getLogger().handlers)
    configure_logging()
    assert len(logging.getLogger().handlers) == n


@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "Yes"])
def test_env_flag_truthy_values(monkeypatch, value):
    monkeypatch.setenv("TEST_ENV_FLAG", value)
    assert env_flag("TEST_ENV_FLAG") is True


@pytest.mark.parametrize("value", ["false", "0", "no", "", "banana"])
def test_env_flag_falsy_values(monkeypatch, value):
    monkeypatch.setenv("TEST_ENV_FLAG", value)
    assert env_flag("TEST_ENV_FLAG") is False


def test_env_flag_uses_default_when_unset(monkeypatch):
    monkeypatch.delenv("TEST_ENV_FLAG_UNSET", raising=False)
    assert env_flag("TEST_ENV_FLAG_UNSET") is True
    assert env_flag("TEST_ENV_FLAG_UNSET", default="false") is False
