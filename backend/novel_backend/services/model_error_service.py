from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(slots=True)
class ModelErrorClassification:
  kind: str
  title: str
  user_action: str
  retryable: bool = False


_RATE_LIMIT_PATTERNS = (
  "rate limit",
  "rate_limit",
  "too many requests",
  "throttled",
  "限流",
  "请求过多",
)
_BILLING_PATTERNS = (
  "insufficient credits",
  "insufficient_quota",
  "quota",
  "余额",
  "额度",
  "欠费",
  "payment required",
)
_AUTH_PATTERNS = (
  "invalid api key",
  "invalid_api_key",
  "unauthorized",
  "authentication",
  "forbidden",
  "api key",
  "鉴权",
  "认证",
  "无权限",
)
_CONTEXT_PATTERNS = (
  "context length",
  "context_length",
  "maximum context",
  "prompt is too long",
  "too many tokens",
  "token limit",
  "上下文",
  "输入过长",
)
_MODEL_NOT_FOUND_PATTERNS = (
  "model not found",
  "model_not_found",
  "invalid model",
  "does not exist",
  "unknown model",
  "模型不存在",
  "模型名",
)
_TIMEOUT_PATTERNS = (
  "timed out",
  "timeout",
  "read timed out",
  "超时",
)
_NETWORK_PATTERNS = (
  "unexpected_eof",
  "unexpected eof",
  "eof occurred",
  "remote end closed",
  "connection closed",
  "connection reset",
  "connection aborted",
  "network",
  "ssl",
  "tls",
  "_ssl.c",
  "连接",
)
_FORMAT_PATTERNS = (
  "invalid request",
  "bad request",
  "json",
  "schema",
  "format",
  "参数",
  "格式",
)


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
  return any(pattern in text for pattern in patterns)


def _http_status(text: str) -> int | None:
  matched = re.search(r"\b(4\d\d|5\d\d)\b", text)
  if not matched:
    return None
  try:
    return int(matched.group(1))
  except ValueError:
    return None


def classify_model_error(error: object) -> ModelErrorClassification:
  text = str(error or "").strip()
  lowered = text.lower()
  status = _http_status(lowered)

  if status in {401, 403} or _contains_any(lowered, _AUTH_PATTERNS):
    return ModelErrorClassification(
      kind="auth",
      title="模型认证失败",
      user_action="检查 API Key、Base URL 和当前模型供应商权限。",
      retryable=False,
    )

  if status == 402 or _contains_any(lowered, _BILLING_PATTERNS):
    return ModelErrorClassification(
      kind="billing",
      title="模型额度不可用",
      user_action="检查账户余额、额度上限或供应商套餐状态。",
      retryable=False,
    )

  if status == 429 or _contains_any(lowered, _RATE_LIMIT_PATTERNS):
    return ModelErrorClassification(
      kind="rate_limit",
      title="模型请求被限流",
      user_action="稍后重试，或切换到可用额度更高的模型配置。",
      retryable=True,
    )

  if status == 413 or _contains_any(lowered, _CONTEXT_PATTERNS):
    return ModelErrorClassification(
      kind="context_overflow",
      title="模型上下文过长",
      user_action="减少输入资料、缩短章节正文，或改用更长上下文的模型。",
      retryable=True,
    )

  if _contains_any(lowered, _MODEL_NOT_FOUND_PATTERNS):
    return ModelErrorClassification(
      kind="model_not_found",
      title="模型不可用",
      user_action="检查模型名是否仍可用，或在设置里换成当前供应商支持的模型。",
      retryable=False,
    )

  if status in {500, 502, 503, 504}:
    return ModelErrorClassification(
      kind="server_error",
      title="模型服务暂时异常",
      user_action="稍后重试；如果持续出现，换一个供应商或模型。",
      retryable=True,
    )

  if _contains_any(lowered, _NETWORK_PATTERNS):
    return ModelErrorClassification(
      kind="network",
      title="模型网络连接中断",
      user_action="模型供应商或当前网络在连接过程中断开。请直接重试；如果连续出现，再检查代理或切换供应商。",
      retryable=True,
    )

  if _contains_any(lowered, _TIMEOUT_PATTERNS):
    return ModelErrorClassification(
      kind="timeout",
      title="模型请求超时",
      user_action="检查网络状态，或降低输入长度后重试。",
      retryable=True,
    )

  if (status is not None and 400 <= status < 500) or _contains_any(lowered, _FORMAT_PATTERNS):
    return ModelErrorClassification(
      kind="format_error",
      title="模型请求格式不被接受",
      user_action="检查当前模型是否兼容 OpenAI Chat Completions 参数。",
      retryable=False,
    )

  return ModelErrorClassification(
    kind="unknown",
    title="模型请求失败",
    user_action="查看运行日志里的完整错误，再决定是否换模型或调整输入。",
    retryable=True,
  )
