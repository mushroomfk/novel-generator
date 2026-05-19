from __future__ import annotations

import http.client
import json
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
  "temporarily unavailable",
  "timed out",
  "timeout",
  "ssl",
  "tls",
  "_ssl.c",
)


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
  api_key: str,
  payload: dict[str, object],
  *,
  failure_label: str,
  invalid_json_message: str,
  invalid_format_message: str,
  timeout: int = 120,
) -> dict[str, object]:
  body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
  request = urllib_request.Request(endpoint, data=body, method="POST")
  request.add_header("Content-Type", "application/json")
  request.add_header("Authorization", f"Bearer {api_key}")

  raw_text = ""
  for attempt in range(len(_RETRY_DELAYS) + 1):
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
      http.client.RemoteDisconnected,
      ssl.SSLError,
    ) as error:
      reason = _transport_error_reason(error)
      if is_retryable_transport_error(reason) and _should_retry(attempt):
        _wait_before_retry(attempt)
        continue
      raise RuntimeError(f"{failure_label}: {reason}") from error

  try:
    parsed = json.loads(raw_text)
  except json.JSONDecodeError as error:
    raise RuntimeError(invalid_json_message) from error

  if not isinstance(parsed, dict):
    raise RuntimeError(invalid_format_message)
  return parsed
