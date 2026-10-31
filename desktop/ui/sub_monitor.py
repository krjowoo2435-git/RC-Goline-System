from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import cv2
import numpy as np

from ..models import RankRow
from ..storage import load_overall_records


class SubMonitor(tk.Toplevel):
    """서브모니터 (Figma): 현재 경기 기록 | 역대 기록 / 현재 랩 기록 | 캠."""

    def __init__(self, master: tk.Tk) -> None:
        super().__init__(master)
        self.title("RCGLS 서브모니터")
        self.geometry("1400x900")
        self.configure(bg="#6B7280")
        self._camera_photo = None
        self._build()
        self.refresh_history()

    def _block(self, parent: tk.Widget, title: str) -> tuple[tk.Frame, tk.Frame]:
        wrap = tk.Frame(parent, bg="#C4C4C4", highlightbackground="#FFFFFF", highlightthickness=2)
        tk.Label(
            wrap,
            text=title,
            bg="#C4C4C4",
            fg="#FFFFFF",
            font=("Segoe UI Semibold", 22),
            anchor="nw",
        ).pack(fill="x", padx=16, pady=(14, 6))
        body = tk.Frame(wrap, bg="#C4C4C4")
        body.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        return wrap, body

    def _build(self) -> None:
        root = tk.Frame(self, bg="#6B7280")
        root.pack(fill="both", expand=True, padx=10, pady=10)
        root.columnconfigure(0, weight=3)
        root.columnconfigure(1, weight=2)
        root.rowconfigure(0, weight=3)
        root.rowconfigure(1, weight=2)

        race_wrap, race_body = self._block(root, "현재 경기 기록")
        race_wrap.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 8))
        cols = ("순위", "RC-ID", "이름", "학번", "합계", "패널티")
        self.race_tree = ttk.Treeview(race_body, columns=cols, show="headings")
        for c, w in zip(cols, (70, 90, 100, 100, 110, 80)):
            self.race_tree.heading(c, text=c)
            self.race_tree.column(c, width=w, anchor="center")
        self.race_tree.pack(fill="both", expand=True)

        hist_wrap, hist_body = self._block(root, "역대 기록")
        hist_wrap.grid(row=0, column=1, sticky="nsew", pady=(0, 8))
        hcols = ("순위", "이름", "학번", "기록")
        self.history_tree = ttk.Treeview(hist_body, columns=hcols, show="headings")
        for c, w in zip(hcols, (70, 110, 90, 100)):
            self.history_tree.heading(c, text=c)
            self.history_tree.column(c, width=w, anchor="center")
        self.history_tree.pack(fill="both", expand=True)

        lap_wrap, lap_body = self._block(root, "현재 랩 기록")
        lap_wrap.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        lcols = ("RC-ID", "이름", "학번", "lap1", "lap2", "lap3")
        self.lap_tree = ttk.Treeview(lap_body, columns=lcols, show="headings")
        for c in lcols:
            self.lap_tree.heading(c, text=c)
            self.lap_tree.column(c, width=100, anchor="center")
        self.lap_tree.pack(fill="both", expand=True)

        # 캠: 패널 크기에 맞춰 이미지만 축소 (위젯은 이미지 크기로 커지지 않음)
        cam_wrap, cam_body = self._block(root, "캠")
        cam_wrap.grid(row=1, column=1, sticky="nsew")
        cam_body.rowconfigure(0, weight=1)
        cam_body.columnconfigure(0, weight=1)
        self.cam_canvas = tk.Canvas(cam_body, bg="#111827", highlightthickness=0)
        self.cam_canvas.grid(row=0, column=0, sticky="nsew")
        self.cam_canvas.create_text(
            10, 10, anchor="nw", text="카메라 대기", fill="#9CA3AF", tags=("hint",)
        )

    def _alive(self) -> bool:
        try:
            return bool(self.winfo_exists())
        except tk.TclError:
            return False

    def update_ranks(self, rows: list[RankRow]) -> None:
        if not self._alive():
            return
        try:
            self.race_tree.delete(*self.race_tree.get_children())
            self.lap_tree.delete(*self.lap_tree.get_children())
        except tk.TclError:
            return
        for row in rows:
            if row.disqualified:
                rank = "DQ"
                penalty = "말소"
            else:
                rank = f"{row.rank}위" if row.rank > 0 else "-"
                penalty = f"+{int(row.penalty_ms / 1000)}s" if row.penalty_ms else "-"
            self.race_tree.insert(
                "",
                "end",
                values=(
                    rank,
                    row.rc_id,
                    row.name,
                    row.student_id,
                    row.total_label,
                    penalty,
                ),
            )
            laps = (row.lap_labels + ["--:--:---"] * 3)[:3]
            self.lap_tree.insert(
                "",
                "end",
                values=(row.rc_id, row.name, row.student_id, *laps),
            )

    def refresh_history(self) -> None:
        """전체 기록(역대) — total 정렬된 JSON/CSV 공통 데이터."""
        if not self._alive():
            return
        try:
            self.history_tree.delete(*self.history_tree.get_children())
        except tk.TclError:
            return
        records = load_overall_records()
        for rec in records[:40]:
            try:
                self.history_tree.insert(
                    "",
                    "end",
                    values=(
                        f"{rec.get('rank', '-')}위",
                        rec.get("name", ""),
                        rec.get("student_id", ""),
                        rec.get("total", ""),
                    ),
                )
            except tk.TclError:
                return

    def update_hardware(self, _state) -> None:
        return

    def update_camera_frame(self, frame_bgr: np.ndarray) -> None:
        """캠 영역 크기에 맞춰 축소 표시 (영역이 이미지에 끌려 커지지 않음)."""
        if not self._alive():
            return
        try:
            cw = max(self.cam_canvas.winfo_width(), 1)
            ch = max(self.cam_canvas.winfo_height(), 1)
            if cw < 20 or ch < 20:
                return
            h, w = frame_bgr.shape[:2]
            scale = min(cw / w, ch / h)
            nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
            resized = cv2.resize(frame_bgr, (nw, nh))
            ok, buf = cv2.imencode(".png", resized)
            if not ok:
                return
            photo = tk.PhotoImage(data=buf.tobytes())
            self._camera_photo = photo
            self.cam_canvas.delete("all")
            ox, oy = (cw - nw) // 2, (ch - nh) // 2
            self.cam_canvas.create_image(ox, oy, anchor="nw", image=photo)
        except tk.TclError:
            return
