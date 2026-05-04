from __future__ import annotations

import json
import os
import re
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from novel_backend.config import Settings
from novel_backend.models import HistoricalResearchResult, HistoricalResearchSource, KnowledgeSearchResult
from novel_backend.services.generation_service import _invoke_model
from novel_backend.services.log_service import append_app_log
from novel_backend.services.project_service import search_project_knowledge


class WebResearchProviderError(RuntimeError):
  pass


class WebResearchProviderUnavailable(WebResearchProviderError):
  pass


_BOCHA_SEARCH_ENDPOINT = "https://api.bochaai.com/v1/web-search"


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
  body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
  request = urllib_request.Request(endpoint, data=body, method="POST")
  request.add_header("Content-Type", "application/json")
  for key, value in headers.items():
    request.add_header(key, value)

  try:
    with urllib_request.urlopen(request, timeout=timeout) as response:
      raw_text = response.read().decode("utf-8")
  except urllib_error.HTTPError as error:
    error_text = error.read().decode("utf-8", errors="ignore")
    raise WebResearchProviderError(f"{error.code} {error_text or error.reason}") from error
  except urllib_error.URLError as error:
    raise WebResearchProviderError(str(error.reason)) from error

  try:
    parsed = json.loads(raw_text)
  except json.JSONDecodeError as error:
    raise WebResearchProviderError("搜索服务返回的不是合法 JSON") from error
  if not isinstance(parsed, dict):
    raise WebResearchProviderError("搜索服务返回格式不正确")
  return parsed


def _resolve_bocha_api_key() -> str:
  value = os.getenv("BOCHA_API_KEY", "").strip()
  if not value:
    raise WebResearchProviderUnavailable("未配置 BOCHA_API_KEY")
  return value


def _provider_search_query(query: str) -> str:
  normalized = query.strip()
  if any(keyword in normalized for keyword in ("典故", "出处", "历史", "史实", "年代")):
    return normalized
  return f"{normalized} 历史典故 出处 背景 用法"


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

  sources: list[HistoricalResearchSource] = []
  for item in web_pages[:limit]:
    if not isinstance(item, dict):
      continue
    url = str(item.get("url") or "").strip()
    title = str(item.get("name") or item.get("title") or "").strip()
    snippet = _compact_text(str(item.get("snippet") or item.get("summary") or ""), 500)
    site_name = str(item.get("siteName") or "").strip()
    sources.append(
      HistoricalResearchSource(
        title=title or _site_from_url(url) or "搜索结果",
        url=url,
        snippet=snippet,
        summary=_compact_text(str(item.get("summary") or ""), 600),
        site=site_name or _site_from_url(url),
        published_at=str(item.get("dateLastCrawled") or item.get("datePublished") or ""),
        provider="bocha",
      )
    )
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

  try:
    provider_answer, sources = _bocha_research(_provider_search_query(normalized), search_limit)
  except WebResearchProviderUnavailable as error:
    warning = "；".join(warnings + [f"bocha: {error}"])
    return HistoricalResearchResult(
      query=normalized,
      provider="none",
      answer="没有完成联网搜索。请配置 BOCHA_API_KEY 后再试。",
      local_hits=local_hits,
      suggestions=_suggestions(normalized),
      warning=warning,
    )
  except WebResearchProviderError as error:
    append_app_log(settings, f"historical_web_research provider bocha failed: {error}", level="WARNING")
    warning = "；".join(warnings + [f"bocha: {error}"])
    return HistoricalResearchResult(
      query=normalized,
      provider="none",
      answer="国内联网搜索失败。请稍后重试，或检查 BOCHA_API_KEY / BOCHA_SEARCH_ENDPOINT 配置。",
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
