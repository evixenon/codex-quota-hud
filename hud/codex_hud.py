"""A small, always-on-top Windows HUD for Codex rate-limit windows.

The HUD deliberately delegates authentication to the installed Codex CLI. It
does not read auth.json, cookies, or browser storage. It asks the local Codex
App Server for the read-only account/rateLimits/read snapshot and renders the
longest available rate-limit window as the weekly window.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


APP_VERSION = "0.1.0"
REFRESH_SECONDS = 90
WINDOW_WIDTH = 250
FULL_WINDOW_HEIGHT = 182
COMPACT_WINDOW_HEIGHT = 38
WINDOW_RIGHT_MARGIN = 20
WINDOW_BOTTOM_MARGIN = 16
QUOTA_LABEL_LEFT_PADDING = 10
FOREGROUND_POLL_MILLISECONDS = 250

SPI_GETWORKAREA = 0x0030
HUD_MUTEX_NAME = r"Local\CodexQuotaHud"
ERROR_ALREADY_EXISTS = 183


class Win32Rect(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]

# The desktop product can be hosted by either Codex itself or the ChatGPT
# desktop shell. Window-title matching makes this resilient to launcher and
# packaging differences.
CODEX_HOST_PROCESS_NAMES = {"codex", "chatgpt"}
CODEX_TITLE_MARKERS = ("codex",)

# Edit these values to change the visual style without touching the data code.
COLORS = {
    "background": "#050b08",
    "surface": "#0a1a12",
    "border": "#18512f",
    "text": "#d8ffe7",
    "muted": "#5c8d70",
    "normal": "#20ff7a",
    "warning": "#d9ff3f",
    "critical": "#ff5a5f",
    "disabled": "#3d5f49",
}


@dataclass(frozen=True)
class QuotaWindow:
    remaining_percent: int
    resets_at: Optional[int]
    window_minutes: Optional[int]


@dataclass(frozen=True)
class UsageSnapshot:
    five_hour: Optional[QuotaWindow]
    weekly: Optional[QuotaWindow]
    plan_type: Optional[str]
    observed_at: float


class AppServerError(RuntimeError):
    """Raised when the local Codex App Server cannot provide a response."""


class HudAlreadyRunning(RuntimeError):
    """Raised when another HUD process already owns the instance mutex."""


class HudInstanceGuard:
    """Keep a Windows named mutex alive for this HUD process."""

    def __init__(self, name: str = HUD_MUTEX_NAME) -> None:
        self.name = name
        self.handle: Optional[wintypes.HANDLE] = None

    def acquire(self) -> bool:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
        kernel32.ReleaseMutex.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.CreateMutexW(None, True, self.name)
        if not handle:
            return False
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False

        kernel32.ReleaseMutex(handle)
        self.handle = handle
        return True

    def close(self) -> None:
        if not self.handle:
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle(self.handle)
        self.handle = None


def _hud_pid_file() -> Path:
    data_dir = Path.home() / ".codex-quota-hud"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "hud.json"


class CodexForegroundMonitor:
    """Detect whether the foreground Windows window belongs to Codex.

    This uses only Win32 window/process metadata. It does not inspect Codex
    conversations, account data, browser storage, or window contents.
    """

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    def __init__(self) -> None:
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        self.user32.GetForegroundWindow.restype = wintypes.HWND
        self.user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self.user32.GetWindowTextLengthW.restype = ctypes.c_int
        self.user32.GetWindowTextW.argtypes = [
            wintypes.HWND,
            wintypes.LPWSTR,
            ctypes.c_int,
        ]
        self.user32.GetWindowTextW.restype = ctypes.c_int

        self.kernel32.OpenProcess.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        self.kernel32.OpenProcess.restype = wintypes.HANDLE
        self.kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel32.CloseHandle.restype = wintypes.BOOL

    @staticmethod
    def _handle_value(handle: wintypes.HWND) -> int:
        return ctypes.cast(handle, ctypes.c_void_p).value or 0

    def _window_title(self, handle: wintypes.HWND) -> str:
        length = self.user32.GetWindowTextLengthW(handle)
        if length <= 0:
            return ""
        buffer = ctypes.create_unicode_buffer(length + 1)
        self.user32.GetWindowTextW(handle, buffer, len(buffer))
        return buffer.value

    def _process_name(self, process_id: int) -> str:
        process = self.kernel32.OpenProcess(
            self.PROCESS_QUERY_LIMITED_INFORMATION, False, process_id
        )
        if not process:
            return ""
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not self.kernel32.QueryFullProcessImageNameW(
                process, 0, buffer, ctypes.byref(size)
            ):
                return ""
            return Path(buffer.value).stem.casefold()
        finally:
            self.kernel32.CloseHandle(process)

    def codex_has_focus(self, hud_window_id: int) -> bool:
        foreground = self.user32.GetForegroundWindow()
        if not foreground:
            return False
        if self._handle_value(foreground) == hud_window_id:
            return True

        process_id = wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(foreground, ctypes.byref(process_id))
        process_name = self._process_name(process_id.value)
        if process_name in CODEX_HOST_PROCESS_NAMES:
            return True

        title = self._window_title(foreground).casefold()
        return any(marker in title for marker in CODEX_TITLE_MARKERS)


def format_reset_countdown(seconds: int) -> str:
    """Format reset time as compact HUD text such as ``5d20h``."""

    remaining = max(0, int(seconds))
    days, remainder = divmod(remaining, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _seconds = divmod(remainder, 60)
    if days:
        return f" {days}D{hours}H"
    if hours:
        return f" {hours}H{minutes}m"
    return f" {minutes}m"


def format_reset_at(timestamp: Optional[int], *, weekly: bool) -> str:
    """Format a local reset timestamp for a compact quota HUD label."""

    if timestamp is None:
        return "--"

    reset_at = datetime.fromtimestamp(timestamp)
    if not weekly:
        return reset_at.strftime("%H:%M")

    weekday = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")[
        reset_at.weekday()
    ]
    return f"{weekday}{reset_at:%H}"


def select_next_reset_window(
    snapshot: Optional[UsageSnapshot], *, now: Optional[int] = None
) -> Optional[tuple[str, bool, QuotaWindow]]:
    """Return the quota window with the nearest upcoming reset."""

    if snapshot is None:
        return None

    candidates = [
        ("5H", False, snapshot.five_hour),
        ("7D", True, snapshot.weekly),
    ]
    available = [candidate for candidate in candidates if candidate[2] is not None]
    if not available:
        return None

    current_time = int(time.time()) if now is None else now
    upcoming = [
        candidate
        for candidate in available
        if candidate[2].resets_at is not None
        and candidate[2].resets_at >= current_time
    ]
    if upcoming:
        return min(upcoming, key=lambda candidate: candidate[2].resets_at or 0)

    # Prefer the short window when reset timestamps are missing or stale.
    return available[0]


def format_compact_status(
    snapshot: Optional[UsageSnapshot], *, now: Optional[int] = None
) -> tuple[str, Optional[int]]:
    """Format the one-line quota and reset-at status."""

    selected = select_next_reset_window(snapshot, now=now)
    if selected is None:
        return "QUOTA --  RESET --", None

    prefix, weekly, window = selected
    reset_at = format_reset_at(window.resets_at, weekly=weekly)
    return (
        f"{prefix} {window.remaining_percent:3d}%  RESET {reset_at}",
        window.remaining_percent,
    )


def snapshot_from_rate_limit_result(
    result: dict[str, Any], *, observed_at: Optional[float] = None
) -> UsageSnapshot:
    """Convert an App Server response into the HUD's quota windows."""

    windows: list[tuple[dict[str, Any], str]] = []
    buckets = result.get("rateLimitsByLimitId")
    if isinstance(buckets, dict):
        for candidate in buckets.values():
            if not isinstance(candidate, dict):
                continue
            for name in ("primary", "secondary"):
                window = candidate.get(name)
                if isinstance(window, dict) and isinstance(window.get("usedPercent"), int):
                    windows.append((window, name))

    rate_limits = result.get("rateLimits")
    if isinstance(rate_limits, dict):
        for name in ("primary", "secondary"):
            window = rate_limits.get(name)
            if isinstance(window, dict) and isinstance(window.get("usedPercent"), int):
                windows.append((window, name))

    if not windows:
        raise AppServerError("当前账户没有可用的额度窗口数据")

    now = int(time.time()) if observed_at is None else int(observed_at)

    def select_nearest(
        candidates: list[tuple[dict[str, Any], str]],
    ) -> Optional[dict[str, Any]]:
        if not candidates:
            return None
        reset_candidates = [
            item for item in candidates if isinstance(item[0].get("resetsAt"), int)
        ]
        future = [item for item in reset_candidates if item[0]["resetsAt"] >= now]
        if future:
            return min(future, key=lambda item: item[0]["resetsAt"])[0]
        if reset_candidates:
            return min(
                reset_candidates,
                key=lambda item: abs(item[0]["resetsAt"] - now),
            )[0]
        return min(
            candidates,
            key=lambda item: item[0].get("windowDurationMins") or float("inf"),
        )[0]

    short_candidates = [
        item
        for item in windows
        if isinstance(item[0].get("windowDurationMins"), int)
        and item[0]["windowDurationMins"] <= 6 * 60
    ]
    weekly_candidates = [
        item
        for item in windows
        if isinstance(item[0].get("windowDurationMins"), int)
        and item[0]["windowDurationMins"] >= 24 * 60
    ]

    # Older responses may omit windowDurationMins. Preserve the historical
    # primary/secondary fallback in that case, while treating a single window
    # as the weekly window (the shape returned by the current API).
    if not short_candidates and not weekly_candidates:
        primary = [item for item in windows if item[1] == "primary"]
        secondary = [item for item in windows if item[1] == "secondary"]
        if secondary:
            short_candidates = primary
            weekly_candidates = secondary
        else:
            weekly_candidates = windows

    def build_window(payload: Optional[dict[str, Any]]) -> Optional[QuotaWindow]:
        if payload is None:
            return None
        used = max(0, min(100, int(payload.get("usedPercent", 100))))
        resets_at = payload.get("resetsAt")
        if not isinstance(resets_at, int):
            resets_at = None
        duration = payload.get("windowDurationMins")
        if not isinstance(duration, int):
            duration = None
        return QuotaWindow(
            remaining_percent=100 - used,
            resets_at=resets_at,
            window_minutes=duration,
        )

    plan_type = result.get("planType") if isinstance(result.get("planType"), str) else None

    return UsageSnapshot(
        five_hour=build_window(select_nearest(short_candidates)),
        weekly=build_window(select_nearest(weekly_candidates)),
        plan_type=plan_type,
        observed_at=time.time() if observed_at is None else observed_at,
    )


class AppServerClient:
    """Minimal JSON-lines client for the local Codex App Server."""

    def __init__(self) -> None:
        self._process: Optional[subprocess.Popen[str]] = None
        self._reader: Optional[threading.Thread] = None
        self._write_lock = threading.Lock()
        self._pending: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._pending_lock = threading.Lock()
        self._next_id = 1

    @staticmethod
    def _find_command() -> list[str]:
        configured = os.environ.get("CODEX_HUD_CODEX_BIN")
        candidates = [configured] if configured else []

        # Windows npm installs normally expose codex.cmd and codex.ps1.
        candidates.extend(
            [
                shutil.which("codex.cmd"),
                shutil.which("codex.exe"),
                shutil.which("codex"),
            ]
        )

        app_data = os.environ.get("APPDATA")
        if app_data:
            candidates.append(str(Path(app_data) / "npm" / "codex.cmd"))
            candidates.append(str(Path(app_data) / "npm" / "codex.ps1"))

        for candidate in candidates:
            if not candidate:
                continue
            path = Path(candidate)
            if not path.exists() and not shutil.which(candidate):
                continue
            if path.suffix.lower() == ".ps1":
                return [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(path),
                ]
            return [str(path)]

        raise AppServerError(
            "找不到 codex 命令。请确认已安装 Codex CLI，并在终端运行 codex --version。"
        )

    def _start(self) -> None:
        if self._process and self._process.poll() is None:
            return

        command = self._find_command() + ["app-server", "--stdio"]
        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            raise AppServerError(f"无法启动 Codex App Server：{exc}") from exc

        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

        self._request(
            "initialize",
            {
                "clientInfo": {
                    "name": "codex-quota-hud",
                    "version": APP_VERSION,
                },
                "capabilities": {"experimentalApi": True},
            },
            timeout=12,
        )

    def _read_loop(self) -> None:
        process = self._process
        if not process or not process.stdout:
            return

        try:
            for line in process.stdout:
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue

                request_id = message.get("id")
                if isinstance(request_id, int):
                    with self._pending_lock:
                        waiter = self._pending.get(request_id)
                    if waiter:
                        waiter.put(message)
        finally:
            with self._pending_lock:
                pending = list(self._pending.values())
            for waiter in pending:
                waiter.put({"error": {"message": "Codex App Server 已退出"}})

    def _request(
        self,
        method: str,
        params: Optional[dict[str, Any]] = None,
        *,
        timeout: float,
    ) -> dict[str, Any]:
        process = self._process
        if not process or process.poll() is not None or not process.stdin:
            raise AppServerError("Codex App Server 未运行")

        with self._pending_lock:
            request_id = self._next_id
            self._next_id += 1
            waiter: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
            self._pending[request_id] = waiter

        request: dict[str, Any] = {"id": request_id, "method": method}
        if params is not None:
            request["params"] = params

        try:
            with self._write_lock:
                process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
                process.stdin.flush()
            response = waiter.get(timeout=timeout)
        except queue.Empty as exc:
            raise AppServerError(f"等待 {method} 超时") from exc
        except (BrokenPipeError, OSError) as exc:
            raise AppServerError(f"无法向 Codex App Server 发送请求：{exc}") from exc
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

        error = response.get("error")
        if error:
            raise AppServerError(str(error.get("message", "Codex App Server 返回错误")))
        return response

    def read_usage(self) -> UsageSnapshot:
        self._start()
        response = self._request("account/rateLimits/read", timeout=12)
        result = response.get("result") or {}
        if not isinstance(result, dict):
            raise AppServerError("Codex App Server 返回了无法识别的额度数据")
        return snapshot_from_rate_limit_result(result)

    def close(self) -> None:
        process = self._process
        self._process = None
        if not process:
            return
        try:
            if process.stdin:
                process.stdin.close()
        except OSError:
            pass
        try:
            process.terminate()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass


class Hud:
    def __init__(self, root: tk.Tk) -> None:
        self._instance_guard = HudInstanceGuard()
        if not self._instance_guard.acquire():
            raise HudAlreadyRunning()
        self._pid_file = _hud_pid_file()
        self._pid_file.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
        self.root = root
        self.client = AppServerClient()
        self.snapshot: Optional[UsageSnapshot] = None
        self._refresh_in_flight = False
        self._drag_origin: Optional[tuple[int, int]] = None
        self._foreground_monitor = CodexForegroundMonitor()
        self._visible = True
        self._compact = False

        root.title("Codex quota HUD")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.8)
        root.configure(bg=COLORS["background"])
        root.geometry(self._default_geometry(FULL_WINDOW_HEIGHT))

        self.outer = tk.Frame(
            root,
            bg=COLORS["background"],
            highlightbackground=COLORS["border"],
            highlightthickness=1,
        )
        self.outer.pack(fill="both", expand=True)

        self.header = tk.Frame(self.outer, bg=COLORS["background"], height=24)
        self.header.pack(fill="x", padx=12, pady=(8, 0))
        self.header.pack_propagate(False)
        self.title_label = tk.Label(
            self.header,
            text="CODEX // 5H + WEEKLY",
            bg=COLORS["background"],
            fg=COLORS["normal"],
            font=("Consolas", 9, "bold"),
        )
        self.title_label.pack(side="left")
        close = tk.Label(
            self.header,
            text="×",
            bg=COLORS["background"],
            fg=COLORS["muted"],
            font=("Segoe UI", 13),
            cursor="hand2",
        )
        close.pack(side="right")
        close.bind("<Button-1>", lambda _event: self.close())

        self.body = tk.Frame(self.outer, bg=COLORS["background"])
        self.body.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        self.battery_canvas = tk.Canvas(
            self.body,
            width=214,
            height=58,
            bg=COLORS["background"],
            highlightthickness=0,
            bd=0,
        )
        self.battery_canvas.pack(fill="x")

        self.five_hour_label = tk.Label(
            self.body,
            text="5H  --",
            bg=COLORS["background"],
            fg=COLORS["normal"],
            font=("Consolas", 11, "bold"),
            anchor="w",
        )
        self.five_hour_label.pack(
            fill="x", padx=(QUOTA_LABEL_LEFT_PADDING, 0), pady=(0, 2)
        )

        self.weekly_label = tk.Label(
            self.body,
            text="7D  --",
            bg=COLORS["background"],
            fg=COLORS["normal"],
            font=("Consolas", 11, "bold"),
            anchor="w",
        )
        self.weekly_label.pack(
            fill="x", padx=(QUOTA_LABEL_LEFT_PADDING, 0), pady=(0, 2)
        )

        self.status_label = tk.Label(
            self.outer,
            text="CONNECTING...",
            bg=COLORS["background"],
            fg=COLORS["muted"],
            font=("Consolas", 7),
            anchor="e",
        )
        self.status_label.pack(fill="x", padx=12, pady=(0, 5))

        self.compact_label = tk.Label(
            self.outer,
            text="QUOTA --  RESET --",
            bg=COLORS["background"],
            fg=COLORS["disabled"],
            font=("Consolas", 11, "bold"),
            anchor="center",
        )

        for widget in (
            self.outer,
            self.header,
            self.title_label,
            self.body,
            self.battery_canvas,
            self.five_hour_label,
            self.weekly_label,
            self.status_label,
            self.compact_label,
        ):
            widget.bind("<ButtonPress-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._drag)
            widget.bind("<Double-Button-1>", lambda _event: self.toggle_mode())

        root.bind("<Escape>", lambda _event: self.close())
        root.bind_all("<Button-3>", self._show_menu)
        self._draw_battery(None)
        self._schedule_countdown()
        self._watch_foreground_window()
        self.refresh()

    def _default_geometry(self, height: int) -> str:
        self.root.update_idletasks()
        work_area = Win32Rect()
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.SystemParametersInfoW.argtypes = [
            wintypes.UINT,
            wintypes.UINT,
            ctypes.POINTER(Win32Rect),
            wintypes.UINT,
        ]
        user32.SystemParametersInfoW.restype = wintypes.BOOL

        if user32.SystemParametersInfoW(
            SPI_GETWORKAREA, 0, ctypes.byref(work_area), 0
        ):
            work_right = work_area.right
            work_bottom = work_area.bottom
        else:
            work_right = self.root.winfo_screenwidth()
            work_bottom = self.root.winfo_screenheight()

        x = max(0, work_right - WINDOW_WIDTH - WINDOW_RIGHT_MARGIN)
        y = max(0, work_bottom - height - WINDOW_BOTTOM_MARGIN)
        return f"{WINDOW_WIDTH}x{height}+{x}+{y}"

    def _start_drag(self, event: tk.Event) -> None:
        self._drag_origin = (event.x_root, event.y_root)

    def _drag(self, event: tk.Event) -> None:
        if self._drag_origin is None:
            return
        old_x, old_y = self._drag_origin
        geometry = self.root.geometry().split("+")
        x, y = int(geometry[1]), int(geometry[2])
        self.root.geometry(f"+{x + event.x_root - old_x}+{y + event.y_root - old_y}")
        self._drag_origin = (event.x_root, event.y_root)

    def _show_menu(self, event: tk.Event) -> None:
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(
            label="切换到完整模式" if self._compact else "切换到单行模式",
            command=self.toggle_mode,
        )
        menu.add_command(label="立即刷新", command=self.refresh)
        menu.add_command(label="关闭", command=self.close)
        menu.tk_popup(event.x_root, event.y_root)

    def toggle_mode(self) -> None:
        """Switch between the full HUD and the one-line status."""

        old_height = COMPACT_WINDOW_HEIGHT if self._compact else FULL_WINDOW_HEIGHT
        self._compact = not self._compact
        new_height = COMPACT_WINDOW_HEIGHT if self._compact else FULL_WINDOW_HEIGHT

        self.root.update_idletasks()
        x = self.root.winfo_x()
        y = self.root.winfo_y() + old_height - new_height

        if self._compact:
            self.header.pack_forget()
            self.body.pack_forget()
            self.status_label.pack_forget()
            self.compact_label.pack(fill="both", expand=True, padx=10, pady=5)
        else:
            self.compact_label.pack_forget()
            self.header.pack(fill="x", padx=12, pady=(8, 0))
            self.body.pack(fill="both", expand=True, padx=12, pady=(0, 8))
            self.status_label.pack(fill="x", padx=12, pady=(0, 5))

        self.root.geometry(f"{WINDOW_WIDTH}x{new_height}+{max(0, x)}+{max(0, y)}")
        self._update_reset_text()

    def refresh(self) -> None:
        if self._refresh_in_flight:
            return
        self._refresh_in_flight = True
        self.status_label.configure(text="正在刷新…", fg=COLORS["muted"])
        threading.Thread(target=self._refresh_worker, daemon=True).start()
        self.root.after(REFRESH_SECONDS * 1000, self.refresh)

    def _refresh_worker(self) -> None:
        try:
            snapshot = self.client.read_usage()
        except Exception as exc:  # Keep the HUD alive when Codex is closed/logged out.
            self.root.after(0, lambda: self._apply_error(str(exc)))
        else:
            self.root.after(0, lambda: self._apply_snapshot(snapshot))
        finally:
            self.root.after(0, self._finish_refresh)

    def _finish_refresh(self) -> None:
        self._refresh_in_flight = False

    def _apply_error(self, message: str) -> None:
        self.snapshot = None
        self._draw_battery(None)
        self._update_reset_text()
        self.status_label.configure(text=message[:48], fg=COLORS["warning"])

    def _apply_snapshot(self, snapshot: UsageSnapshot) -> None:
        self.snapshot = snapshot
        battery_window = snapshot.five_hour or snapshot.weekly
        battery_percent = battery_window.remaining_percent if battery_window else None
        self._draw_battery(
            battery_percent,
            color=self._quota_color(battery_percent),
        )
        self.status_label.configure(
            text=f"LIVE // {datetime.now().strftime('%H:%M:%S')}",
            fg=COLORS["muted"],
        )
        self._update_reset_text()

    def _draw_battery(self, percent: Optional[int], *, color: Optional[str] = None) -> None:
        """Draw a segmented terminal-style battery on the Tk canvas."""

        canvas = self.battery_canvas
        canvas.delete("all")
        accent = color or COLORS["disabled"]
        percent_text = "--%" if percent is None else f"{percent}%"
        percent_value = 0 if percent is None else max(0, min(100, percent))

        # Battery outline and terminal.
        canvas.create_rectangle(10, 12, 204, 48, outline=COLORS["border"], width=2)
        canvas.create_rectangle(204, 24, 211, 36, fill=COLORS["border"], outline="")

        segment_count = 10
        inner_left, inner_top = 16, 18
        inner_width, inner_height = 182, 24
        gap = 3
        segment_width = (inner_width - (segment_count - 1) * gap) / segment_count
        for index in range(segment_count):
            x1 = inner_left + index * (segment_width + gap)
            x2 = x1 + segment_width
            filled = max(0.0, min(1.0, (percent_value - index * 10) / 10))
            canvas.create_rectangle(
                x1,
                inner_top,
                x2,
                inner_top + inner_height,
                fill=COLORS["surface"],
                outline=COLORS["border"],
                width=1,
            )
            if filled:
                canvas.create_rectangle(
                    x1 + 1,
                    inner_top + 1,
                    x1 + max(1, (segment_width - 2) * filled),
                    inner_top + inner_height - 1,
                    fill=accent,
                    outline="",
                )

        canvas.create_text(
            107,
            30,
            text=percent_text,
            fill=COLORS["text"] if percent is not None else COLORS["disabled"],
            font=("Consolas", 15, "bold"),
        )

    @staticmethod
    def _quota_color(percent: Optional[int]) -> str:
        if percent is None:
            return COLORS["disabled"]
        if percent <= 10:
            return COLORS["critical"]
        if percent <= 30:
            return COLORS["warning"]
        return COLORS["normal"]

    def _update_reset_text(self) -> None:
        for label, prefix, weekly, window in (
            (
                self.five_hour_label,
                "5H",
                False,
                self.snapshot.five_hour if self.snapshot else None,
            ),
            (
                self.weekly_label,
                "7D",
                True,
                self.snapshot.weekly if self.snapshot else None,
            ),
        ):
            if window is None:
                label.configure(text=f"{prefix}  --", fg=COLORS["disabled"])
                continue

            if window.resets_at:
                remaining = max(0, window.resets_at - int(time.time()))
                countdown = format_reset_countdown(remaining).strip()
            else:
                countdown = "--"
            reset_at = format_reset_at(window.resets_at, weekly=weekly)
            label.configure(
                text=(
                    f"{prefix} {window.remaining_percent:3d}%  "
                    f"{countdown}  {reset_at}"
                ),
                fg=self._quota_color(window.remaining_percent),
            )

        compact_text, compact_percent = format_compact_status(self.snapshot)
        self.compact_label.configure(
            text=compact_text,
            fg=self._quota_color(compact_percent),
        )

    def _schedule_countdown(self) -> None:
        self._update_reset_text()
        self.root.after(1000, self._schedule_countdown)

    def _watch_foreground_window(self) -> None:
        """Show the HUD only while Codex (or the HUD itself) is foreground."""

        try:
            should_show = self._foreground_monitor.codex_has_focus(
                self.root.winfo_id()
            )
        except OSError:
            # A transient Win32 failure should not close the HUD process.
            should_show = self._visible

        if should_show and not self._visible:
            self.root.deiconify()
            self.root.attributes("-topmost", True)
            self._visible = True
        elif not should_show and self._visible:
            self.root.withdraw()
            self._visible = False

        self.root.after(FOREGROUND_POLL_MILLISECONDS, self._watch_foreground_window)

    def close(self) -> None:
        self.client.close()
        try:
            payload = json.loads(self._pid_file.read_text(encoding="utf-8"))
            if payload.get("pid") == os.getpid():
                self._pid_file.unlink()
        except (OSError, ValueError):
            pass
        self._instance_guard.close()
        self.root.destroy()


def main() -> None:
    if sys.platform != "win32":
        print("此 HUD 当前面向 Windows。", file=sys.stderr)
        raise SystemExit(1)
    root = tk.Tk()
    try:
        Hud(root)
    except HudAlreadyRunning:
        root.destroy()
        return
    root.mainloop()


if __name__ == "__main__":
    main()
