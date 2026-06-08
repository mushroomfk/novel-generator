from __future__ import annotations

import http.client
import json
import socket
import ssl
import time
from urllib import error as urllib_error
from urllib import request as urllib_request

_RETRY_DELAYS = (0.8, 2.0)
_RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}
_RETRYABLE_TRANSPORT_PATTERNS = (
  "unexpected_eof",
  "unexpected eof",
  "eof occurred",
  "remote end closed",
  "connection closed",
  "connection reset",
  "connection aborted",
  "broken pipe",
  "temporarily unavailable",
  "temporary failure",
  "timed out",
  "timeout",
  "ssl",
  "tls",
  "_ssl.c",
)
_CHAT_COMPLETIONS_SUFFIX = "/chat/completions"
_OPTIONAL_SAMPLING_KEYS = ("temperature", "top_p")


def _is_chat_completion_request(endpoint: str, payload: dict[str, object] | None) -> bool:
  if payload is None:
    return False
  normalized_endpoint = endpoint.strip().lower().rstrip("/")
  return normalized_endpoint.endswith(_CHAT_COMPLETIONS_SUFFIX) and "messages" in payload


def prepare_model_request_payload(endpoint: str, payload: dict[str, object] | None) -> dict[str, object] | None:
  if not _is_chat_completion_request(endpoint, payload):
    return payload

  sanitized = dict(payload)
  for key in _OPTIONAL_SAMPLING_KEYS:
    sanitized.pop(key, None)
  return sanitized


def _build_request(
  endpoint: str,
  *,
  method: str,
  body: bytes | None,
  api_key: str | None,
  headers: dict[str, str] | None,
  content_type: str | None,
) -> urllib_request.Request:
  request = urllib_request.Request(endpoint, data=body, method=method)
  if api_key:
    request.add_header("Authorization", f"Bearer {api_key}")
  if body is not None and content_type:
    request.add_header("Content-Type", content_type)
  for key, value in (headers or {}).items():
    request.add_header(key, value)
  return request


def is_retryable_transport_error(error: object) -> bool:
  text = str(error or "").strip().lower()
  if not text:
    return False
  return any(pattern in text for pattern in _RETRYABLE_TRANSPORT_PATTERNS)


def _transport_error_reason(error: object) -> object:
  if isinstance(error, urllib_error.URLError):
    return getattr(error, "reason", error)
  return error


def _should_retry(attempt: int) -> bool:
  return attempt < len(_RETRY_DELAYS)


def _wait_before_retry(attempt: int) -> None:
  time.sleep(_RETRY_DELAYS[attempt])


def request_json(
  endpoint: str,
  api_key: str | None = None,
  payload: dict[str, object] | None = None,
  *,
  method: str = "POST",
  body: bytes | None = None,
  headers: dict[str, str] | None = None,
  content_type: str | None = "application/json",
  failure_label: str,
  invalid_json_message: str,
  invalid_format_message: str,
  allow_empty_response: bool = False,
  timeout: int = 120,
) -> dict[str, object]:
  if payload is not None and body is not None:
    raise RuntimeError("请求参数冲突")
  safe_payload = prepare_model_request_payload(endpoint, payload)
  request_body = body if body is not None else (
    json.dumps(safe_payload, ensure_ascii=False).encode("utf-8")
    if safe_payload is not None else None
  )

  raw_text = ""
  for attempt in range(len(_RETRY_DELAYS) + 1):
    request = _build_request(
      endpoint,
      method=method,
      body=request_body,
      api_key=api_key,
      headers=headers,
      content_type=content_type,
    )
    try:
      with urllib_request.urlopen(request, timeout=timeout) as response:
        raw_text = response.read().decode("utf-8")
      break
    except urllib_error.HTTPError as error:
      error_text = error.read().decode("utf-8", errors="ignore")
      message = error_text or str(error)
      if error.code in _RETRYABLE_HTTP_STATUS and _should_retry(attempt):
        _wait_before_retry(attempt)
        continue
      raise RuntimeError(f"{failure_label}: {error.code} {message}") from error
    except (
      urllib_error.URLError,
      TimeoutError,
      ConnectionError,
      socket.timeout,
      http.client.IncompleteRead,
      http.client.HTTPException,
      http.client.RemoteDisconnected,
      ssl.SSLError,
    ) as error:
      reason = _transport_error_reason(error)
      if is_retryable_transport_error(reason) and _should_retry(attempt):
        _wait_before_retry(attempt)
        continue
      raise RuntimeError(f"{failure_label}: {reason}") from error

  if not raw_text.strip():
    if allow_empty_response:
      return {}
    raise RuntimeError(invalid_json_message)

  try:
    parsed = json.loads(raw_text)
  except json.JSONDecodeError as error:
    raise RuntimeError(invalid_json_message) from error

  if not isinstance(parsed, dict):
    raise RuntimeError(invalid_format_message)
  return parsed
