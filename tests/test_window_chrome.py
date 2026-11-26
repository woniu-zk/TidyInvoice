"""无边框窗口的放置与缩放：纯函数单测 + 前后端契约。"""

from __future__ import annotations

import os
from pathlib import Path

import window_chrome

ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = ROOT / "main.py"
APP_API_PATH = ROOT / "app_api.py"
HTML_PATH = ROOT / "templates" / "index.html"
SOURCE_PATH = ROOT / "templates" / "index_app.js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --- 纯函数 -------------------------------------------------------------------


def test_centered_rect_centers_within_the_work_area():
    work_area = (0, 0, 2560, 1528)
    x, y, width, height = window_chrome.centered_rect(work_area, (2040, 1260))
    assert (width, height) == (2040, 1260)
    assert x == (2560 - 2040) // 2
    assert y == (1528 - 1260) // 2


def test_centered_rect_respects_margin_and_offsets_for_secondary_monitors():
    work_area = (2560, 0, 5120, 1440)
    x, y, width, height = window_chrome.centered_rect(work_area, (1000, 800), margin=40)
    assert (width, height) == (1000, 800)
    assert x == 2560 + (2560 - 1000) // 2
    assert y == (1440 - 800) // 2


def test_centered_rect_shrinks_windows_larger_than_the_work_area():
    x, y, width, height = window_chrome.centered_rect((0, 0, 800, 600), (1360, 840), margin=24)
    assert (width, height) == (776, 576)
    assert (x, y) == (12, 12)


def test_resized_rect_follows_each_edge():
    start = (100, 100, 800, 600)

    assert window_chrome.resized_rect(start, "e", (40, 0), (100, 100)) == (100, 100, 840, 600)
    assert window_chrome.resized_rect(start, "w", (-40, 0), (100, 100)) == (60, 100, 840, 600)
    assert window_chrome.resized_rect(start, "s", (0, 30), (100, 100)) == (100, 100, 800, 630)
    assert window_chrome.resized_rect(start, "n", (0, -30), (100, 100)) == (100, 70, 800, 630)


def test_resized_rect_handles_corners():
    start = (100, 100, 800, 600)

    assert window_chrome.resized_rect(start, "se", (40, 30), (100, 100)) == (100, 100, 840, 630)
    assert window_chrome.resized_rect(start, "nw", (-40, -30), (100, 100)) == (60, 70, 840, 630)
    assert window_chrome.resized_rect(start, "ne", (40, -30), (100, 100)) == (100, 70, 840, 630)
    assert window_chrome.resized_rect(start, "sw", (-40, 30), (100, 100)) == (60, 100, 840, 630)


def test_resized_rect_clamps_to_the_minimum_size():
    start = (100, 100, 800, 600)
    min_size = (900, 620)

    assert window_chrome.resized_rect(start, "e", (-1000, 0), min_size) == (100, 100, 900, 600)
    assert window_chrome.resized_rect(start, "w", (1000, 0), min_size) == (0, 100, 900, 600)
    assert window_chrome.resized_rect(start, "s", (0, -1000), min_size) == (100, 100, 800, 620)
    assert window_chrome.resized_rect(start, "n", (0, 1000), min_size) == (100, 80, 800, 620)


def test_resized_rect_ignores_unknown_edges():
    start = (100, 100, 800, 600)
    assert window_chrome.resized_rect(start, "center", (50, 50), (100, 100)) == start
    assert window_chrome.resized_rect(start, "", (50, 50), (100, 100)) == start


def test_resize_edges_cover_borders_and_corners():
    assert window_chrome.RESIZE_EDGES == frozenset({"n", "s", "e", "w", "ne", "nw", "se", "sw"})


# --- 前后端契约 ---------------------------------------------------------------


def test_main_uses_the_pywebview_drag_selector_used_by_the_frontend():
    main_source = _read(MAIN_PATH)
    frontend_source = _read(SOURCE_PATH)

    assert 'webview.settings["DRAG_REGION_SELECTOR"] = ".pywebview-drag-region"' in main_source
    assert "pywebview-drag-region" in frontend_source
    assert 'className="sidebar-brand pywebview-drag-region"' in frontend_source
    assert 'className="sidebar-spacer pywebview-drag-region"' in frontend_source
    assert 'className="sidebar-topbar pywebview-drag-region"' in frontend_source
    # 旧选择器没有任何 DOM 元素匹配，曾导致窗口无法拖动。
    assert ".window-drag-region" not in main_source
    assert "window-drag-region" not in frontend_source


def test_main_centers_the_window_before_it_is_shown():
    main_source = _read(MAIN_PATH)

    assert "import window_chrome" in main_source
    assert "window.events.before_show += lambda *_: _apply_window_chrome(window)" in main_source
    assert "window_chrome.attach(" in main_source
    assert "WINDOW_BASELINE_WIDTH" in main_source
    # pywebview 的 WinForms 后端会把 x/y 再按 DPI 缩放一次，几何改由 window_chrome 接管。
    assert "screen=window_geometry" not in main_source
    assert "_resolve_window_geometry" not in main_source


def test_frontend_resize_handles_drive_the_window_resize_api():
    source = _read(SOURCE_PATH)
    styles = _read(HTML_PATH)
    api_source = _read(APP_API_PATH)

    for edge in ("n", "s", "e", "w", "ne", "nw", "se", "sw"):
        assert f"window-resize-handle--{edge}" in styles

    assert "function WindowResizeHandles()" in source
    assert "<WindowResizeHandles />" in source
    assert 'callApi("begin_window_resize", edge)' in source
    assert 'callApi("update_window_resize", deltaX, deltaY)' in source
    assert 'callApi("end_window_resize")' in source

    for method in ("begin_window_resize", "update_window_resize", "end_window_resize"):
        assert f"def {method}(" in api_source


def test_window_chrome_module_exposes_platform_flag():
    assert isinstance(window_chrome.SUPPORTS_NATIVE_CHROME, bool)
    assert window_chrome.SUPPORTS_NATIVE_CHROME == (os.name == "nt")
