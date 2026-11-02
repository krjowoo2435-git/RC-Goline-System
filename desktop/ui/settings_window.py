from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from . import theme as T


class SettingsWindow(tk.Toplevel):
    """랩 수 · 아두이노 · 카메라 설정을 메인과 동일 UI로 표시."""

    def __init__(
        self,
        master: tk.Tk,
        *,
        lap_var: tk.IntVar,
        com_var: tk.StringVar,
        cam_var: tk.StringVar,
        arduino_status_text: str,
        arduino_status_fg: str,
        cam_status_text: str,
        cam_status_fg: str,
        on_lap_change: Callable[..., None],
        on_refresh_com: Callable[[], None],
        on_connect_arduino: Callable[[], None],
        on_connect_camera: Callable[[], None],
        on_disconnect_camera: Callable[[], None],
        gray_btn: Callable,
        on_close: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(master)
        self.title("설정")
        self.geometry("420x360")
        self.resizable(False, False)
        self.configure(bg="#E5E7EB")
        self._on_close = on_close

        self.transient(master)
        self.grab_set()
        self._build(
            lap_var=lap_var,
            com_var=com_var,
            cam_var=cam_var,
            arduino_status_text=arduino_status_text,
            arduino_status_fg=arduino_status_fg,
            cam_status_text=cam_status_text,
            cam_status_fg=cam_status_fg,
            on_lap_change=on_lap_change,
            on_refresh_com=on_refresh_com,
            on_connect_arduino=on_connect_arduino,
            on_connect_camera=on_connect_camera,
            on_disconnect_camera=on_disconnect_camera,
            gray_btn=gray_btn,
        )
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(50, on_refresh_com)

    def _close(self) -> None:
        if self._on_close:
            self._on_close()
        self.destroy()

    def _build(
        self,
        *,
        lap_var: tk.IntVar,
        com_var: tk.StringVar,
        cam_var: tk.StringVar,
        arduino_status_text: str,
        arduino_status_fg: str,
        cam_status_text: str,
        cam_status_fg: str,
        on_lap_change: Callable[..., None],
        on_refresh_com: Callable[[], None],
        on_connect_arduino: Callable[[], None],
        on_connect_camera: Callable[[], None],
        on_disconnect_camera: Callable[[], None],
        gray_btn: Callable,
    ) -> None:
        root = tk.Frame(self, bg="#E5E7EB")
        root.pack(fill="both", expand=True, padx=12, pady=12)

        tk.Label(
            root,
            text="설정",
            bg="#E5E7EB",
            fg=T.TEXT,
            font=("Segoe UI Semibold", 16),
        ).pack(anchor="w", pady=(0, 10))

        lap_wrap = tk.Frame(root, bg=T.BTN)
        lap_wrap.pack(fill="x", pady=4)
        tk.Label(lap_wrap, text="랩 수", bg=T.BTN, fg=T.BTN_FG, font=T.FONT_UI).pack(
            side="left", padx=8, pady=6
        )
        lap_spin = tk.Spinbox(
            lap_wrap,
            from_=1,
            to=10,
            textvariable=lap_var,
            width=6,
            font=T.FONT_UI,
            command=on_lap_change,
        )
        lap_spin.pack(side="right", padx=8, pady=6)
        lap_spin.bind("<FocusOut>", lambda _e: on_lap_change())
        lap_spin.bind("<Return>", lambda _e: on_lap_change())

        arduino_wrap = tk.Frame(root, bg=T.BTN)
        arduino_wrap.pack(fill="x", pady=6)
        tk.Label(
            arduino_wrap, text="아두이노 COM", bg=T.BTN, fg=T.BTN_FG, font=T.FONT_UI
        ).pack(anchor="w", padx=8, pady=(6, 0))
        arduino_line = tk.Frame(arduino_wrap, bg=T.BTN)
        arduino_line.pack(fill="x", padx=6, pady=6)
        self.com_box = ttk.Combobox(arduino_line, textvariable=com_var, width=12)
        self.com_box.pack(side="left", fill="x", expand=True)
        tk.Button(
            arduino_line,
            text="↻",
            width=3,
            command=on_refresh_com,
            bg=T.PANEL_DARK,
            fg="white",
        ).pack(side="left", padx=2)
        tk.Button(
            arduino_line,
            text="연결",
            command=on_connect_arduino,
            bg=T.PANEL_DARK,
            fg="white",
        ).pack(side="left", padx=2)
        self.arduino_status = tk.Label(
            arduino_wrap,
            text=arduino_status_text,
            bg=T.BTN,
            fg=arduino_status_fg,
            font=T.FONT_UI,
            anchor="w",
        )
        self.arduino_status.pack(fill="x", padx=8, pady=(0, 6))

        cam_row = tk.Frame(root, bg="#E5E7EB")
        cam_row.pack(fill="x", pady=6)
        ttk.Combobox(
            cam_row,
            textvariable=cam_var,
            values=["0", "1", "2", "3"],
            width=8,
            state="readonly",
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        gray_btn(cam_row, "카메라 연결", on_connect_camera).pack(
            side="left", fill="x", expand=True, padx=2
        )
        gray_btn(cam_row, "해제", on_disconnect_camera).pack(
            side="left", fill="x", expand=True, padx=(2, 0)
        )
        self.cam_status = tk.Label(
            root,
            text=cam_status_text,
            bg="#E5E7EB",
            fg=cam_status_fg,
            font=T.FONT_UI,
            anchor="w",
        )
        self.cam_status.pack(fill="x", pady=(2, 4))
