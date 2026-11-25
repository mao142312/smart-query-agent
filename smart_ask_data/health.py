from __future__ import annotations

from typing import Any

SUPPORTED_QUERY_BACKENDS = {"sqlite", "trino"}


def safe_query_backend(value: Any) -> str:
    normalized = str(value).strip().lower()
    return normalized if normalized in SUPPORTED_QUERY_BACKENDS else "unknown"


def safe_runtime_label(value: Any, allowed: set[str]) -> str:
    normalized = str(value).strip().lower()
    return normalized if normalized in allowed else "unknown"


def classify_data_source_error(error: Exception) -> dict[str, str]:
    """Return a stable, user-safe error without exposing connection details."""
    message = str(error).lower()
    if any(term in message for term in ("auth", "password", "credential", "unauthorized", "forbidden")):
        code, safe_message = "DATA_SOURCE_AUTHENTICATION_FAILED", "数据源认证失败"
    elif isinstance(error, TimeoutError) or any(term in message for term in ("timeout", "timed out", "deadline")):
        code, safe_message = "DATA_SOURCE_TIMEOUT", "数据源连接超时"
    elif isinstance(error, (ConnectionError, OSError)) or any(
        term in message for term in ("connect", "connection", "refused", "network", "host", "socket", "dns")
    ):
        code, safe_message = "DATA_SOURCE_CONNECTION_FAILED", "无法连接数据源"
    elif isinstance(error, (KeyError, TypeError, ValueError)):
        code, safe_message = "DATA_SOURCE_CONFIGURATION_INVALID", "数据源配置无效"
    else:
        code, safe_message = "DATA_SOURCE_CHECK_FAILED", "数据源检查失败"
    return {"code": code, "message": safe_message}


def unavailable_data_source(
    backend: str,
    read_only: bool,
    read_only_basis: str,
    error: Exception,
) -> dict[str, Any]:
    return {
        "status": "error",
        "backend": safe_query_backend(backend),
        "read_only": read_only,
        "read_only_basis": read_only_basis,
        "error": classify_data_source_error(error),
    }


def invalid_data_source_configuration() -> dict[str, Any]:
    return {
        "status": "error",
        "backend": "unknown",
        "read_only": False,
        "read_only_basis": "configuration_not_loaded",
        "error": {
            "code": "DATA_SOURCE_CONFIGURATION_INVALID",
            "message": "数据源配置无效",
        },
    }
