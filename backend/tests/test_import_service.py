from __future__ import annotations

import base64
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from novel_backend.config import Settings
from novel_backend.models import (
  AppConfigUpdateRequest,
  EmbeddingConfig,
  ImportedFileBatchRequest,
  ImportedFilePayload,
  KNOWLEDGE_IMPORT_CONTENT_MAX_LENGTH,
  ModelConfig,
)
from novel_backend.services.config_service import initialize_app_storage, save_config
from novel_backend.services.import_service import _format_liteparse_text, extract_import_text, imported_files_to_knowledge_items


def _docx_bytes(*paragraphs: str) -> bytes:
  document_xml = [
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>',
  ]
  for paragraph in paragraphs:
    document_xml.append(f"<w:p><w:r><w:t>{paragraph}</w:t></w:r></w:p>")
  document_xml.append("</w:body></w:document>")

  stream = io.BytesIO()
  with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    archive.writestr("word/document.xml", "".join(document_xml))
  return stream.getvalue()


def _pdf_bytes(text: str) -> bytes:
  stream_text = f"BT /F1 24 Tf 72 720 Td ({text}) Tj ET"
  objects = [
    "1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
    "2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
    "3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\nendobj\n",
    "4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    f"5 0 obj\n<< /Length {len(stream_text)} >>\nstream\n{stream_text}\nendstream\nendobj\n",
  ]
  content = "%PDF-1.4\n"
  offsets: list[int] = []
  for item in objects:
    offsets.append(len(content.encode("latin1")))
    content += item
  xref_offset = len(content.encode("latin1"))
  content += "xref\n0 6\n0000000000 65535 f \n"
  for offset in offsets:
    content += f"{offset:010d} 00000 n \n"
  content += f"trailer\n<< /Root 1 0 R /Size 6 >>\nstartxref\n{xref_offset}\n%%EOF\n"
  return content.encode("latin1")


class _LiteParsePageStub:
  def __init__(self, page_num: int, text: str):
    self.page_num = page_num
    self.text = text


class _LiteParseResultStub:
  def __init__(self, *pages: _LiteParsePageStub):
    self.pages = list(pages)
    self.text = "\n".join(page.text for page in pages)


class ImportServiceTestCase(unittest.TestCase):
  def setUp(self) -> None:
    self._temp_dir = tempfile.TemporaryDirectory()
    self.settings = Settings(data_dir=Path(self._temp_dir.name))
    initialize_app_storage(self.settings)
    save_config(
      self.settings,
      AppConfigUpdateRequest(
        model=ModelConfig(
          provider="aliyun-bailian",
          base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
          api_key="dashscope-key",
          model_name="qwen3.6-plus",
        ),
        embedding=EmbeddingConfig(),
      ),
    )

  def tearDown(self) -> None:
    self._temp_dir.cleanup()

  def test_extract_import_text_supports_docx_html_csv_json_and_pdf(self) -> None:
    docx_text = extract_import_text("设定.docx", _docx_bytes("第一段", "第二段"))
    html_text = extract_import_text(
      "页面.html",
      "<html><body><h1>港口档案</h1><p>灯塔白光像审讯。</p></body></html>".encode("utf-8"),
    )
    csv_text = extract_import_text(
      "线索.csv",
      "角色,线索\n林追,铜钥匙\n旧船队后人,潮位窗口".encode("utf-8"),
    )
    json_text = extract_import_text(
      "设定.json",
      '{"港口":"白石港","线索":["铜钥匙","隐秘航线"]}'.encode("utf-8"),
    )
    pdf_text = extract_import_text("档案.pdf", _pdf_bytes("harbor archive"))

    self.assertIn("第一段", docx_text)
    self.assertIn("港口档案", html_text)
    self.assertIn("角色：林追", csv_text)
    self.assertIn('"港口": "白石港"', json_text)
    self.assertIn("harbor archive", pdf_text)

  def test_extract_import_text_prefers_qwen_doc_for_supported_files(self) -> None:
    with patch("novel_backend.services.import_service._extract_with_qwen_doc", return_value="远端抽取正文") as extract_mock:
      content = extract_import_text("档案.pdf", _pdf_bytes("harbor archive"), settings=self.settings)

    self.assertEqual(content, "远端抽取正文")
    extract_mock.assert_called_once()

  def test_extract_import_text_falls_back_to_local_parser_when_qwen_doc_fails(self) -> None:
    with patch("novel_backend.services.import_service._extract_with_qwen_doc", side_effect=RuntimeError("dashscope unavailable")):
      content = extract_import_text("档案.pdf", _pdf_bytes("harbor archive"), settings=self.settings)

    self.assertIn("harbor archive", content)

  def test_extract_import_text_uses_liteparse_before_pypdf_for_pdf(self) -> None:
    data = _pdf_bytes("pypdf text")
    with (
      patch("novel_backend.services.import_service._extract_pdf_text_with_liteparse", return_value="【第 1 页】\nliteparse text") as liteparse_mock,
      patch("novel_backend.services.import_service._extract_pdf_text", return_value="pypdf text") as pypdf_mock,
    ):
      content = extract_import_text("档案.pdf", data)

    self.assertEqual(content, "【第 1 页】\nliteparse text")
    liteparse_mock.assert_called_once_with(data, ocr_enabled=False)
    pypdf_mock.assert_not_called()

  def test_extract_import_text_falls_back_to_pypdf_when_liteparse_fails(self) -> None:
    data = _pdf_bytes("pypdf text")
    with (
      patch("novel_backend.services.import_service._extract_pdf_text_with_liteparse", side_effect=RuntimeError("liteparse unavailable")) as liteparse_mock,
      patch("novel_backend.services.import_service._extract_pdf_text", return_value="pypdf text") as pypdf_mock,
    ):
      content = extract_import_text("档案.pdf", data)

    self.assertEqual(content, "pypdf text")
    liteparse_mock.assert_called_once_with(data, ocr_enabled=False)
    pypdf_mock.assert_called_once_with(data)

  def test_extract_import_text_tries_liteparse_ocr_when_pdf_text_is_empty(self) -> None:
    data = _pdf_bytes("empty")
    with (
      patch(
        "novel_backend.services.import_service._extract_pdf_text_with_liteparse",
        side_effect=["", "【第 1 页】\nocr text"],
      ) as liteparse_mock,
      patch("novel_backend.services.import_service._extract_pdf_text", return_value="") as pypdf_mock,
    ):
      content = extract_import_text("扫描档案.pdf", data)

    self.assertEqual(content, "【第 1 页】\nocr text")
    self.assertEqual(liteparse_mock.call_count, 2)
    liteparse_mock.assert_any_call(data, ocr_enabled=False)
    liteparse_mock.assert_any_call(data, ocr_enabled=True)
    pypdf_mock.assert_called_once_with(data)

  def test_format_liteparse_text_adds_page_markers(self) -> None:
    content = _format_liteparse_text(
      _LiteParseResultStub(
        _LiteParsePageStub(3, "第一行\n\n第二行"),
        _LiteParsePageStub(4, "第三行"),
      )
    )

    self.assertEqual(content, "【第 3 页】\n第一行\n第二行\n\n【第 4 页】\n第三行")

  def test_imported_files_to_knowledge_items_rejects_unsupported_suffix(self) -> None:
    payload = ImportedFileBatchRequest(
      files=[
        ImportedFilePayload(
          filename="附件.exe",
          content_base64=base64.b64encode(b"fake binary").decode("utf-8"),
        )
      ]
    )

    with self.assertRaises(HTTPException) as context:
      imported_files_to_knowledge_items(payload)

    self.assertEqual(context.exception.status_code, 400)

  def test_imported_files_to_knowledge_items_builds_titles_from_filenames(self) -> None:
    payload = ImportedFileBatchRequest(
      files=[
        ImportedFilePayload(
          filename="旧船队口供.docx",
          content_base64=base64.b64encode(_docx_bytes("铜钥匙是启航凭证。")).decode("utf-8"),
        ),
        ImportedFilePayload(
          filename="潮位窗口.html",
          content_base64=base64.b64encode("<p>涨潮前三分钟开航。</p>".encode("utf-8")).decode("utf-8"),
        ),
        ImportedFilePayload(
          filename="港口旧档案.pdf",
          content_base64=base64.b64encode(_pdf_bytes("harbor testimony")).decode("utf-8"),
        ),
      ]
    )

    items = imported_files_to_knowledge_items(payload)

    self.assertEqual(items[0].title, "旧船队口供")
    self.assertIn("铜钥匙", items[0].content)
    self.assertEqual(items[1].title, "潮位窗口")
    self.assertIn("涨潮前三分钟开航", items[1].content)
    self.assertEqual(items[2].title, "港口旧档案")
    self.assertIn("harbor testimony", items[2].content)

  def test_imported_files_to_knowledge_items_passes_settings_to_qwen_doc_path(self) -> None:
    payload = ImportedFileBatchRequest(
      files=[
        ImportedFilePayload(
          filename="旧档案.pdf",
          content_base64=base64.b64encode(_pdf_bytes("harbor testimony")).decode("utf-8"),
        )
      ]
    )

    with patch("novel_backend.services.import_service._extract_with_qwen_doc", return_value="远端证词") as extract_mock:
      items = imported_files_to_knowledge_items(payload, settings=self.settings)

    self.assertEqual(len(items), 1)
    self.assertEqual(items[0].title, "旧档案")
    self.assertEqual(items[0].content, "远端证词")
    extract_mock.assert_called_once()

  def test_imported_files_to_knowledge_items_splits_large_text_into_segments(self) -> None:
    long_text = ("第一段\n\n" + ("甲" * (KNOWLEDGE_IMPORT_CONTENT_MAX_LENGTH - 10)) + "\n\n第二段\n\n" + ("乙" * 5000)).encode("utf-8")
    payload = ImportedFileBatchRequest(
      files=[
        ImportedFilePayload(
          filename="围城.txt",
          content_base64=base64.b64encode(long_text).decode("utf-8"),
        )
      ]
    )

    items = imported_files_to_knowledge_items(payload)

    self.assertEqual(len(items), 2)
    self.assertEqual(items[0].title, "围城（1/2）")
    self.assertEqual(items[1].title, "围城（2/2）")
    self.assertLessEqual(len(items[0].content), KNOWLEDGE_IMPORT_CONTENT_MAX_LENGTH)
    self.assertLessEqual(len(items[1].content), KNOWLEDGE_IMPORT_CONTENT_MAX_LENGTH)
    self.assertTrue(items[0].content.startswith("第一段"))
    self.assertTrue(any("第二段" in item.content for item in items))
    self.assertTrue(items[1].content.startswith("乙"))


if __name__ == "__main__":
  unittest.main()
