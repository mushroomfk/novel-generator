from __future__ import annotations

import base64
import csv
import io
import json
import mimetypes
import os
import time
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

from fastapi import HTTPException
from pydantic import ValidationError
from pypdf import PdfReader

from novel_backend.config import Settings
from novel_backend.models import (
  ImportedFileBatchRequest,
  KNOWLEDGE_IMPORT_CONTENT_MAX_LENGTH,
  KnowledgeImportItem,
)
from novel_backend.services.config_service import load_config
from novel_backend.services.log_service import append_app_log
from novel_backend.services.model_runtime_service import mark_model_runtime_cooldown, model_runtime_slot
from novel_backend.services.model_transport_service import request_json as transport_request_json


_SUPPORTED_IMPORT_EXTENSIONS = {
  ".txt",
  ".md",
  ".markdown",
  ".json",
  ".csv",
  ".tsv",
  ".html",
  ".htm",
  ".xml",
  ".docx",
  ".pdf",
}

_QWEN_DOC_SUPPORTED_EXTENSIONS = {
  ".txt",
  ".md",
  ".docx",
  ".pdf",
}

_QWEN_DOC_MODEL_NAME = "qwen-doc-turbo"
_QWEN_DOC_READY_STATUS = {"processed"}
_QWEN_DOC_FAILED_STATUS = {"failed", "error", "deleted"}
_QWEN_DOC_WAIT_SECONDS = 45.0
_QWEN_DOC_POLL_INTERVAL_SECONDS = 1.0
_LITEPARSE_OCR_LANGUAGE_ENV = "NOVEL_LITEPARSE_OCR_LANGUAGE"


class _LiteParseUnavailable(RuntimeError):
  pass


def _decode_text_bytes(data: bytes) -> str:
  for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
    try:
      return data.decode(encoding)
    except UnicodeDecodeError:
      continue
  return data.decode("utf-8", errors="ignore")


def _title_from_filename(filename: str) -> str:
  title = Path(filename).stem.strip()
  return title or "导入资料"


def _compact_lines(lines: list[str]) -> str:
  cleaned = [item.strip() for item in lines if item and item.strip()]
  return "\n".join(cleaned).strip()


def _split_import_content(content: str, limit: int = KNOWLEDGE_IMPORT_CONTENT_MAX_LENGTH) -> list[str]:
  normalized = content.replace("\r\n", "\n").strip()
  if not normalized:
    return []
  if len(normalized) <= limit:
    return [normalized]

  pieces: list[str] = []
  buffer = ""
  paragraphs = [item.strip() for item in normalized.split("\n\n") if item.strip()]
  if not paragraphs:
    paragraphs = [normalized]

  def flush_buffer() -> None:
    nonlocal buffer
    if buffer:
      pieces.append(buffer)
      buffer = ""

  for paragraph in paragraphs:
    candidate = f"{buffer}\n\n{paragraph}".strip() if buffer else paragraph
    if len(candidate) <= limit:
      buffer = candidate
      continue

    flush_buffer()
    if len(paragraph) <= limit:
      buffer = paragraph
      continue

    lines = [item.strip() for item in paragraph.splitlines() if item.strip()]
    if not lines:
      lines = [paragraph]

    for line in lines:
      merged = f"{buffer}\n{line}".strip() if buffer else line
      if len(merged) <= limit:
        buffer = merged
        continue

      flush_buffer()
      if len(line) <= limit:
        buffer = line
        continue

      for start in range(0, len(line), limit):
        piece = line[start : start + limit].strip()
        if piece:
          pieces.append(piece)

  flush_buffer()
  return pieces


def _build_segment_title(title: str, index: int, total: int) -> str:
  if total <= 1:
    return title

  suffix = f"（{index}/{total}）"
  max_base_length = max(1, 120 - len(suffix))
  base = title[:max_base_length].rstrip() or title[:max_base_length]
  return f"{base}{suffix}"


def _resolve_qwen_doc_api_key(settings: Settings) -> str:
  model_config = load_config(settings).model
  candidates = [
    model_config.api_key,
    os.getenv("NOVEL_MODEL_API_KEY", ""),
    os.getenv("DASHSCOPE_API_KEY", ""),
    os.getenv("NOVEL_API_KEY", ""),
    os.getenv("OPENAI_API_KEY", ""),
  ]
  for item in candidates:
    value = item.strip()
    if value:
      return value
  raise RuntimeError("还没配置阿里 API Key，不能使用 qwen-doc-turbo。")


def _qwen_doc_base_url(settings: Settings) -> str:
  base_url = load_config(settings).model.base_url.strip().rstrip("/")
  if not base_url:
    raise RuntimeError("模型接口地址不能为空")
  if base_url.endswith("/chat/completions"):
    base_url = base_url[: -len("/chat/completions")]
  return base_url


def _qwen_doc_chat_endpoint(settings: Settings) -> str:
  return f"{_qwen_doc_base_url(settings)}/chat/completions"


def _qwen_doc_files_endpoint(settings: Settings) -> str:
  return f"{_qwen_doc_base_url(settings)}/files"


def _qwen_doc_file_endpoint(settings: Settings, file_id: str) -> str:
  return f"{_qwen_doc_files_endpoint(settings)}/{file_id}"


def _request_json(
  endpoint: str,
  api_key: str,
  *,
  method: str = "GET",
  payload: dict[str, object] | None = None,
  body: bytes | None = None,
  content_type: str | None = "application/json",
) -> dict[str, object]:
  return transport_request_json(
    endpoint,
    api_key=api_key,
    payload=payload,
    method=method,
    body=body,
    content_type=content_type,
    failure_label="文档接口请求失败",
    invalid_json_message="文档接口返回的不是合法 JSON",
    invalid_format_message="文档接口返回格式不正确",
    allow_empty_response=True,
    timeout=120,
  )


def _safe_upload_filename(filename: str) -> str:
  safe_name = Path(filename).name.replace('"', "").replace("\r", "").replace("\n", "").strip()
  return safe_name or "document"


def _build_file_upload_body(filename: str, data: bytes) -> tuple[bytes, str]:
  boundary = f"----NovelGenerator{int(time.time() * 1000)}"
  content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
  safe_name = _safe_upload_filename(filename)
  header = (
    f"--{boundary}\r\n"
    "Content-Disposition: form-data; name=\"purpose\"\r\n\r\n"
    "file-extract\r\n"
    f"--{boundary}\r\n"
    f"Content-Disposition: form-data; name=\"file\"; filename=\"{safe_name}\"\r\n"
    f"Content-Type: {content_type}\r\n\r\n"
  ).encode("utf-8")
  footer = f"\r\n--{boundary}--\r\n".encode("utf-8")
  return header + data + footer, boundary


def _upload_qwen_doc_file(settings: Settings, api_key: str, filename: str, data: bytes) -> str:
  body, boundary = _build_file_upload_body(filename, data)
  payload = _request_json(
    _qwen_doc_files_endpoint(settings),
    api_key,
    method="POST",
    body=body,
    content_type=f"multipart/form-data; boundary={boundary}",
  )
  file_id = payload.get("id")
  if not isinstance(file_id, str) or not file_id.strip():
    raise RuntimeError("文件上传成功但没有拿到 file_id")
  return file_id.strip()


def _wait_for_qwen_doc_file(settings: Settings, api_key: str, file_id: str) -> None:
  deadline = time.time() + _QWEN_DOC_WAIT_SECONDS
  last_status = ""
  while time.time() < deadline:
    payload = _request_json(_qwen_doc_file_endpoint(settings, file_id), api_key, method="GET", content_type=None)
    status = str(payload.get("status") or "").strip().lower()
    if status in _QWEN_DOC_READY_STATUS:
      return
    if status in _QWEN_DOC_FAILED_STATUS:
      raise RuntimeError(f"文档解析失败，状态是 {status}")
    last_status = status or "unknown"
    time.sleep(_QWEN_DOC_POLL_INTERVAL_SECONDS)
  raise RuntimeError(f"文档解析超时，最后状态是 {last_status or 'unknown'}")


def _delete_qwen_doc_file(settings: Settings, api_key: str, file_id: str) -> None:
  _request_json(_qwen_doc_file_endpoint(settings, file_id), api_key, method="DELETE", content_type=None)


def _extract_chat_content(payload: dict[str, object]) -> str:
  choices = payload.get("choices")
  if not isinstance(choices, list) or not choices:
    raise RuntimeError("文档抽取返回格式不正确：缺少 choices")
  first_choice = choices[0]
  if not isinstance(first_choice, dict):
    raise RuntimeError("文档抽取返回格式不正确：choices[0] 不是对象")
  message = first_choice.get("message")
  if not isinstance(message, dict):
    raise RuntimeError("文档抽取返回格式不正确：缺少 message")
  content = message.get("content")
  if isinstance(content, str):
    return content.strip()
  if isinstance(content, list):
    texts: list[str] = []
    for item in content:
      if isinstance(item, dict):
        text = item.get("text")
        if isinstance(text, str) and text.strip():
          texts.append(text.strip())
    merged = "\n".join(texts).strip()
    if merged:
      return merged
  raise RuntimeError("文档抽取返回格式不正确：content 为空")


def _should_use_qwen_doc(settings: Settings | None, suffix: str) -> bool:
  if settings is None or suffix not in _QWEN_DOC_SUPPORTED_EXTENSIONS:
    return False
  model_config = load_config(settings).model
  base_url = model_config.base_url.strip().lower()
  model_name = model_config.model_name.strip().lower()
  if "dashscope.aliyuncs.com" not in base_url and not model_name.startswith("qwen"):
    return False
  try:
    _resolve_qwen_doc_api_key(settings)
  except RuntimeError:
    return False
  return True


def _extract_with_qwen_doc(settings: Settings, filename: str, data: bytes) -> str:
  api_key = _resolve_qwen_doc_api_key(settings)
  file_id = ""
  runtime_task = None
  try:
    with model_runtime_slot(settings, lane="retrieval", task_name="qwen_doc_extract") as task:
      runtime_task = task
      file_id = _upload_qwen_doc_file(settings, api_key, filename, data)
      _wait_for_qwen_doc_file(settings, api_key, file_id)
      payload = _request_json(
        _qwen_doc_chat_endpoint(settings),
        api_key,
        method="POST",
        payload={
          "model": _QWEN_DOC_MODEL_NAME,
          "messages": [
            {
              "role": "system",
              "content": "你是文档抽取助手，只负责按原意提取文本内容，不做总结，不做改写，不补充说明。",
            },
            {
              "role": "system",
              "content": f"fileid://{file_id}",
            },
            {
              "role": "user",
              "content": "请完整提取这份文档的正文，保留标题层级、段落、列表和表格信息。直接输出整理后的文本。",
            },
          ],
          "temperature": 0,
        },
      )
      content = _extract_chat_content(payload).strip()
    if not content:
      raise RuntimeError("qwen-doc-turbo 没有返回正文")
    append_app_log(settings, f"qwen_doc_extract completed for {filename}")
    return content
  except Exception as error:
    if runtime_task is not None:
      mark_model_runtime_cooldown(settings, "retrieval", str(error))
    raise
  finally:
    if file_id:
      try:
        _delete_qwen_doc_file(settings, api_key, file_id)
      except Exception as error:
        append_app_log(settings, f"qwen_doc_extract cleanup failed for {filename}: {error}", level="WARNING")


def _extract_plain_text(filename: str, data: bytes) -> str:
  suffix = Path(filename).suffix.lower()
  text = _decode_text_bytes(data).strip()
  if not text:
    return ""

  if suffix == ".json":
    try:
      payload = json.loads(text)
    except json.JSONDecodeError:
      return text
    return json.dumps(payload, ensure_ascii=False, indent=2)

  if suffix in {".csv", ".tsv"}:
    delimiter = "\t" if suffix == ".tsv" else ","
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    if not rows:
      return ""
    header = rows[0]
    if len(rows) == 1:
      return " | ".join(cell.strip() for cell in header if cell.strip())
    normalized_rows: list[str] = []
    for index, row in enumerate(rows[1:], start=1):
      pairs = [
        f"{header[position].strip() or f'列{position + 1}'}：{cell.strip()}"
        for position, cell in enumerate(row)
        if position < len(header) and cell.strip()
      ]
      if pairs:
        normalized_rows.append(f"第 {index} 行\n" + "\n".join(pairs))
    return "\n\n".join(normalized_rows).strip()

  if suffix in {".html", ".htm", ".xml"}:
    class TextExtractor(HTMLParser):
      def __init__(self):
        super().__init__()
        self._skip_depth = 0
        self.parts: list[str] = []

      def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
          self._skip_depth += 1
        elif tag in {"p", "div", "section", "article", "li", "h1", "h2", "h3", "h4", "h5", "h6", "br"}:
          self.parts.append("\n")

      def handle_endtag(self, tag):
        if tag in {"script", "style"} and self._skip_depth > 0:
          self._skip_depth -= 1
        elif tag in {"p", "div", "section", "article", "li"}:
          self.parts.append("\n")

      def handle_data(self, data):
        if self._skip_depth == 0 and data.strip():
          self.parts.append(data.strip())

    parser = TextExtractor()
    parser.feed(text)
    return _compact_lines("".join(parser.parts).splitlines())

  return text


def _extract_docx_text(data: bytes) -> str:
  try:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
      xml_names = [
        name for name in archive.namelist()
        if name == "word/document.xml" or name.startswith("word/header") or name.startswith("word/footer")
      ]
      texts: list[str] = []
      for name in xml_names:
        try:
          xml_bytes = archive.read(name)
        except KeyError:
          continue
        root = ElementTree.fromstring(xml_bytes)
        paragraphs: list[str] = []
        for paragraph in root.iter():
          if paragraph.tag.endswith("}p"):
            parts = [
              node.text.strip()
              for node in paragraph.iter()
              if node.tag.endswith("}t") and isinstance(node.text, str) and node.text.strip()
            ]
            if parts:
              paragraphs.append("".join(parts))
        if paragraphs:
          texts.append("\n".join(paragraphs))
  except zipfile.BadZipFile as error:
    raise HTTPException(
      status_code=400,
      detail={"code": "invalid_docx", "message": "DOCX 文件损坏，无法解析"},
    ) from error

  return _compact_lines("\n".join(texts).splitlines())


def _extract_pdf_text(data: bytes) -> str:
  try:
    reader = PdfReader(io.BytesIO(data))
  except Exception as error:
    raise HTTPException(
      status_code=400,
      detail={"code": "invalid_pdf", "message": "PDF 文件损坏，无法解析"},
    ) from error

  parts: list[str] = []
  for page in reader.pages:
    try:
      text = page.extract_text() or ""
    except Exception:
      text = ""
    if text.strip():
      parts.append(text.strip())
  return _compact_lines("\n".join(parts).splitlines())


def _format_liteparse_text(result: object) -> str:
  pages = getattr(result, "pages", None)
  page_sections: list[str] = []
  if isinstance(pages, list):
    for fallback_index, page in enumerate(pages, start=1):
      text = str(getattr(page, "text", "") or "").strip()
      if not text:
        continue
      page_num = getattr(page, "page_num", fallback_index)
      try:
        clean_page_num = int(page_num)
      except (TypeError, ValueError):
        clean_page_num = fallback_index
      page_sections.append(f"【第 {clean_page_num} 页】\n{_compact_lines(text.splitlines())}")
  if page_sections:
    return "\n\n".join(page_sections).strip()

  text = str(getattr(result, "text", "") or "").strip()
  return _compact_lines(text.splitlines())


def _extract_pdf_text_with_liteparse(data: bytes, *, ocr_enabled: bool = False) -> str:
  try:
    from liteparse import LiteParse
  except ImportError as error:
    raise _LiteParseUnavailable("LiteParse 未安装") from error

  parser = LiteParse(
    ocr_enabled=ocr_enabled,
    ocr_language=os.getenv(_LITEPARSE_OCR_LANGUAGE_ENV, "eng").strip() or "eng",
    quiet=True,
  )
  return _format_liteparse_text(parser.parse(data))


def _append_import_log(settings: Settings | None, message: str, *, level: str = "INFO") -> None:
  if settings is None:
    return
  append_app_log(settings, message, level=level)


def _extract_pdf_text_local(filename: str, data: bytes, settings: Settings | None = None) -> str:
  liteparse_available = True
  try:
    content = _extract_pdf_text_with_liteparse(data, ocr_enabled=False).strip()
    if content:
      _append_import_log(settings, f"liteparse_extract completed for {filename}")
      return content
  except _LiteParseUnavailable:
    liteparse_available = False
  except Exception as error:
    _append_import_log(settings, f"liteparse_extract fallback for {filename}: {error}", level="WARNING")

  pypdf_content = _extract_pdf_text(data).strip()
  if pypdf_content:
    return pypdf_content

  if liteparse_available:
    try:
      content = _extract_pdf_text_with_liteparse(data, ocr_enabled=True).strip()
      if content:
        _append_import_log(settings, f"liteparse_ocr_extract completed for {filename}")
        return content
    except Exception as error:
      _append_import_log(settings, f"liteparse_ocr_extract fallback for {filename}: {error}", level="WARNING")

  return pypdf_content


def extract_import_text(filename: str, data: bytes, settings: Settings | None = None) -> str:
  suffix = Path(filename).suffix.lower()
  if suffix not in _SUPPORTED_IMPORT_EXTENSIONS:
    supported = "、".join(sorted(_SUPPORTED_IMPORT_EXTENSIONS))
    raise HTTPException(
      status_code=400,
      detail={"code": "unsupported_import_file", "message": f"暂不支持这种文件，当前支持：{supported}"},
    )
  if _should_use_qwen_doc(settings, suffix):
    try:
      return _extract_with_qwen_doc(settings, filename, data).strip()
    except Exception as error:
      append_app_log(settings, f"qwen_doc_extract fallback for {filename}: {error}", level="WARNING")
  if suffix == ".docx":
    return _extract_docx_text(data)
  if suffix == ".pdf":
    return _extract_pdf_text_local(filename, data, settings=settings)
  return _extract_plain_text(filename, data)


def imported_files_to_knowledge_items(
  request: ImportedFileBatchRequest,
  settings: Settings | None = None,
) -> list[KnowledgeImportItem]:
  items: list[KnowledgeImportItem] = []
  for file in request.files:
    try:
      data = base64.b64decode(file.content_base64.encode("utf-8"), validate=True)
    except Exception as error:
      raise HTTPException(
        status_code=400,
        detail={"code": "invalid_file_payload", "message": f"{file.filename} 编码无效"},
      ) from error
    content = extract_import_text(file.filename, data, settings=settings).strip()
    if not content:
      continue
    title = _title_from_filename(file.filename)
    segments = _split_import_content(content)
    for index, segment in enumerate(segments, start=1):
      try:
        items.append(
          KnowledgeImportItem(
            title=_build_segment_title(title, index, len(segments)),
            content=segment,
          )
        )
      except ValidationError as error:
        raise HTTPException(
          status_code=400,
          detail={"code": "invalid_import_file", "message": f"{file.filename} 无法导入，请检查文件内容。"},
        ) from error
  if not items:
    raise HTTPException(
      status_code=400,
      detail={"code": "empty_import_files", "message": "选中的文件没有可导入内容"},
    )
  return items
