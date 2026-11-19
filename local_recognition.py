"""Local-only invoice recognition: direct parsing + local OCR + anchor rules.

This module replaces the former remote LLM recognition stage. It never touches
the network and never needs an API key:

* PDF with an embedded text layer  -> PyMuPDF text extraction
* scanned PDF / image attachment   -> RapidOCR (ONNX runtime, bundled model)
* OFD (Chinese e-invoice container) -> zip + XML ``ofd:TextCode`` extraction
* 数电票 / 增值税 XML              -> structured field aliases

All text sources are converted to a common text form and then mapped to invoice
fields by deterministic anchor/regex rules plus offline consistency checks.
The produced payload keeps the legacy payload shape consumed by
``InvoiceRecord.from_legacy`` so archive/report/pairing code stays untouched.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time
import unicodedata
import zipfile
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Sequence
from xml.etree import ElementTree as ET

from document_types import (
    CHARGING_SERVICE_TOKENS,
    DINING_BEVERAGE_TOKENS,
    normalize_document_type,
)

logger = logging.getLogger(__name__)

PDF_TEXT_EXTENSIONS = frozenset({".pdf"})
IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"})
OFD_EXTENSIONS = frozenset({".ofd"})
XML_EXTENSIONS = frozenset({".xml"})

MAX_PDF_TEXT_PAGES = 3
MAX_OCR_PAGES = 2
OCR_RENDER_DPI = 200
OCR_LINE_Y_TOLERANCE = 10.0

# Below this amount of useful characters a PDF text layer is treated as empty
# (scanned documents often carry only a header/footer text layer).
MIN_USEFUL_TEXT_CHARS = 40

ENGINE_PDF_TEXT = "local_pdf_text"
ENGINE_OCR_PDF = "local_ocr_pdf"
ENGINE_OCR_IMAGE = "local_ocr_image"
ENGINE_OFD_TEXT = "local_ofd_text"
ENGINE_XML = "local_xml"
ENGINE_UNSUPPORTED = "local_unsupported"
ENGINE_QR_IMAGE = "local_qr_image"
ENGINE_QR_PDF = "local_qr_pdf"

REASON_OK = "LOCAL_PARSE_OK"
REASON_TEXT_UNAVAILABLE = "LOCAL_TEXT_UNAVAILABLE"
REASON_OCR_UNAVAILABLE = "LOCAL_OCR_ENGINE_UNAVAILABLE"
REASON_UNSUPPORTED = "LOCAL_UNSUPPORTED_SOURCE"
REASON_NOT_INVOICE = "LOCAL_NOT_INVOICE"

# Structured supporting documents that the deterministic rules can classify even
# though they are not single invoices.
TYPE_TOLL_SUMMARY = "通行费汇总单"
TYPE_QR_INVOICE = "开票二维码"
TOLL_SUMMARY_MARKERS = ("收费公路通行费电子票据汇总单", "通行费电子票据汇总单")

# A QR code is treated as an invoice-issuing entry point when its payload points
# at a known invoicing platform or contains invoicing keywords.
QR_INVOICE_TEXT_HINTS = (
    "扫码开票",
    "扫码获取电子发票",
    "扫码获取发票",
    "扫码领取",
    "扫码领取电子发票",
    "扫一扫领取电子发票",
    "扫一扫开票",
    "领取电子发票",
    "开票二维码",
)
QR_INVOICE_PAYLOAD_HINTS = (
    "baiwang",
    "nuonuo",
    "fapiao",
    "invoice",
    "issue-scan",
    "chinatax",
    "jss.com.cn",
    "vpiaotong",
    "piaotong",
    "fpkj",
)


class LocalRecognitionUnavailable(RuntimeError):
    """The local recognizer cannot read this document (never a network error)."""

    def __init__(self, reason_code: str, message: str = "") -> None:
        super().__init__(message or reason_code)
        self.reason_code = reason_code


@dataclass
class RecognitionResult:
    payload: dict[str, Any] | None
    engine: str = ""
    reason_code: str = ""
    confidence: float = 0.0
    text_length: int = 0
    elapsed_ms: float = 0.0
    warnings: list[str] = field(default_factory=list)

    @property
    def is_invoice(self) -> bool:
        return bool(self.payload and self.payload.get("is_invoice"))


# ---------------------------------------------------------------------------
# Lazy OCR engine (RapidOCR + ONNX Runtime). Injected in tests via ocr_engine=.
# ---------------------------------------------------------------------------

_OCR_ENGINE: Any = None
_OCR_ENGINE_ERROR: BaseException | None = None
# The pipeline may run two extraction workers; RapidOCR/ONNX inference is
# serialized to avoid concurrent use of one engine instance.
_OCR_INFERENCE_LOCK = threading.Lock()


def _load_ocr_engine() -> Any:
    global _OCR_ENGINE, _OCR_ENGINE_ERROR
    if _OCR_ENGINE is not None:
        return _OCR_ENGINE
    if _OCR_ENGINE_ERROR is not None:
        raise LocalRecognitionUnavailable(REASON_OCR_UNAVAILABLE, str(_OCR_ENGINE_ERROR))
    try:  # pragma: no cover - depends on optional wheel
        from rapidocr_onnxruntime import RapidOCR  # type: ignore

        _OCR_ENGINE = RapidOCR()
    except Exception as exc:  # pragma: no cover - optional dependency
        _OCR_ENGINE_ERROR = exc
        raise LocalRecognitionUnavailable(REASON_OCR_UNAVAILABLE, f"local OCR unavailable: {exc}") from exc
    return _OCR_ENGINE


def ocr_engine_available() -> bool:
    try:
        _load_ocr_engine()
    except LocalRecognitionUnavailable:
        return False
    return True


def _reset_ocr_engine_for_tests() -> None:
    global _OCR_ENGINE, _OCR_ENGINE_ERROR
    _OCR_ENGINE = None
    _OCR_ENGINE_ERROR = None


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

_WHITESPACE_RE = re.compile(r"[\s\u00a0\u3000]+")


def _compact(text: str) -> str:
    """Remove every whitespace character (OCR often injects spaces inside labels)."""
    return _WHITESPACE_RE.sub("", str(text or ""))


def _clean_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in str(text or "").splitlines():
        line = unicodedata.normalize("NFKC", raw).strip()
        line = _WHITESPACE_RE.sub(" ", line)
        if line:
            lines.append(line)
    return lines


def _parse_money(value: str | None) -> Decimal | None:
    if not value:
        return None
    text = str(value).replace(",", "").replace("，", "").strip()
    text = text.replace("￥", "").replace("¥", "")
    try:
        amount = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return amount if amount.is_finite() else None


def _parse_int_date(value: str) -> date | None:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) < 8:
        return None
    try:
        return date(int(digits[0:4]), int(digits[4:6]), int(digits[6:8]))
    except ValueError:
        return None


_DATE_FLEX_RE = re.compile(r"(20\d{2})\s*[年\-/.]\s*(\d{1,2})\s*[月\-/.]\s*(\d{1,2})\s*日?")
_DATE_DIGITS_RE = re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)")


def _find_date(text: str) -> date | None:
    for match in _DATE_FLEX_RE.finditer(text or ""):
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            continue
    for match in _DATE_DIGITS_RE.finditer(text or ""):
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            continue
    return None


def _iter_lines_y_ordered(blocks: Sequence[tuple[float, float, str]], y_tolerance: float) -> list[str]:
    """Group OCR blocks into lines by y coordinate, then order each line by x."""
    ordered = sorted(blocks, key=lambda item: (item[0], item[1]))
    grouped: list[list[tuple[float, float, str]]] = []
    for y0, x0, text in ordered:
        if grouped:
            current = grouped[-1]
            if abs(current[0][0] - y0) <= y_tolerance:
                current.append((y0, x0, text))
                continue
        grouped.append([(y0, x0, text)])
    lines: list[str] = []
    for group in grouped:
        group.sort(key=lambda item: item[1])
        line = " ".join(text.strip() for _y, _x, text in group if text.strip())
        if line:
            lines.append(line)
    return lines


# ---------------------------------------------------------------------------
# Readers: PDF text / PDF OCR / image OCR / OFD text
# ---------------------------------------------------------------------------

def _require_fitz():
    try:
        import fitz  # type: ignore

        return fitz
    except Exception as exc:  # pragma: no cover - dependency is pinned
        raise LocalRecognitionUnavailable("LOCAL_PDF_ENGINE_UNAVAILABLE", str(exc)) from exc


def read_pdf_text(path: str | Path, max_pages: int = MAX_PDF_TEXT_PAGES) -> str:
    fitz = _require_fitz()
    parts: list[str] = []
    with fitz.open(str(path)) as document:
        for page_index in range(min(max_pages, len(document))):
            try:
                parts.append(document.load_page(page_index).get_text("text") or "")
            except Exception:
                continue
    return "\n".join(part for part in parts if part).strip()


def _ocr_blocks_from_bytes(engine: Any, image_bytes: bytes) -> list[tuple[float, float, str]]:
    with _OCR_INFERENCE_LOCK:
        result, _elapsed = engine(image_bytes)
    blocks: list[tuple[float, float, str]] = []
    for item in result or []:
        try:
            box, text = item[0], item[1]
        except (TypeError, IndexError):
            continue
        if not text:
            continue
        try:
            ys = [float(point[1]) for point in box]
            xs = [float(point[0]) for point in box]
        except (TypeError, ValueError, IndexError):
            ys, xs = [0.0], [0.0]
        blocks.append((min(ys), min(xs), str(text)))
    return blocks


def read_pdf_ocr_text(
    path: str | Path,
    *,
    max_pages: int = MAX_OCR_PAGES,
    dpi: int = OCR_RENDER_DPI,
    ocr_engine: Any = None,
) -> str:
    engine = ocr_engine or _load_ocr_engine()
    fitz = _require_fitz()
    page_texts: list[str] = []
    with fitz.open(str(path)) as document:
        for page_index in range(min(max_pages, len(document))):
            try:
                page = document.load_page(page_index)
                pixmap = page.get_pixmap(dpi=dpi, alpha=False)
                image_bytes = pixmap.tobytes("png")
            except Exception as exc:
                logger.debug("PDF render failed for OCR: %s", exc)
                continue
            blocks = _ocr_blocks_from_bytes(engine, image_bytes)
            lines = _iter_lines_y_ordered(blocks, OCR_LINE_Y_TOLERANCE)
            if lines:
                page_texts.append("\n".join(lines))
    return "\n\n".join(page_texts).strip()


def read_image_ocr_text(path: str | Path, *, ocr_engine: Any = None) -> str:
    engine = ocr_engine or _load_ocr_engine()
    try:
        image_bytes = Path(path).read_bytes()
    except OSError as exc:
        raise LocalRecognitionUnavailable("LOCAL_IMAGE_UNREADABLE", str(exc)) from exc
    blocks = _ocr_blocks_from_bytes(engine, image_bytes)
    lines = _iter_lines_y_ordered(blocks, OCR_LINE_Y_TOLERANCE)
    return "\n".join(lines).strip()


def _local_tag(tag: str) -> str:
    return str(tag).rsplit("}", 1)[-1].lower()


def _natural_key(value: str) -> list[Any]:
    return [int(token) if token.isdigit() else token for token in re.split(r"(\d+)", value)]


def _boundary_y(boundary: str | None) -> float | None:
    if not boundary:
        return None
    parts = str(boundary).replace(",", " ").split()
    if len(parts) >= 2:
        try:
            return float(parts[1])
        except ValueError:
            return None
    return None


def read_ofd_text(path: str | Path) -> str:
    """OFD is a zip container; invoice text lives in ``<ofd:TextCode>`` nodes."""
    blocks: list[tuple[float, float, str]] = []
    try:
        with zipfile.ZipFile(str(path)) as archive:
            content_names = [
                name
                for name in archive.namelist()
                if re.search(r"(^|/)Content\.xml$", name, re.IGNORECASE)
            ]
            content_names.sort(key=_natural_key)
            for page_index, name in enumerate(content_names):
                try:
                    root = ET.fromstring(archive.read(name))
                except (ET.ParseError, KeyError, OSError):
                    continue
                items: list[tuple[float, str]] = []
                for element in root.iter():
                    if _local_tag(element.tag) != "textobject":
                        continue
                    text = "".join(
                        child.text
                        for child in element.iter()
                        if _local_tag(child.tag) == "textcode" and child.text
                    ).strip()
                    if not text:
                        continue
                    y = _boundary_y(element.attrib.get("Boundary"))
                    items.append((-(y if y is not None else len(items) + page_index * 10000), text))
                if not items:  # fallback: plain TextCode nodes
                    for index, element in enumerate(root.iter()):
                        if _local_tag(element.tag) == "textcode" and element.text:
                            items.append((float(index), element.text.strip()))
                items.sort(key=lambda item: item[0])
                for order, (y, text) in enumerate(items):
                    blocks.append((y, float(order), text))
    except zipfile.BadZipFile as exc:
        raise LocalRecognitionUnavailable("LOCAL_OFD_INVALID", str(exc)) from exc
    return "\n".join(_iter_lines_y_ordered(blocks, y_tolerance=2.0)).strip()


def read_document_text(
    path: str | Path,
    *,
    ocr_engine: Any = None,
) -> tuple[str, str]:
    """Return ``(text, engine)`` for any supported document; never touches network."""
    suffix = Path(path).suffix.lower()
    if suffix in OFD_EXTENSIONS:
        return read_ofd_text(path), ENGINE_OFD_TEXT
    if suffix in XML_EXTENSIONS:
        try:
            return Path(path).read_text(encoding="utf-8", errors="replace"), ENGINE_XML
        except OSError as exc:
            raise LocalRecognitionUnavailable("LOCAL_XML_UNREADABLE", str(exc)) from exc
    if suffix in IMAGE_EXTENSIONS:
        return read_image_ocr_text(path, ocr_engine=ocr_engine), ENGINE_OCR_IMAGE
    if suffix in PDF_TEXT_EXTENSIONS:
        text = read_pdf_text(path)
        if len(_compact(text)) >= MIN_USEFUL_TEXT_CHARS:
            return text, ENGINE_PDF_TEXT
        ocr_text = read_pdf_ocr_text(path, ocr_engine=ocr_engine)
        return ocr_text, ENGINE_OCR_PDF
    raise LocalRecognitionUnavailable(REASON_UNSUPPORTED, f"unsupported source: {suffix}")


# ---------------------------------------------------------------------------
# Anchor rules: text -> invoice fields
# ---------------------------------------------------------------------------

_INVOICE_NO_PATTERNS = (
    re.compile(r"发票号[码玛]?[:：]?(\d{8,20})"),
    re.compile(r"票据号[码玛]?[:：]?(\d{8,20})"),
    re.compile(r"发票号[码玛]?(\d{8,20})"),
)
_INVOICE_CODE_PATTERNS = (
    re.compile(r"发票代码[:：]?(\d{10,12})"),
    re.compile(r"发票代码(\d{10,12})"),
)
_TIN_SCAN_RE = re.compile(
    r"(?:统一社会信用代码/纳税人识别号|纳税人识别号|统一社会信用代码|税号)[:：]?([0-9A-Z]{15,20})"
)
_NAME_LINE_RE = re.compile(r"名\s*称\s*[:：]\s*([^\n：:]{2,60})")
_NAME_IN_SECTION_RE = re.compile(r"名\s*称\s*[:：]?\s*([^\n：:]{2,60})")

_BUYER_SECTION_RE = re.compile(r"(?:购买方|购方)(?:信息)?(.{0,500}?)(?=销售方|销方|备注|$)", re.S)
_SELLER_SECTION_RE = re.compile(r"(?:销售方|销方)(?:信息)?(.{0,500}?)(?=购买方|购方|备注|$)", re.S)

_TOTAL_STRONG_PATTERNS = (
    re.compile(r"价税合计(?:\(小写\)|（小写）|小写)?[￥¥]?([0-9][0-9,]*\.[0-9]{2})"),
    re.compile(r"[（(]小写[）)][￥¥]?([0-9][0-9,]*\.[0-9]{2})"),
    re.compile(r"小写[^\d]{0,6}([0-9][0-9,]*\.[0-9]{2})"),
)
_TOTAL_FALLBACK_PATTERN = re.compile(r"合计[^\d]{0,24}([0-9][0-9,]*\.[0-9]{2})")
_AMOUNT_TAX_TOTAL_RE = re.compile(
    r"合计[^\d]{0,8}([0-9][0-9,]*\.[0-9]{2})[^\d]{0,8}([0-9][0-9,]*\.[0-9]{2})"
    r"[^\d]{0,8}([0-9][0-9,]*\.[0-9]{2})"
)
_AMOUNT_TAX_PAIR_RE = re.compile(
    r"(?:金额|合计)[^\d]{0,8}([0-9][0-9,]*\.[0-9]{2})[^\d]{0,8}([0-9][0-9,]*\.[0-9]{2})"
)
_AMOUNT_ONLY_RE = re.compile(r"金额[^\d]{0,10}([0-9][0-9,]*\.[0-9]{2})")
_TAX_ONLY_RE = re.compile(r"税额[^\d]{0,10}([0-9][0-9,]*\.[0-9]{2})")
_ITEM_NAME_CELL_RE = re.compile(r"\*[^*\n]{2,24}\*[^\s*]{0,40}")
_ITEM_ROW_LABELS = (
    "货物或应税劳务、服务名称",
    "货物或应税劳务服务名称",
    "货物或应税劳务名称",
    "项目名称",
    "货物名称",
)
_ITEM_ROW_COLUMN_TOKENS = ("规格型号", "单位", "数量", "单价", "金额", "税率", "税额")

_TYPE_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("铁路电子客票", "火车票", "高铁"), "火车票"),
    (("航空运输电子客票行程单", "行程单", "机票", "航班"), "机票"),
    (("出租汽车", "网约车", "滴滴", "高德", "打车"), "打车"),
    (("住宿", "酒店", "宾馆", "旅馆"), "住宿发票"),
    (("餐饮", "餐费", "餐厅", "饭店") + DINING_BEVERAGE_TOKENS, "餐饮"),
    (("通行费", "过路费", "高速费"), "过路费"),
    (("定额发票", "定额"), "定额发票"),
    (CHARGING_SERVICE_TOKENS, "充电"),
)

_DEPARTURE_PATTERNS = {
    "Departure_City": re.compile(r"出发(?:站|城市|地)?[:：]?\s*([^\s,，;；]{2,12})"),
    "Destination_City": re.compile(r"到达(?:站|城市|地)?[:：]?\s*([^\s,，;；]{2,12})"),
}
_DEPARTURE_DATE_RE = re.compile(r"乘车日期[:：]?\s*(\d{4}[-年/.]\d{1,2}[-月/.]\d{1,2})")

# 价税合计（大写）is a redundancy check: the Chinese uppercase amount must agree
# with the numeric total. Only used as an offline confidence signal.
_CN_DIGITS = {
    "零": 0, "壹": 1, "贰": 2, "叁": 3, "肆": 4, "伍": 5, "陆": 6, "柒": 7, "捌": 8, "玖": 9,
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_CN_SMALL_UNITS = {"拾": 10, "十": 10, "佰": 100, "百": 100, "仟": 1000, "千": 1000}
_UPPER_TOTAL_RE = re.compile(
    r"价税合计[^\n]{0,16}?(?:大写)?[)）]?\s*([零壹贰叁肆伍陆柒捌玖拾佰仟万亿圆元角分整正]{2,})"
)
_UPPER_FALLBACK_RE = re.compile(r"[（(]大写[）)]\s*([零壹贰叁肆伍陆柒捌玖拾佰仟万亿圆元角分整正]{2,})")


def _clean_item_cell(value: str) -> str:
    """Normalize one item-name cell: drop column padding and numeric columns."""
    cell = str(value or "").strip()
    if not cell:
        return ""
    cell = re.split(r"\s{2,}", cell, maxsplit=1)[0]
    cell = re.split(r"\s+(?=[0-9¥￥])", cell, maxsplit=1)[0]
    return re.sub(r"\s+", "", cell).strip()


def _item_row_cell(text: str) -> str:
    """Return the first item name from a 货物/项目名称 row, when one exists."""
    lines = str(text or "").splitlines()
    for index, line in enumerate(lines):
        label_end = -1
        for label in _ITEM_ROW_LABELS:
            found = line.find(label)
            if found >= 0:
                label_end = found + len(label)
                break
        if label_end < 0:
            continue
        remainder = line[label_end:].strip(" \t:：")
        if remainder and not any(token in remainder for token in _ITEM_ROW_COLUMN_TOKENS):
            return _clean_item_cell(remainder)
        for later_line in lines[index + 1:]:
            candidate = _clean_item_cell(later_line)
            if candidate:
                return candidate
        return ""
    return ""


def parse_chinese_amount(text: str) -> Decimal | None:
    """Parse a Chinese-uppercase money string (e.g. 壹佰零叁元整 -> 103.00)."""
    raw = str(text or "").strip()
    if not raw:
        return None
    digits: list[str] = []
    for char in raw:
        if char in _CN_DIGITS or char in _CN_SMALL_UNITS or char in {"万", "亿", "圆", "元", "角", "分", "整", "正"}:
            digits.append(char)
    if not digits:
        return None
    integer_text = "".join(digits)
    fraction = Decimal("0")
    yuan_match = re.search(r"[圆元]", integer_text)
    if yuan_match:
        main_text = integer_text[: yuan_match.start()]
        fraction_text = integer_text[yuan_match.end() :]
    else:
        split_match = re.search(r"[角分]", integer_text)
        main_text = integer_text[: split_match.start()] if split_match else integer_text
        fraction_text = integer_text[split_match.start() :] if split_match else ""
    jiao_match = re.search(r"([零壹贰叁肆伍陆柒捌玖])角", fraction_text)
    fen_match = re.search(r"([零壹贰叁肆伍陆柒捌玖])分", fraction_text)
    if jiao_match:
        fraction += Decimal(_CN_DIGITS[jiao_match.group(1)]) / Decimal(10)
    if fen_match:
        fraction += Decimal(_CN_DIGITS[fen_match.group(1)]) / Decimal(100)
    main_text = main_text.replace("整", "").replace("正", "")
    total = Decimal(0)
    section = 0
    number = 0
    for char in main_text:
        if char in _CN_DIGITS:
            number = _CN_DIGITS[char]
        elif char in _CN_SMALL_UNITS:
            section += (number or 1) * _CN_SMALL_UNITS[char]
            number = 0
        elif char == "万":
            total += (section + number) * 10000
            section = 0
            number = 0
        elif char == "亿":
            total = (total + section + number) * 100000000
            section = 0
            number = 0
        elif char in {"圆", "元"}:
            total += section + number
            section = 0
            number = 0
    if section or number:
        total += section + number
    return total + fraction


def find_chinese_upper_amount(text: str) -> Decimal | None:
    match = _UPPER_TOTAL_RE.search(text or "") or _UPPER_FALLBACK_RE.search(text or "")
    if not match:
        return None
    return parse_chinese_amount(match.group(1))


def _plausible_company_name(value: str) -> str:
    name = unicodedata.normalize("NFKC", str(value or "")).strip()
    name = _WHITESPACE_RE.sub("", name)
    name = name.strip(":：、,，;；")
    if len(name) < 2:
        return ""
    if name in {"名称", "购买方", "销售方", "信息"}:
        return ""
    return name


def _section_name(section_text: str) -> str:
    for pattern in (_NAME_IN_SECTION_RE, _NAME_LINE_RE):
        match = pattern.search(section_text or "")
        if match:
            name = _plausible_company_name(match.group(1))
            if name:
                return name
    return ""


class _FieldExtractor:
    """Deterministic anchor/rule extraction over one invoice text blob."""

    def __init__(self, text: str) -> None:
        self.text = str(text or "")
        self.flat = _compact(self.text)
        self.lines = _clean_lines(self.text)

    # -- identity -----------------------------------------------------------
    def invoice_number(self) -> str:
        for pattern in _INVOICE_NO_PATTERNS:
            match = pattern.search(self.flat)
            if match:
                return match.group(1)
        if any(token in self.flat for token in ("数电", "电子发票", "全电")):
            match = re.search(r"(?<!\d)(\d{20})(?!\d)", self.flat)
            if match:
                return match.group(1)
        return ""

    def invoice_code(self) -> str:
        for pattern in _INVOICE_CODE_PATTERNS:
            match = pattern.search(self.flat)
            if match:
                return match.group(1)
        return ""

    # -- date ---------------------------------------------------------------
    def invoice_date(self) -> date | None:
        label_index = self.flat.find("开票日期")
        if label_index >= 0:
            window = self.flat[label_index : label_index + 32]
            found = _find_date(window)
            if found:
                return found
        if label_index < 0:
            label_index = self.flat.find("开具日期")
            if label_index >= 0:
                found = _find_date(self.flat[label_index : label_index + 32])
                if found:
                    return found
        return _find_date(self.flat)

    # -- parties ------------------------------------------------------------
    def parties(self) -> tuple[str, str]:
        buyer = _section_name(_BUYER_SECTION_RE.search(self.text).group(1)) if _BUYER_SECTION_RE.search(self.text) else ""
        seller_match = _SELLER_SECTION_RE.search(self.text)
        seller = _section_name(seller_match.group(1)) if seller_match else ""

        names: list[str] = []
        for match in _NAME_LINE_RE.finditer(self.text):
            name = _plausible_company_name(match.group(1))
            if name and name not in names:
                names.append(name)
        if not buyer and not seller and len(names) >= 2:
            buyer, seller = names[0], names[1]
        elif not seller and names:
            seller = names[0]
        elif not buyer and len(names) >= 2:
            buyer = names[0]
            if not seller:
                seller = names[1]
        return buyer, seller

    def tax_ids(self) -> tuple[str, str]:
        matches = [match.group(1) for match in _TIN_SCAN_RE.finditer(self.flat)]
        buyer_tin = matches[0] if len(matches) >= 1 else ""
        seller_tin = matches[1] if len(matches) >= 2 else ""
        return buyer_tin, seller_tin

    # -- money --------------------------------------------------------------
    def amounts(self) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
        amount = tax = total = None
        triple = _AMOUNT_TAX_TOTAL_RE.search(self.flat)
        if triple:
            amount = _parse_money(triple.group(1))
            tax = _parse_money(triple.group(2))
            total = _parse_money(triple.group(3))
        for pattern in _TOTAL_STRONG_PATTERNS:
            if total is not None:
                break
            match = pattern.search(self.flat)
            if match:
                total = _parse_money(match.group(1))
        pair = _AMOUNT_TAX_PAIR_RE.search(self.flat)
        if pair:
            if amount is None:
                amount = _parse_money(pair.group(1))
            if tax is None:
                tax = _parse_money(pair.group(2))
        if total is None:
            match = _TOTAL_FALLBACK_PATTERN.search(self.flat)
            if match:
                total = _parse_money(match.group(1))
        if amount is None:
            match = _AMOUNT_ONLY_RE.search(self.flat)
            if match:
                amount = _parse_money(match.group(1))
        if tax is None:
            match = _TAX_ONLY_RE.search(self.flat)
            if match:
                tax = _parse_money(match.group(1))
        if total is None and amount is not None and tax is not None:
            total = amount + tax
        elif pair is not None and amount is not None and tax is not None and total is not None:
            # A "合计 amount tax" row without < 价税合计 > is still self-consistent.
            if abs((amount + tax) - total) > Decimal("0.02") and total == amount:
                total = amount + tax
        if total is not None and amount is not None and tax is not None:
            if abs((amount + tax) - total) > Decimal("0.02"):
                # Trust the labelled total, keep the others for traceability.
                amount = None
                tax = None
        return amount, tax, total

    # -- classification -----------------------------------------------------
    def item_names(self) -> str:
        """Up to five unique item-name cells, e.g. ``*运输服务*客运服务费``.

        Cells are taken from every ``*tax-category*goods-name`` token in the
        text and, as a fallback source, from the 货物/项目名称 row.
        """
        names: list[str] = []
        for match in _ITEM_NAME_CELL_RE.finditer(self.text):
            name = re.sub(r"\s+", "", match.group(0)).strip()
            if not name or name in names:
                continue
            names.append(name)
            if len(names) >= 5:
                return " | ".join(names)
        row_name = _item_row_cell(self.text)
        if row_name and row_name not in names:
            names.append(row_name)
        return " | ".join(names[:5])

    def item_text(self) -> str:
        names = self.item_names()
        return names.split(" | ", 1)[0] if names else ""

    def document_type(self) -> str:
        haystack = f"{self.item_text()} {self.text[:2500]}"
        for keywords, doc_type in _TYPE_KEYWORDS:
            if any(keyword in haystack for keyword in keywords):
                return normalize_document_type(doc_type)
        return normalize_document_type("其他")

    def route_fields(self) -> dict[str, str]:
        result = {"Departure_Date": "", "Departure_City": "", "Destination_City": ""}
        match = _DEPARTURE_DATE_RE.search(self.flat)
        if match:
            parsed = _find_date(match.group(1))
            if parsed:
                result["Departure_Date"] = parsed.strftime("%Y-%m-%d")
        for key, pattern in _DEPARTURE_PATTERNS.items():
            match = pattern.search(self.text)
            if match:
                result[key] = match.group(1).strip()
        return result


# ---------------------------------------------------------------------------
# Structured supporting documents: toll summary sheets and invoice QR codes
# ---------------------------------------------------------------------------

def _lazy_cv2():
    try:
        import cv2  # type: ignore

        return cv2
    except Exception as exc:  # pragma: no cover - optional dependency
        raise LocalRecognitionUnavailable("LOCAL_QR_DECODER_UNAVAILABLE", str(exc)) from exc


def _decode_qr_bgr(bgr) -> list[str]:
    """Decode QR payloads with OpenCV, retrying common photo scales."""
    cv2 = _lazy_cv2()
    detector = cv2.QRCodeDetector()
    payloads: list[str] = []
    for scale in (1.0, 0.5, 0.25):
        image = bgr
        if scale != 1.0:
            image = cv2.resize(bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        try:
            ok, decoded, _points, _ = detector.detectAndDecodeMulti(image)
        except Exception:
            continue
        if ok:
            payloads.extend(str(text) for text in decoded if text)
        if payloads:
            break
    if payloads:
        return payloads
    for scale in (1.0, 0.5, 0.25):
        image = bgr
        if scale != 1.0:
            image = cv2.resize(bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        try:
            text, _points, _ = detector.detectAndDecode(image)
        except Exception:
            continue
        if text:
            return [str(text)]
    return []


def decode_qr_payloads(path: str | Path | None, *, max_pages: int = 2) -> list[str]:
    """Decode QR payloads from an image attachment or PDF pages (local only)."""
    if not path or not os.path.exists(str(path)):
        return []
    suffix = Path(path).suffix.lower()
    cv2 = _lazy_cv2()
    if suffix in IMAGE_EXTENSIONS:
        try:
            import numpy as np
            from PIL import Image

            with Image.open(str(path)) as image:
                rgb = np.asarray(image.convert("RGB"))
        except Exception:
            return []
        try:
            return _decode_qr_bgr(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
        except Exception:
            return []
    if suffix not in PDF_TEXT_EXTENSIONS:
        return []
    try:
        import numpy as np

        fitz = _require_fitz()
    except LocalRecognitionUnavailable:
        return []
    payloads: list[str] = []
    try:
        with fitz.open(str(path)) as document:
            for index in range(min(max_pages, len(document))):
                try:
                    page = document.load_page(index)
                    pixmap = page.get_pixmap(dpi=200, alpha=False)
                    samples = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                        pixmap.height, pixmap.width, pixmap.n
                    )
                    if pixmap.n == 4:
                        bgr = cv2.cvtColor(samples, cv2.COLOR_RGBA2BGR)
                    elif pixmap.n == 3:
                        bgr = cv2.cvtColor(samples, cv2.COLOR_RGB2BGR)
                    else:
                        bgr = cv2.cvtColor(samples, cv2.COLOR_GRAY2BGR)
                except Exception:
                    continue
                payloads.extend(_decode_qr_bgr(bgr))
                if payloads:
                    break
    except Exception:
        return []
    return payloads


def _qr_host(payload: str) -> str:
    match = re.match(r"^https?://([^/]+)", str(payload or ""), re.IGNORECASE)
    return match.group(1).lower() if match else ""


def _qr_provider_label(payload: str) -> str:
    host = _qr_host(payload)
    if "baiwang" in host:
        return "百望云"
    if "nuonuo" in host:
        return "诺诺发票"
    if "chinatax" in host or "jss" in host:
        return "税务平台"
    if "piaotong" in host:
        return "票通"
    if "fapiao" in host or "invoice" in host:
        return "开票平台"
    return host or TYPE_QR_INVOICE


def _is_invoice_issuing_qr(payload: str) -> bool:
    text = str(payload or "").lower()
    if not text:
        return False
    return any(hint in text for hint in QR_INVOICE_PAYLOAD_HINTS)


_QR_AMOUNT_LABELED_PATTERNS = (
    re.compile(r"(?:合计|总计|实付|应付|消费|金额)[^\d\n]{0,10}([0-9][0-9,]*\.[0-9]{2})"),
    re.compile(r"[￥¥]\s*([0-9][0-9,]*\.[0-9]{2})"),
)


def _find_qr_amount(text: str) -> Decimal | None:
    """Pick the receipt total from OCR text without merging adjacent numbers."""
    source = str(text or "")
    for pattern in _QR_AMOUNT_LABELED_PATTERNS:
        match = pattern.search(source)
        if match:
            amount = _parse_money(match.group(1))
            if amount is not None and Decimal("0") < amount < Decimal("1000000"):
                return amount
    # Line-level scan avoids "0321" + "158.80" becoming 321158.80 when spaces are
    # stripped by the compact form; the receipt total is usually the largest
    # two-decimal figure on the ticket.
    line_amounts: list[Decimal] = []
    for line in source.splitlines():
        for match in re.finditer(r"(?<![\d.])([0-9][0-9,]*\.[0-9]{2})(?![\d])", line):
            amount = _parse_money(match.group(1))
            if amount is not None and Decimal("0") < amount < Decimal("1000000"):
                line_amounts.append(amount)
    return max(line_amounts) if line_amounts else None


def _build_qr_invoice_payload(
    text: str,
    qr_payloads: Sequence[str],
    *,
    engine: str,
    document_context: dict[str, Any] | None = None,
) -> RecognitionResult | None:
    """Classify an image/PDF whose invoice-issuing QR code is the real content."""
    invoice_payloads = [payload for payload in qr_payloads if _is_invoice_issuing_qr(payload)]
    text_hint = any(hint in str(text or "") for hint in QR_INVOICE_TEXT_HINTS)
    if not invoice_payloads and not text_hint:
        return None
    qr_payload = invoice_payloads[0] if invoice_payloads else ""
    provider = _qr_provider_label(qr_payload) if qr_payload else TYPE_QR_INVOICE
    host = _qr_host(qr_payload)
    date_value = _find_date(text)
    if date_value is None:
        email_date = str((document_context or {}).get("email_date") or "")
        date_value = _find_date(email_date) or _parse_int_date(email_date)
    amount = _find_qr_amount(text)
    warnings: list[str] = []
    if not qr_payload:
        warnings.append("qr_payload_not_decoded")
    if date_value is None:
        warnings.append("date_missing")
    if amount is None:
        warnings.append("amount_missing")
    confidence = 0.92 if invoice_payloads else 0.72
    payload: dict[str, Any] = {
        "is_invoice": True,
        "Date": date_value.strftime("%Y-%m-%d") if date_value else "",
        "Purchaser": "",
        "Seller": provider,
        "Amount": format(amount, "f") if amount is not None else "",
        "InvoiceCode": "",
        "InvoiceNumber": "",
        "Type": TYPE_QR_INVOICE,
        "category": TYPE_QR_INVOICE,
        "Item": "",
        "Departure_Date": "",
        "Departure_City": "",
        "Destination_City": "",
        "local_recognition": {
            "engine": engine,
            "confidence": confidence,
            "warnings": warnings,
            "qr_provider": provider,
            "qr_host": host,
            "qr_payload_sha256": (
                hashlib.sha256(qr_payload.encode("utf-8", errors="replace")).hexdigest()
                if qr_payload
                else ""
            ),
        },
    }
    return RecognitionResult(
        payload=payload,
        engine=engine,
        reason_code=REASON_OK,
        confidence=confidence,
        text_length=len(_compact(text)),
        warnings=warnings,
    )


def _parse_toll_summary(text: str, engine: str) -> RecognitionResult | None:
    """Recognize 收费公路通行费电子票据汇总单 (toll trip/invoice summary sheet)."""
    flat = _compact(text)
    if not any(marker in flat for marker in TOLL_SUMMARY_MARKERS) and not (
        "通行费" in flat and "汇总单" in flat
    ):
        return None

    date_value = None
    label_index = flat.find("开票申请日期")
    if label_index >= 0:
        date_value = _find_date(flat[label_index : label_index + 40])
    if date_value is None:
        date_value = _find_date(flat)

    amount = None
    for pattern in (
        re.compile(r"交易金额[￥¥]?([0-9][0-9,]*\.[0-9]{2})"),
        re.compile(r"价税合计(?:\(小写\)|（小写）|小写)?[￥¥]?([0-9][0-9,]*\.[0-9]{2})"),
    ):
        match = pattern.search(flat)
        if match:
            amount = _parse_money(match.group(1))
            if amount is not None:
                break

    plate_match = re.search(
        r"车牌号码([京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼][A-Z][0-9A-Z]{4,6})",
        flat,
    )
    plate = plate_match.group(1) if plate_match else ""

    purchaser = ""
    text_lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    for index, line in enumerate(text_lines):
        if "购买方名称" not in line:
            continue
        tail = line.split("购买方名称", 1)[1].strip(" :：\t")
        if tail:
            purchaser = _plausible_company_name(tail)
        if not purchaser and index + 1 < len(text_lines):
            purchaser = _plausible_company_name(text_lines[index + 1])
        if purchaser:
            break
    if not purchaser:
        for match in re.finditer(
            r"购买方名称\s*[:：]?\s*([^\n]{2,80}?)(?=\s*(?:行程数量|票据数量|纳税人识别号|车牌号码|票据信息|行程信息)|$)",
            text,
            re.S,
        ):
            purchaser = _plausible_company_name(match.group(1))
            if purchaser:
                break

    summary_number = ""
    match = re.search(r"汇总单号[:：]?([0-9A-Z]{6,})", flat)
    if match:
        summary_number = match.group(1)

    seller = "通行费电子票据平台"
    if plate:
        seller = f"通行费电子票据平台·{plate}"
    warnings: list[str] = []
    if date_value is None:
        warnings.append("date_missing")
    if amount is None:
        warnings.append("amount_missing")
    confidence = 0.9 if date_value is not None and amount is not None else 0.6
    payload: dict[str, Any] = {
        "is_invoice": True,
        "Date": date_value.strftime("%Y-%m-%d") if date_value else "",
        "Purchaser": purchaser,
        "Seller": seller,
        "Amount": format(amount, "f") if amount is not None else "",
        "InvoiceCode": "",
        "InvoiceNumber": summary_number,
        "Type": TYPE_TOLL_SUMMARY,
        "category": TYPE_TOLL_SUMMARY,
        "Item": "",
        "Departure_Date": "",
        "Departure_City": "",
        "Destination_City": "",
        "local_recognition": {
            "engine": engine,
            "confidence": confidence,
            "warnings": warnings,
            "plate": plate,
        },
    }
    return RecognitionResult(
        payload=payload,
        engine=engine,
        reason_code=REASON_OK,
        confidence=confidence,
        text_length=len(flat),
        warnings=warnings,
    )


def extract_invoice_payload(text: str, *, engine: str, confidence_cap: float = 0.95) -> RecognitionResult:
    """Map an invoice text blob to the legacy payload shape."""
    toll_summary = _parse_toll_summary(text, engine)
    if toll_summary is not None:
        return toll_summary
    extractor = _FieldExtractor(text)
    invoice_number = extractor.invoice_number()
    invoice_code = extractor.invoice_code()
    invoice_date = extractor.invoice_date()
    buyer, seller = extractor.parties()
    buyer_tin, seller_tin = extractor.tax_ids()
    amount, tax, total = extractor.amounts()
    document_type = extractor.document_type()
    route = extractor.route_fields()

    has_invoice_marker = any(
        token in extractor.flat for token in ("发票", "电子发票", "票据", "价税合计", "旅客运输")
    )
    is_invoice = bool(invoice_number or total is not None or has_invoice_marker)
    warnings: list[str] = []
    if not invoice_number:
        warnings.append("invoice_number_missing")
    if total is None:
        warnings.append("amount_missing")
    if not seller:
        warnings.append("seller_missing")
    if invoice_date is None:
        warnings.append("date_missing")

    if not is_invoice:
        return RecognitionResult(
            payload=None,
            engine=engine,
            reason_code=REASON_NOT_INVOICE,
            confidence=0.0,
            text_length=len(_compact(text)),
            warnings=warnings,
        )

    confidence = 0.5
    confidence += 0.15 if invoice_number else 0.0
    confidence += 0.12 if invoice_date else 0.0
    confidence += 0.15 if total is not None else 0.0
    confidence += 0.08 if seller else 0.0
    confidence += 0.05 if document_type != "其他" else 0.0
    # Offline redundancy check: uppercase total must agree with the numeric one.
    upper_total = find_chinese_upper_amount(text)
    if upper_total is not None and total is not None:
        if abs(upper_total - total) <= Decimal("0.01"):
            confidence += 0.03
        else:
            warnings.append("upper_amount_mismatch")
            confidence -= 0.2
    elif upper_total is not None and total is None:
        total = upper_total
        warnings.append("amount_from_uppercase")
    if engine in {ENGINE_OCR_PDF, ENGINE_OCR_IMAGE}:
        confidence = min(confidence, 0.85)
    confidence = round(max(0.05, min(confidence, confidence_cap)), 3)

    payload: dict[str, Any] = {
        "is_invoice": True,
        "Date": invoice_date.strftime("%Y-%m-%d") if invoice_date else "",
        "Purchaser": buyer,
        "Seller": seller,
        "Amount": format(total, "f") if total is not None else "",
        "InvoiceCode": invoice_code,
        "InvoiceNumber": invoice_number,
        "Type": document_type,
        "category": document_type,
        "Item": extractor.item_names(),
        "Departure_Date": route["Departure_Date"],
        "Departure_City": route["Departure_City"],
        "Destination_City": route["Destination_City"],
        "buyer_tin": buyer_tin,
        "seller_tin": seller_tin,
        "local_recognition": {
            "engine": engine,
            "confidence": confidence,
            "warnings": list(warnings),
            "amount_excluding_tax": format(amount, "f") if amount is not None else "",
            "tax_amount": format(tax, "f") if tax is not None else "",
        },
    }
    return RecognitionResult(
        payload=payload,
        engine=engine,
        reason_code=REASON_OK,
        confidence=confidence,
        text_length=len(_compact(text)),
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# XML fallback (数电票/增值税 XML)
# ---------------------------------------------------------------------------

def _xml_payload(xml_text: str) -> RecognitionResult:
    try:
        from provider_direct_invoice import parse_direct_invoice_xml_fields
    except Exception:  # pragma: no cover - import guard
        parse_direct_invoice_xml_fields = None  # type: ignore[assignment]

    fields = parse_direct_invoice_xml_fields(xml_text.encode("utf-8")) if parse_direct_invoice_xml_fields else {}
    if not fields:
        return extract_invoice_payload(xml_text, engine=ENGINE_XML)

    invoice_date = ""
    raw_date = str(fields.get("invoice_date") or "")
    parsed = _find_date(raw_date) or _parse_int_date(raw_date)
    if parsed:
        invoice_date = parsed.strftime("%Y-%m-%d")
    amount_value = _parse_money(str(fields.get("amount") or ""))
    haystack = " ".join(str(value or "") for value in fields.values())
    extractor = _FieldExtractor(haystack)
    document_type = extractor.document_type()
    reasons: list[str] = []
    if not fields.get("invoice_number"):
        reasons.append("invoice_number_missing")
    if not fields.get("seller"):
        reasons.append("seller_missing")
    payload: dict[str, Any] = {
        "is_invoice": True,
        "Date": invoice_date,
        "Purchaser": str(fields.get("purchaser") or ""),
        "Seller": str(fields.get("seller") or ""),
        "seller_tin": str(fields.get("seller_tin") or ""),
        "buyer_tin": str(fields.get("buyer_tin") or ""),
        "Amount": format(amount_value, "f") if amount_value is not None else "",
        "InvoiceCode": str(fields.get("invoice_code") or ""),
        "InvoiceNumber": str(fields.get("invoice_number") or ""),
        "Type": document_type,
        "category": document_type,
        "Item": str(fields.get("item_name") or ""),
        "Departure_Date": "",
        "Departure_City": "",
        "Destination_City": "",
        "local_recognition": {
            "engine": ENGINE_XML,
            "confidence": 0.95 if not reasons else 0.7,
            "warnings": reasons,
        },
    }
    return RecognitionResult(
        payload=payload,
        engine=ENGINE_XML,
        reason_code=REASON_OK,
        confidence=0.95 if not reasons else 0.7,
        text_length=len(_compact(xml_text)),
        warnings=reasons,
    )


# ---------------------------------------------------------------------------
# Public entry point + pipeline worker
# ---------------------------------------------------------------------------

def recognize_document(
    path: str | Path | None,
    *,
    ocr_engine: Any = None,
    document_context: dict[str, Any] | None = None,
) -> RecognitionResult:
    """Recognize one invoice document locally. Never performs network access."""
    started = time.perf_counter()
    try:
        if not path or not os.path.exists(str(path)):
            raise LocalRecognitionUnavailable("LOCAL_SOURCE_MISSING")
        suffix = Path(path).suffix.lower()
        if suffix in XML_EXTENSIONS:
            try:
                xml_text = Path(path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                xml_text = ""
            if xml_text.strip():
                result = _xml_payload(xml_text)
            else:  # binary/encoded XML -> let the field rules try the decoded text
                result = extract_invoice_payload("", engine=ENGINE_XML)
        else:
            text, engine = read_document_text(path, ocr_engine=ocr_engine)
            compact_length = len(_compact(text))
            if compact_length < 10:
                result = RecognitionResult(
                    payload=None,
                    engine=engine,
                    reason_code=REASON_TEXT_UNAVAILABLE,
                    confidence=0.0,
                    text_length=compact_length,
                    warnings=["text_layer_empty"],
                )
            else:
                result = extract_invoice_payload(text, engine=engine)
            qr_engine = (
                ENGINE_QR_IMAGE if suffix in IMAGE_EXTENSIONS else ENGINE_QR_PDF
            )
            qr_payloads: list[str] = []
            needs_qr = result.payload is None
            if suffix in IMAGE_EXTENSIONS:
                qr_payloads = decode_qr_payloads(path)
                if not needs_qr:
                    invoice_info = result.payload or {}
                    text_hint = any(hint in text for hint in QR_INVOICE_TEXT_HINTS)
                    invoice_qr = any(
                        _is_invoice_issuing_qr(payload) for payload in qr_payloads
                    )
                    # Receipts/photos carry the invoice-issuing QR as their real
                    # content; do not let a weak text match hide that.
                    needs_qr = bool(
                        not str(invoice_info.get("InvoiceNumber") or "").strip()
                        and (text_hint or invoice_qr)
                    )
            elif suffix in PDF_TEXT_EXTENSIONS and needs_qr:
                qr_payloads = decode_qr_payloads(path)
            if needs_qr:
                qr_result = _build_qr_invoice_payload(
                    text,
                    qr_payloads,
                    engine=qr_engine,
                    document_context=document_context,
                )
                if qr_result is not None:
                    result = qr_result
    except LocalRecognitionUnavailable as exc:
        result = RecognitionResult(
            payload=None,
            engine=ENGINE_UNSUPPORTED,
            reason_code=exc.reason_code,
            confidence=0.0,
            text_length=0,
            warnings=[str(exc)],
        )
    except Exception as exc:  # never let one document crash a batch
        logger.exception("local recognition crashed")
        result = RecognitionResult(
            payload=None,
            engine=ENGINE_UNSUPPORTED,
            reason_code="LOCAL_RECOGNITION_ERROR",
            confidence=0.0,
            text_length=0,
            warnings=[f"{type(exc).__name__}: {exc}"],
        )
    result.elapsed_ms = round((time.perf_counter() - started) * 1000.0, 1)
    return result


class LocalRecognitionWorker:
    """Pipeline worker compatible with ``SharedRuntimeRemoteExtractor``.

    ``SharedRuntimeRemoteExtractor`` calls ``extract_remote_only(base64_images, ...)``.
    This worker ignores the images (they are not needed for local parsing) and runs
    the deterministic local recognizer instead.
    """

    needs_remote_images = False

    def __init__(self, output_dir: str = "", *, ocr_engine: Any = None) -> None:
        self.output_dir = str(output_dir or "")
        self._ocr_engine = ocr_engine
        self.last_extraction_trace: dict[str, Any] = {}
        self.last_timing_trace: dict[str, Any] = {}
        self.last_route_trace: dict[str, Any] = {}

    def extract_remote_only(
        self,
        base64_images: Any = None,
        custom_rules: str = "",
        pdf_path: str | None = None,
        document_context: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        del base64_images, custom_rules  # local recognition needs neither
        result = recognize_document(
            pdf_path,
            ocr_engine=self._ocr_engine,
            document_context=document_context,
        )
        self.last_extraction_trace = {
            "engine": result.engine,
            "reason_code": result.reason_code,
            "confidence": result.confidence,
            "warnings": list(result.warnings),
            "text_length": result.text_length,
        }
        self.last_timing_trace = {"local_recognition_ms": result.elapsed_ms}
        return result.payload

    def close(self) -> None:  # pragma: no cover - nothing to release
        return None
