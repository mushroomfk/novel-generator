from __future__ import annotations

import os
import re
from urllib import parse as urllib_parse

from novel_backend.config import Settings
from novel_backend.models import HistoricalResearchResult, HistoricalResearchSource, KnowledgeSearchResult, ModelConfig
from novel_backend.services.config_service import load_config
from novel_backend.services.generation_service import _invoke_model
from novel_backend.services.log_service import append_app_log
from novel_backend.services.model_transport_service import request_json
from novel_backend.services.project_service import search_project_knowledge


class WebResearchProviderError(RuntimeError):
  pass


class WebResearchProviderUnavailable(WebResearchProviderError):
  pass


_BOCHA_SEARCH_ENDPOINT = "https://api.bochaai.com/v1/web-search"
_ALIYUN_RESPONSES_ENDPOINT = "https://dashscope.aliyuncs.com/compatible-mode/v1/responses"


def _compact_text(text: str, limit: int = 600) -> str:
  normalized = re.sub(r"\s+", " ", (text or "").strip())
  if len(normalized) <= limit:
    return normalized
  return normalized[:limit].rstrip() + "..."


def _site_from_url(url: str) -> str:
  try:
    return urllib_parse.urlparse(url).netloc.lower().removeprefix("www.")
  except Exception:
    return ""


def _request_json(
  endpoint: str,
  *,
  headers: dict[str, str],
  payload: dict[str, object],
  timeout: int = 45,
) -> dict[str, object]:
  try:
    return request_json(
      endpoint,
      payload=payload,
      headers=headers,
      failure_label="搜索服务请求失败",
      invalid_json_message="搜索服务返回的不是合法 JSON",
      invalid_format_message="搜索服务返回格式不正确",
      timeout=timeout,
    )
  except RuntimeError as error:
    raise WebResearchProviderError(str(error)) from error


def _model_is_aliyun(config: ModelConfig) -> bool:
  base_url = config.base_url.strip().lower()
  model_name = config.model_name.strip().lower()
  return "dashscope.aliyuncs.com" in base_url or model_name.startswith("qwen")


def _resolve_aliyun_api_key(config: ModelConfig) -> str:
  candidates: list[str] = []
  if _model_is_aliyun(config):
    candidates.extend([config.api_key, os.getenv("NOVEL_MODEL_API_KEY", "")])
  candidates.append(os.getenv("DASHSCOPE_API_KEY", ""))
  for item in candidates:
    value = item.strip()
    if value:
      return value
  raise WebResearchProviderUnavailable("未配置阿里百炼 API Key")


def _resolve_bocha_api_key() -> str:
  value = os.getenv("BOCHA_API_KEY", "").strip()
  if not value:
    raise WebResearchProviderUnavailable("未配置 BOCHA_API_KEY")
  return value


def _chat_completions_endpoint(base_url: str) -> str:
  normalized = base_url.strip().rstrip("/")
  if not normalized:
    return "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
  if normalized.endswith("/chat/completions"):
    return normalized
  if normalized.endswith("/responses"):
    return f"{normalized.removesuffix('/responses')}/chat/completions"
  return f"{normalized}/chat/completions"


def _responses_endpoint(base_url: str) -> str:
  normalized = base_url.strip().rstrip("/")
  if not normalized:
    return _ALIYUN_RESPONSES_ENDPOINT
  if normalized.endswith("/responses"):
    return normalized
  if normalized.endswith("/chat/completions"):
    return f"{normalized.removesuffix('/chat/completions')}/responses"
  return f"{normalized}/responses"


def _provider_search_query(query: str) -> str:
  normalized = query.strip()
  if any(keyword in normalized for keyword in ("典故", "出处", "历史", "史实", "年代")):
    return normalized
  return f"{normalized} 历史典故 出处 背景 用法"


def _research_prompt(query: str, local_hits: list[KnowledgeSearchResult]) -> str:
  local_text = "\n".join(f"- {item.section}：{item.preview}" for item in local_hits[:4]) or "无"
  return f"""
请联网考据这个小说创作问题：{query}

本项目已有资料命中：
{local_text}

请只依据联网搜索结果和本地资料输出中文研究简报，必须包含：
### 可用素材
### 考据要点
### 误用风险
### 写作借鉴
### 联网来源

要求：
- 给出典故或史实出处，资料不足就明确写资料不足。
- 联网来源必须列出资料标题和可打开 URL。
- 不要编造来源。
- 重点服务小说创作，不要写成百科词条。
""".strip()


def _extract_chat_answer(payload: dict[str, object]) -> str:
  output = payload.get("output")
  if isinstance(output, dict):
    choices = output.get("choices")
  else:
    choices = payload.get("choices")
  if not isinstance(choices, list) or not choices:
    return ""
  first = choices[0]
  if not isinstance(first, dict):
    return ""
  message = first.get("message")
  if not isinstance(message, dict):
    return ""
  content = message.get("content")
  if isinstance(content, str):
    return content.strip()
  if isinstance(content, list):
    parts = [
      str(item.get("text") or "").strip()
      for item in content
      if isinstance(item, dict) and str(item.get("text") or "").strip()
    ]
    return "\n".join(parts).strip()
  return ""


def _extract_chat_search_sources(payload: dict[str, object], provider: str) -> list[HistoricalResearchSource]:
  output = payload.get("output")
  search_info = output.get("search_info") if isinstance(output, dict) else payload.get("search_info")
  if not isinstance(search_info, dict):
    return []
  raw_results = search_info.get("search_results")
  if not isinstance(raw_results, list):
    return []
  return _sources_from_search_results(raw_results, provider)


def _extract_responses_answer(payload: dict[str, object]) -> str:
  output_text = payload.get("output_text")
  if isinstance(output_text, str) and output_text.strip():
    return output_text.strip()

  parts: list[str] = []

  def visit(value: object) -> None:
    if isinstance(value, dict):
      value_type = str(value.get("type") or "")
      text = value.get("text")
      if value_type in {"output_text", "text"} and isinstance(text, str) and text.strip():
        parts.append(text.strip())
      content = value.get("content")
      if isinstance(content, str) and value_type == "message" and content.strip():
        parts.append(content.strip())
      for child in value.values():
        visit(child)
    elif isinstance(value, list):
      for child in value:
        visit(child)

  visit(payload.get("output"))
  return "\n\n".join(parts).strip()


def _extract_responses_sources(payload: dict[str, object], provider: str) -> list[HistoricalResearchSource]:
  sources: list[HistoricalResearchSource] = []
  seen: set[str] = set()

  def add_source(title: str, url: str, site: str = "") -> None:
    clean_url = url.strip()
    if not clean_url or clean_url in seen:
      return
    seen.add(clean_url)
    sources.append(
      HistoricalResearchSource(
        title=title.strip() or _site_from_url(clean_url) or "联网来源",
        url=clean_url,
        site=site.strip() or _site_from_url(clean_url),
        provider=provider,
      )
    )

  def visit(value: object) -> None:
    if isinstance(value, dict):
      url = value.get("url")
      if isinstance(url, str):
        add_source(str(value.get("title") or value.get("name") or ""), url, str(value.get("site_name") or ""))
      urls = value.get("urls")
      if isinstance(urls, list):
        for item in urls:
          if isinstance(item, str):
            add_source("", item)
      for child in value.values():
        visit(child)
    elif isinstance(value, list):
      for child in value:
        visit(child)

  visit(payload.get("output"))
  return sources


def _sources_from_search_results(raw_results: list[object], provider: str) -> list[HistoricalResearchSource]:
  sources: list[HistoricalResearchSource] = []
  for item in raw_results:
    if not isinstance(item, dict):
      continue
    url = str(item.get("url") or "").strip()
    title = str(item.get("title") or item.get("name") or "").strip()
    site_name = str(item.get("site_name") or item.get("siteName") or "").strip()
    sources.append(
      HistoricalResearchSource(
        title=title or _site_from_url(url) or "搜索结果",
        url=url,
        snippet=_compact_text(str(item.get("snippet") or item.get("summary") or ""), 500),
        summary=_compact_text(str(item.get("summary") or ""), 600),
        site=site_name or _site_from_url(url),
        published_at=str(item.get("dateLastCrawled") or item.get("datePublished") or ""),
        provider=provider,
      )
    )
  return [item for item in sources if item.url or item.title]


def _sources_from_answer_links(answer: str, provider: str) -> list[HistoricalResearchSource]:
  sources: list[HistoricalResearchSource] = []
  seen: set[str] = set()

  def add(title: str, url: str) -> None:
    clean_url = url.strip().rstrip("，。；;、)")
    if not clean_url or clean_url in seen:
      return
    seen.add(clean_url)
    sources.append(
      HistoricalResearchSource(
        title=title.strip() or _site_from_url(clean_url) or "联网来源",
        url=clean_url,
        site=_site_from_url(clean_url),
        provider=provider,
      )
    )

  for match in re.finditer(r"\[([^\]\n]{1,120})\]\((https?://[^)\s]+)\)", answer):
    add(match.group(1), match.group(2))

  for match in re.finditer(r"https?://[^\s)）\]，。；;、]+", answer):
    add("", match.group(0))

  return sources


def _merge_sources(
  primary: list[HistoricalResearchSource],
  secondary: list[HistoricalResearchSource],
) -> list[HistoricalResearchSource]:
  merged: list[HistoricalResearchSource] = []
  seen: set[str] = set()
  for item in primary + secondary:
    key = item.url or f"{item.provider}:{item.title}"
    if key in seen:
      continue
    seen.add(key)
    merged.append(item)
  return merged


def _model_uses_responses_search(model_name: str) -> bool:
  normalized = model_name.strip().lower()
  return normalized.startswith(("qwen3.6-", "qwen3.5-"))


def _aliyun_chat_research(
  settings: Settings,
  query: str,
  local_hits: list[KnowledgeSearchResult],
) -> tuple[str, list[HistoricalResearchSource]]:
  config = load_config(settings).model
  if not _model_is_aliyun(config):
    raise WebResearchProviderUnavailable("当前写作模型不是阿里百炼")
  api_key = _resolve_aliyun_api_key(config)
  payload: dict[str, object] = {
    "model": config.model_name,
    "messages": [
      {"role": "system", "content": "你是中文小说考据编辑。"},
      {"role": "user", "content": _research_prompt(query, local_hits)},
    ],
    "temperature": 0.2,
    "max_tokens": min(config.max_tokens, 1800),
    "enable_search": True,
    "search_options": {
      "search_strategy": "max",
      "enable_source": True,
      "enable_citation": True,
    },
  }
  response_payload = _request_json(
    _chat_completions_endpoint(config.base_url),
    headers={"Authorization": f"Bearer {api_key}"},
    payload=payload,
    timeout=90,
  )
  answer = _extract_chat_answer(response_payload)
  if not answer:
    raise WebResearchProviderError("阿里百炼联网搜索没有返回可读正文")
  sources = _merge_sources(
    _extract_chat_search_sources(response_payload, "aliyun-bailian"),
    _sources_from_answer_links(answer, "aliyun-bailian"),
  )
  return answer, sources


def _aliyun_responses_research(
  settings: Settings,
  query: str,
  local_hits: list[KnowledgeSearchResult],
) -> tuple[str, list[HistoricalResearchSource]]:
  config = load_config(settings).model
  if not _model_is_aliyun(config):
    raise WebResearchProviderUnavailable("当前写作模型不是阿里百炼")
  api_key = _resolve_aliyun_api_key(config)
  payload: dict[str, object] = {
    "model": config.model_name,
    "input": _research_prompt(query, local_hits),
    "tools": [
      {"type": "web_search"},
      {"type": "web_extractor"},
    ],
    "max_output_tokens": min(config.max_tokens, 1800),
  }
  response_payload = _request_json(
    _responses_endpoint(config.base_url),
    headers={"Authorization": f"Bearer {api_key}"},
    payload=payload,
    timeout=120,
  )
  answer = _extract_responses_answer(response_payload)
  if not answer:
    raise WebResearchProviderError("阿里百炼 Responses 联网搜索没有返回可读正文")
  sources = _merge_sources(
    _extract_responses_sources(response_payload, "aliyun-bailian"),
    _sources_from_answer_links(answer, "aliyun-bailian"),
  )
  return answer, sources


def _aliyun_research(
  settings: Settings,
  query: str,
  local_hits: list[KnowledgeSearchResult],
) -> tuple[str, list[HistoricalResearchSource]]:
  config = load_config(settings).model
  if _model_uses_responses_search(config.model_name):
    return _aliyun_responses_research(settings, query, local_hits)
  return _aliyun_chat_research(settings, query, local_hits)


def _bocha_research(query: str, limit: int) -> tuple[str, list[HistoricalResearchSource]]:
  api_key = _resolve_bocha_api_key()
  endpoint = os.getenv("BOCHA_SEARCH_ENDPOINT", _BOCHA_SEARCH_ENDPOINT).strip() or _BOCHA_SEARCH_ENDPOINT
  payload: dict[str, object] = {
    "query": query,
    "count": max(1, min(limit, 20)),
    "freshness": "noLimit",
    "summary": True,
  }
  response_payload = _request_json(
    endpoint,
    headers={"Authorization": f"Bearer {api_key}"},
    payload=payload,
    timeout=45,
  )
  response_data = response_payload.get("data")
  web_pages = response_payload.get("webPages")
  if isinstance(response_data, dict) and not isinstance(web_pages, dict):
    web_pages = response_data.get("webPages")
  if isinstance(web_pages, dict):
    web_pages = web_pages.get("value", [])
  if not isinstance(web_pages, list) or not web_pages:
    raise WebResearchProviderError("博查没有返回搜索结果")

  sources = _sources_from_search_results(web_pages[:limit], "bocha")
  if not sources:
    raise WebResearchProviderError("博查结果格式不完整")
  return "", sources


def _format_sources_for_prompt(sources: list[HistoricalResearchSource]) -> str:
  lines: list[str] = []
  for index, item in enumerate(sources, 1):
    parts = [
      f"{index}. {item.title}",
      f"URL: {item.url}" if item.url else "",
      f"摘要: {item.snippet or item.summary}" if (item.snippet or item.summary) else "",
    ]
    lines.append("\n".join(part for part in parts if part))
  return "\n\n".join(lines)


def _synthesize_answer(
  settings: Settings,
  query: str,
  local_hits: list[KnowledgeSearchResult],
  provider_answer: str,
  sources: list[HistoricalResearchSource],
) -> str:
  source_text = _format_sources_for_prompt(sources)
  local_text = "\n".join(f"- {item.section}：{item.preview}" for item in local_hits[:4]) or "无"
  messages = [
    {
      "role": "system",
      "content": (
        "你是中文小说考据编辑。只依据输入里的国内搜索结果和本地资料写研究简报；"
        "资料不足就写资料不足，不要编造出处。输出要适合作者写小说借鉴。"
      ),
    },
    {
      "role": "user",
      "content": f"""
考据问题：{query}

搜索服务摘要：
{provider_answer or "无"}

搜索来源：
{source_text or "无"}

本项目资料命中：
{local_text}

请按以下结构输出：
### 可用素材
### 考据要点
### 误用风险
### 写作借鉴
""".strip(),
    },
  ]
  return _invoke_model(
    settings,
    messages,
    task_name="historical_web_research",
    temperature=0.2,
    max_tokens=1800,
    enable_thinking=False,
  )


def _fallback_answer(query: str, provider_answer: str, sources: list[HistoricalResearchSource]) -> str:
  if provider_answer:
    return provider_answer
  if not sources:
    return ""
  lines = [f"已找到 {len(sources)} 条国内联网来源，可继续打开原文核对。"]
  for item in sources[:5]:
    detail = item.snippet or item.summary
    if detail:
      lines.append(f"- {item.title}：{detail}")
    else:
      lines.append(f"- {item.title}")
  lines.append(f"检索主题：{query}")
  return "\n".join(lines)


def _suggestions(query: str) -> list[str]:
  trimmed = query.strip()
  return [
    f"{trimmed} 的原始出处和最早文本",
    f"{trimmed} 在同类历史事件中的相似案例",
    f"{trimmed} 可改写成小说冲突的场景线索",
  ]


def research_historical_reference(
  settings: Settings,
  project_id: str,
  query: str,
  limit: int = 8,
) -> HistoricalResearchResult:
  normalized = query.strip()
  if not normalized:
    raise ValueError("检索问题不能为空")

  search_limit = max(1, min(limit, 12))
  warnings: list[str] = []
  try:
    local_hits = search_project_knowledge(settings, project_id, normalized, limit=4)
  except Exception as error:
    local_hits = []
    warnings.append(f"本地资料检索未完成：{error}")

  provider_errors: list[str] = []
  try:
    answer, sources = _aliyun_research(settings, normalized, local_hits)
    return HistoricalResearchResult(
      query=normalized,
      provider="aliyun-bailian",
      answer=answer,
      sources=sources[:search_limit],
      local_hits=local_hits,
      suggestions=_suggestions(normalized),
      warning="；".join(warnings),
    )
  except WebResearchProviderUnavailable as error:
    provider_errors.append(f"aliyun-bailian: {error}")
  except WebResearchProviderError as error:
    append_app_log(settings, f"historical_web_research provider aliyun-bailian failed: {error}", level="WARNING")
    provider_errors.append(f"aliyun-bailian: {error}")

  try:
    provider_answer, sources = _bocha_research(_provider_search_query(normalized), search_limit)
  except WebResearchProviderUnavailable as error:
    warning = "；".join(warnings + provider_errors + [f"bocha: {error}"])
    return HistoricalResearchResult(
      query=normalized,
      provider="none",
      answer="没有完成联网搜索。请先配置阿里百炼 API Key；BOCHA_API_KEY 可作为备用搜索源。",
      local_hits=local_hits,
      suggestions=_suggestions(normalized),
      warning=warning,
    )
  except WebResearchProviderError as error:
    append_app_log(settings, f"historical_web_research provider bocha failed: {error}", level="WARNING")
    warning = "；".join(warnings + provider_errors + [f"bocha: {error}"])
    return HistoricalResearchResult(
      query=normalized,
      provider="none",
      answer="国内联网搜索失败。请稍后重试，或检查阿里百炼 API Key / BOCHA_API_KEY / BOCHA_SEARCH_ENDPOINT 配置。",
      local_hits=local_hits,
      suggestions=_suggestions(normalized),
      warning=warning,
    )

  try:
    answer = _synthesize_answer(settings, normalized, local_hits, provider_answer, sources)
  except Exception as error:
    warnings.append(f"模型整理失败：{error}")
    answer = _fallback_answer(normalized, provider_answer, sources)

  return HistoricalResearchResult(
    query=normalized,
    provider="bocha",
    answer=answer,
    sources=sources[:search_limit],
    local_hits=local_hits,
    suggestions=_suggestions(normalized),
    warning="；".join(warnings),
  )
