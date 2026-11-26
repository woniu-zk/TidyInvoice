"""Windows 无边框窗口的放置与缩放。

pywebview 的 WinForms 后端在 ``frameless=True`` 时会把 ``FormBorderStyle`` 设成
``None``，``resizable=True`` 因此不会产生可拖拽的缩放边缘；WebView2 的子窗口又铺满
整个客户区，系统原生命中测试不会到达顶层窗口（实测顶层窗口收不到 ``WM_NCHITTEST``），
所以缩放由前端指针事件驱动、后端用 SetWindowPos 落盘。本模块负责两件事：

* **居中放置**：按显示器工作区与 DPI 计算尺寸，在 ``before_show``（同步事件，窗口
  尚不可见）里一次性摆好，避免窗口先出现在错误位置再跳动；
* **缩放计算**：把前端传来的 CSS 像素位移换算成物理像素，按拖拽的边/角算出目标矩形
  并限制在最小尺寸以上，再交给 SetWindowPos。

拖动仍然走前端 ``.pywebview-drag-region``（pywebview 默认选择器），见
``docs/ui-design.zh.md`` 第 6 节。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os

IS_WINDOWS = os.name == "nt"
SUPPORTS_NATIVE_CHROME = IS_WINDOWS

BASE_DPI = 96
RESIZE_EDGES = frozenset({"n", "s", "e", "w", "ne", "nw", "se", "sw"})

# --- Win32 常量 ---------------------------------------------------------------
GWL_STYLE = -16
WS_MAXIMIZE = 0x01000000
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
MONITOR_DEFAULTTOPRIMARY = 1
MDT_EFFECTIVE_DPI = 0
SM_CXSCREEN = 0
SM_CYSCREEN = 1


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("rcMonitor", wt.RECT),
        ("rcWork", wt.RECT),
        ("dwFlags", wt.DWORD),
    ]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def centered_rect(work_area, size, margin=0):
    """把 ``size`` 居中放进 ``work_area``，返回 ``(x, y, width, height)``。

    ``work_area`` 是 ``(left, top, right, bottom)``，与 ``size``、``margin``
    使用同一单位（调用方在 DPI 感知进程里传物理像素）。窗口比可用区域大时按可用
    区域收缩，保证窗口完整落在工作区内。
    """
    left, top, right, bottom = work_area
    available_width = max(right - left - margin, 0)
    available_height = max(bottom - top - margin, 0)
    width = min(int(size[0]), available_width)
    height = min(int(size[1]), available_height)
    x = left + max((right - left - width) // 2, 0)
    y = top + max((bottom - top - height) // 2, 0)
    return x, y, width, height


def resized_rect(start_rect, edge, delta, min_size):
    """按拖拽的边计算目标窗口矩形。

    ``start_rect`` 为拖拽开始时的 ``(left, top, width, height)``；``edge`` 取
    ``n/s/e/w/ne/nw/se/sw``；``delta`` 是 ``(dx, dy)`` 物理像素位移；``min_size``
    是 ``(width, height)`` 下限。对边做最小尺寸钳制，返回 ``(left, top, width, height)``。
    """
    edge = str(edge or "").strip().lower()
    if edge not in RESIZE_EDGES:
        return (int(start_rect[0]), int(start_rect[1]), int(start_rect[2]), int(start_rect[3]))
    left, top, width, height = (int(start_rect[0]), int(start_rect[1]), int(start_rect[2]), int(start_rect[3]))
    min_width = max(int(min_size[0]), 1)
    min_height = max(int(min_size[1]), 1)
    right = left + width
    bottom = top + height
    dx, dy = int(delta[0]), int(delta[1])

    if "w" in edge:
        left = min(left + dx, right - min_width)
    if "e" in edge:
        right = max(right + dx, left + min_width)
    if "n" in edge:
        top = min(top + dy, bottom - min_height)
    if "s" in edge:
        bottom = max(bottom + dy, top + min_height)

    return left, top, right - left, bottom - top


# --- Win32 绑定（首次使用时初始化） -------------------------------------------
_user32 = None
_shcore = None


def _win():
    global _user32, _shcore
    if _user32 is not None:
        return _user32
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.MonitorFromWindow.argtypes = [wt.HWND, wt.DWORD]
    user32.MonitorFromWindow.restype = wt.HMONITOR
    user32.MonitorFromPoint.argtypes = [_POINT, wt.DWORD]
    user32.MonitorFromPoint.restype = wt.HMONITOR
    user32.GetMonitorInfoW.argtypes = [wt.HMONITOR, ctypes.c_void_p]
    user32.GetMonitorInfoW.restype = ctypes.c_bool
    user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
    user32.GetWindowRect.restype = ctypes.c_bool
    user32.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowPos.argtypes = [
        wt.HWND,
        wt.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wt.UINT,
    ]
    user32.SetWindowPos.restype = ctypes.c_bool
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int
    _user32 = user32

    try:
        shcore = ctypes.WinDLL("shcore", use_last_error=True)
        shcore.GetDpiForMonitor.argtypes = [
            wt.HMONITOR,
            ctypes.c_int,
            ctypes.POINTER(wt.UINT),
            ctypes.POINTER(wt.UINT),
        ]
        shcore.GetDpiForMonitor.restype = ctypes.c_long
        _shcore = shcore
    except OSError:
        _shcore = None
    return user32


def _dpi_for_monitor(monitor):
    """显示器有效 DPI；取不到时返回 0。"""
    _win()
    if _shcore is None or not monitor:
        return 0
    dpi_x = wt.UINT()
    dpi_y = wt.UINT()
    try:
        if _shcore.GetDpiForMonitor(monitor, MDT_EFFECTIVE_DPI, dpi_x, dpi_y) != 0:
            return 0
    except OSError:
        return 0
    return int(dpi_x.value or 0)


def _primary_monitor():
    return _win().MonitorFromPoint(_POINT(0, 0), MONITOR_DEFAULTTOPRIMARY)


def _monitor_work_area(monitor):
    user32 = _win()
    info = _MONITORINFO()
    info.cbSize = ctypes.sizeof(_MONITORINFO)
    if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        work = info.rcWork
        return work.left, work.top, work.right, work.bottom
    return (
        0,
        0,
        int(user32.GetSystemMetrics(SM_CXSCREEN)),
        int(user32.GetSystemMetrics(SM_CYSCREEN)),
    )


class WindowChrome:
    """一个无边框窗口的放置与缩放状态。"""

    _registry: dict[int, "WindowChrome"] = {}

    def __init__(self, hwnd, min_width=0, min_height=0):
        self.hwnd = int(hwnd)
        self.min_width = int(min_width)
        self.min_height = int(min_height)
        self.applied_rect = None
        self._resize_anchor = None
        self._resize_scale = 1.0

    # -- 放置 ---------------------------------------------------------------
    def dpi_scale(self):
        """窗口所在显示器的 DPI 缩放系数；取不到时按 100% 处理。"""
        user32 = _win()
        monitor = user32.MonitorFromWindow(self.hwnd, MONITOR_DEFAULTTOPRIMARY)
        dpi = _dpi_for_monitor(monitor)
        return (dpi / BASE_DPI) if dpi > 0 else 1.0

    def window_rect(self):
        """返回窗口的物理像素 ``(left, top, width, height)``；失败返回 ``None``。"""
        rect = wt.RECT()
        if not _win().GetWindowRect(self.hwnd, ctypes.byref(rect)):
            return None
        return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top

    def is_maximized(self):
        style = int(_win().GetWindowLongPtrW(self.hwnd, GWL_STYLE))
        return bool(style & WS_MAXIMIZE)

    def center(self, width, height, margin=0):
        """把窗口按逻辑尺寸 ``width``/``height`` 居中到主显示器工作区。"""
        monitor = _primary_monitor()
        dpi = _dpi_for_monitor(monitor)
        scale = (dpi / BASE_DPI) if dpi > 0 else 1.0
        target_x, target_y, target_width, target_height = centered_rect(
            _monitor_work_area(monitor),
            (round(width * scale), round(height * scale)),
            margin=round(margin * scale),
        )
        _win().SetWindowPos(
            self.hwnd,
            0,
            int(target_x),
            int(target_y),
            int(target_width),
            int(target_height),
            SWP_NOZORDER | SWP_NOACTIVATE,
        )
        self.applied_rect = (target_x, target_y, target_width, target_height)
        return self.applied_rect

    # -- 缩放 ---------------------------------------------------------------
    def begin_resize(self, edge):
        """记录缩放起点；最大化或边名非法时返回 ``False``。"""
        edge = str(edge or "").strip().lower()
        if edge not in RESIZE_EDGES or self.is_maximized():
            return False
        rect = self.window_rect()
        if rect is None:
            return False
        self._resize_scale = self.dpi_scale()
        self._resize_anchor = (edge, rect)
        return True

    def update_resize(self, delta_x_css, delta_y_css):
        """按 CSS 像素位移更新窗口矩形，返回新的物理像素矩形或 ``None``。"""
        if self._resize_anchor is None:
            return None
        edge, start_rect = self._resize_anchor
        scale = self._resize_scale or 1.0
        delta = (round(float(delta_x_css) * scale), round(float(delta_y_css) * scale))
        target = resized_rect(
            start_rect,
            edge,
            delta,
            (round(self.min_width * scale), round(self.min_height * scale)),
        )
        _win().SetWindowPos(
            self.hwnd,
            0,
            int(target[0]),
            int(target[1]),
            int(target[2]),
            int(target[3]),
            SWP_NOZORDER | SWP_NOACTIVATE,
        )
        return target

    def end_resize(self):
        """结束缩放，清空起点。"""
        self._resize_anchor = None
        return True


def current():
    """返回最近一次挂接的窗口外壳；没有则返回 ``None``。"""
    if not WindowChrome._registry:
        return None
    return next(reversed(WindowChrome._registry.values()))


def attach(window, width, height, margin=0, min_width=0, min_height=0):
    """在窗口显示前居中放好窗口并登记缩放状态。

    ``window`` 是 pywebview 窗口对象，须在 ``before_show``（同步事件）里调用；返回
    ``WindowChrome``，非 Windows 或窗口尚未创建时返回 ``None``。
    """
    if not SUPPORTS_NATIVE_CHROME:
        return None
    native = getattr(window, "native", None)
    if native is None:
        return None
    chrome = WindowChrome(
        int(native.Handle.ToInt32()),
        min_width=min_width,
        min_height=min_height,
    )
    chrome.center(width, height, margin=margin)
    WindowChrome._registry[chrome.hwnd] = chrome
    window.events.closed += lambda *_: WindowChrome._registry.pop(chrome.hwnd, None)
    return chrome
