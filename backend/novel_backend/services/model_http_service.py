from __future__ import annotations

import json
import time
from urllib import error as urllib_error
from urllib import request as urllib_request

from novel_backend.services.model_error_service import is_transient_model_network_error

DEFAULT_MODEL_REQUEST_TIMEOUT_SECONDS = 120
DEFAULT_MODEL_REQUEST_RETRY_DELAYS = (0.8, 1.6)


def request_json_with_retries(
  endpoint: str,
  *,
  headers: dict[str, str],
  payload: dict[str, object],
  error_prefix: str,
  invalid_json_message: str,
  invalid_payload_message: str,
  timeout: int = DEFAULT_MODEL_REQUEST_TIMEOUT_SECONDS,
  retry_delays: tuple[float, ...] = DEFAULT_MODEL_REQUEST_RETRY_DELAYS,
) -> dict[str, object]:
  body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
  last_error: BaseException | None = None

  for attempt_index in range(len(retry_delays) + 1):
    request = urllib_request.Request(endpoint, data=body, method="POST")
    for key, value in headers.items():
      request.add_header(key, value)

    try:
      with urllib_request.urlopen(request, timeout=timeout) as response:
        raw_text = response.read().decode("utf-8")
      break
    except urllib_error.HTTPError as error:
      error_text = error.read().decode("utf-8", errors="ignore")
      message = error_text or str(error)
      raise RuntimeError(f"{error_prefix}: {error.code} {message}") from error
    except urllib_error.URLError as error:
      last_error = error
      reason = error.reason
      if attempt_index < len(retry_delays) and is_transient_model_network_error(reason):
        time.sleep(retry_delays[attempt_index])
        continue
      raise RuntimeError(f"{error_prefix}: {reason}") from error
    except (TimeoutError, ConnectionError, OSError) as error:
      last_error = error
      if attempt_index < len(retry_delays) and is_transient_model_network_error(error):
        time.sleep(retry_delays[attempt_index])
        continue
      raise RuntimeError(f"{error_prefix}: {error}") from error
  else:
    raise RuntimeError(f"{error_prefix}: {last_error}")

  try:
    parsed = json.loads(raw_text)
  except json.JSONDecodeError as error:
    raise RuntimeError(invalid_json_message) from error

  if not isinstance(parsed, dict):
    raise RuntimeError(invalid_payload_message)

  return parsed
