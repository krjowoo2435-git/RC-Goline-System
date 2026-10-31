from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Callable, Optional

from ..race_engine import RaceEngine
from . import theme as T


class ManualPenaltyWindow(tk.Toplevel):
    """메인모니터 - 수동 패널티 (Figma)."""

    def __init__(
        self,
        master: tk.Tk,
        engine: RaceEngine,
        on_changed: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(master)
        self.title("메인모니터 - 수동 패널티")
        self.geometry("360x420")
        self.resizable(False, False)
        self.configure(bg="#F3F4F6")
        self.engine = engine
        self.on_changed = on_changed
        self._target_map: dict[str, str] = {}  # label -> rc_id

        self.transient(master)
        self.grab_set()
        self._build()
        self.refresh_targets()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _build(self) -> None:
        root = tk.Frame(self, bg="#F3F4F6")
        root.pack(fill="both", expand=True, padx=20, pady=20)

        tk.Label(
            root,
            text="수동 패널티",
            bg="#F3F4F6",
            fg=T.TEXT,
            font=("Segoe UI Semibold", 16),
        ).pack(anchor="w", pady=(0, 16))

        tk.Label(
            root, text="패널티 대상", bg="#F3F4F6", fg=T.MUTED, font=T.FONT_UI
        ).pack(anchor="w")
        self.target_var = tk.StringVar()
        self.target_box = ttk.Combobox(
            root, textvariable=self.target_var, state="readonly", font=T.FONT_UI
        )
        self.target_box.pack(fill="x", pady=(4, 16))

        tk.Label(
            root, text="시간추가 입력 (초)", bg="#F3F4F6", fg=T.MUTED, font=T.FONT_UI
        ).pack(anchor="w")
        time_row = tk.Frame(root, bg="#F3F4F6")
        time_row.pack(fill="x", pady=(4, 8))
        self.seconds_var = tk.StringVar(value="3")
        tk.Entry(
            time_row,
            textvariable=self.seconds_var,
            font=T.FONT_UI,
            width=12,
            justify="center",
        ).pack(side="left", fill="x", expand=True, padx=(0, 8))
        tk.Button(
            time_row,
            text="시간 추가",
            command=self._add_time,
            bg=T.BTN,
            fg=T.BTN_FG,
            activebackground=T.BTN_ACTIVE,
            relief="flat",
            font=T.FONT_BTN,
            padx=12,
            pady=6,
        ).pack(side="left")

        tk.Frame(root, bg="#E5E7EB", height=1).pack(fill="x", pady=20)

        tk.Button(
            root,
            text="탈락(기록말소형)",
            command=self._disqualify,
            bg="#DC2626",
            fg="#FFFFFF",
            activebackground="#B91C1C",
            activeforeground="#FFFFFF",
            relief="flat",
            font=("Segoe UI Semibold", 13),
            pady=14,
        ).pack(fill="x")

        tk.Label(
            root,
            text="탈락 시 해당 차량의 랩·패널티 기록이 말소됩니다.",
            bg="#F3F4F6",
            fg=T.MUTED,
            font=T.FONT_UI,
            wraplength=300,
            justify="left",
        ).pack(anchor="w", pady=(10, 0))

        tk.Button(
            root,
            text="대상 새로고침",
            command=self.refresh_targets,
            bg="#E5E7EB",
            relief="groove",
            font=T.FONT_UI,
        ).pack(fill="x", pady=(16, 0))

    def refresh_targets(self) -> None:
        targets = self.engine.list_penalty_targets()
        self._target_map = {label: rc for rc, label in targets}
        labels = list(self._target_map.keys())
        self.target_box["values"] = labels
        if not labels:
            self.target_var.set("")
            return
        current = self.target_var.get()
        if current in labels and " [DQ]" not in current:
            return
        # 탈락 후 등: 패널티 부과 가능한(비 DQ) 첫 대상 선택
        for label in labels:
            if " [DQ]" not in label:
                self.target_var.set(label)
                return
        self.target_var.set(labels[0])

    def _selected_rc(self) -> Optional[str]:
        label = self.target_var.get().strip()
        if not label:
            messagebox.showwarning("대상", "패널티 대상을 선택하세요.", parent=self)
            return None
        rc = self._target_map.get(label)
        if not rc:
            messagebox.showwarning("대상", "유효하지 않은 대상입니다.", parent=self)
            return None
        return rc

    def _add_time(self) -> None:
        rc = self._selected_rc()
        if not rc:
            return
        raw = self.seconds_var.get().strip()
        try:
            seconds = float(raw)
        except ValueError:
            messagebox.showwarning("입력", "초 단위 숫자를 입력하세요.", parent=self)
            return
        if seconds <= 0:
            messagebox.showwarning("입력", "0보다 큰 값을 입력하세요.", parent=self)
            return
        if self.engine.add_manual_penalty(rc, seconds):
            self.refresh_targets()
            if self.on_changed:
                self.on_changed()
        else:
            messagebox.showwarning(
                "패널티",
                "패널티를 적용할 수 없습니다.\n탈락 상태이거나 대상을 확인하세요.",
                parent=self,
            )

    def _disqualify(self) -> None:
        rc = self._selected_rc()
        if not rc:
            return
        if not messagebox.askyesno(
            "탈락 확인",
            f"{rc} 기록을 말소하고 탈락 처리할까요?\n이 작업은 되돌릴 수 없습니다.",
            parent=self,
        ):
            return
        if self.engine.disqualify(rc):
            self.refresh_targets()
            if self.on_changed:
                self.on_changed()
        else:
            messagebox.showwarning("탈락", "탈락 처리에 실패했습니다.", parent=self)
