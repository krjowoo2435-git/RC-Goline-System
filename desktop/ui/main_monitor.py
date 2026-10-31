from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional

import cv2
import numpy as np

from ..camera_service import CameraService
from ..finish_line import VirtualFinishLine
from ..hardware import HardwareController, HardwareState, list_com_ports
from ..models import Participant, RacePhase, RankRow
from ..race_engine import RaceConfig, RaceEngine
from ..storage import clear_all_records, load_participants, save_participants
from . import theme as T
from .manual_penalty import ManualPenaltyWindow
from .sub_monitor import SubMonitor


PHASE_LABEL = {
    RacePhase.IDLE: "대기",
    RacePhase.LED_COUNTDOWN: "LED 점등",
    RacePhase.LIGHTS_OFF: "소등",
    RacePhase.WAITING_START: "출발 대기",
    RacePhase.RACING: "계측 중",
    RacePhase.FINISHED: "종료",
}

DEFAULT_LANES = 3


class MainMonitor(tk.Tk):
    """Figma 메인모니터 레이아웃: 좌측 카메라/기록, 우측 컨트롤·학번입력."""

    def __init__(self) -> None:
        super().__init__()
        self.title("RCGLS")
        self.geometry("1440x900")
        self.minsize(1200, 720)
        self.configure(bg=T.BG)

        self.participants = load_participants()
        self.hardware = HardwareController()
        self.finish_line = VirtualFinishLine()
        self.engine = RaceEngine(
            participants=self.participants,
            hardware=self.hardware,
            config=RaceConfig(lap_count=1),
            on_status=self._on_status,
            on_phase=self._on_phase,
            on_rank=self._on_rank,
        )
        self.camera = CameraService(
            camera_index=0,
            on_markers=self._on_markers,
            on_marker_poses=self._on_marker_poses,
            on_frame=self._on_camera_frame,
        )
        self.sub: Optional[SubMonitor] = None
        self.penalty_win: Optional[ManualPenaltyWindow] = None
        self._photo_main = None
        self._latest_frame: Optional[np.ndarray] = None
        self._display_scale = 1.0
        self._display_offset = (0, 0)
        self._fps_frames = 0
        self._fps_t0 = 0.0
        self._fps_value = 0.0
        self._frame_size = (0, 0)
        self._row_vars: list[dict[str, tk.StringVar]] = []

        self._build()
        self._sync_marker_labels()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(80, self._tick)
        self.after(200, self._open_sub_monitor)
        self.after(300, self._refresh_com_ports)

    def _gray_btn(self, parent, text, command, fill=False, pady=4):
        btn = tk.Button(
            parent,
            text=text,
            command=command,
            bg=T.BTN,
            fg=T.BTN_FG,
            activebackground=T.BTN_ACTIVE,
            activeforeground=T.BTN_FG,
            relief="flat",
            font=T.FONT_BTN,
            cursor="hand2",
        )
        if fill:
            btn.pack(fill="x", pady=pady)
        return btn

    def _build(self) -> None:
        root = tk.Frame(self, bg=T.BG)
        root.pack(fill="both", expand=True, padx=10, pady=10)
        root.columnconfigure(0, weight=3)
        root.columnconfigure(1, weight=0)
        root.rowconfigure(0, weight=1)

        # ===== 좌측: 카메라 + 하단 기록바 =====
        left = tk.Frame(root, bg=T.BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.rowconfigure(0, weight=4)
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)

        cam_frame = tk.Frame(left, bg=T.PANEL_ALT, highlightbackground=T.BORDER, highlightthickness=1)
        cam_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
        overlay = tk.Frame(cam_frame, bg=T.PANEL_ALT)
        overlay.pack(fill="x")
        self.fps_label = tk.Label(
            overlay,
            text="--- X ---   FPS: 0",
            bg=T.PANEL_ALT,
            fg=T.MUTED,
            font=T.FONT_MONO,
            anchor="e",
        )
        self.fps_label.pack(side="right", padx=8, pady=4)
        self.line_hint = tk.Label(
            overlay,
            text="카메라 클릭 2점으로 가상 결승선 설정",
            bg=T.PANEL_ALT,
            fg=T.MUTED,
            font=T.FONT_UI,
            anchor="w",
        )
        self.line_hint.pack(side="left", padx=8)

        self.cam_canvas = tk.Canvas(cam_frame, bg="#111827", highlightthickness=0, cursor="crosshair")
        self.cam_canvas.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.cam_canvas.bind("<Button-1>", self._on_camera_click)

        bottom_bar = tk.Frame(
            left, bg=T.PANEL_ALT, highlightbackground=T.BORDER, highlightthickness=1, height=160
        )
        bottom_bar.grid(row=1, column=0, sticky="nsew")
        bottom_bar.grid_propagate(False)
        tk.Label(
            bottom_bar,
            text="프로그램 실행 기록",
            bg=T.PANEL_DARK,
            fg=T.BTN_FG,
            font=T.FONT_RANK,
            anchor="w",
        ).pack(fill="x")
        log_wrap = tk.Frame(bottom_bar, bg=T.PANEL_ALT)
        log_wrap.pack(fill="both", expand=True, padx=6, pady=6)
        log_scroll = ttk.Scrollbar(log_wrap, orient="vertical")
        self.exec_log = tk.Listbox(
            log_wrap,
            height=6,
            bg="#111827",
            fg="#E5E7EB",
            selectbackground="#374151",
            font=T.FONT_MONO,
            activestyle="none",
            yscrollcommand=log_scroll.set,
        )
        log_scroll.config(command=self.exec_log.yview)
        self.exec_log.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")
        self._append_exec_log("대기 — 경기 시작 시 실행 기록이 여기에 표시됩니다.")

        # ===== 우측: 버튼 부 + 차량정보 수정부 =====
        right = tk.Frame(root, bg=T.BG, width=380)
        right.grid(row=0, column=1, sticky="ns")
        right.grid_propagate(False)

        # --- 버튼 부 ---
        btn_section = tk.LabelFrame(
            right,
            text=" 버튼 부 ",
            bg="#E5E7EB",
            fg=T.MUTED,
            font=T.FONT_RANK,
            padx=8,
            pady=8,
            labelanchor="nw",
            relief="groove",
            bd=2,
        )
        btn_section.pack(fill="x", pady=(0, 12))

        self._gray_btn(btn_section, "경기 시작", self._start_race, fill=True, pady=(0, 8)).configure(
            font=("Segoe UI Semibold", 15), pady=10
        )

        lap_wrap = tk.Frame(btn_section, bg=T.BTN)
        lap_wrap.pack(fill="x", pady=4)
        tk.Label(lap_wrap, text="랩 수", bg=T.BTN, fg=T.BTN_FG, font=T.FONT_UI).pack(
            side="left", padx=8, pady=6
        )
        self.lap_var = tk.IntVar(value=1)
        lap_spin = tk.Spinbox(
            lap_wrap,
            from_=1,
            to=10,
            textvariable=self.lap_var,
            width=6,
            font=T.FONT_UI,
            command=self._on_lap_change,
        )
        lap_spin.pack(side="right", padx=8, pady=6)
        lap_spin.bind("<FocusOut>", lambda _e: self._on_lap_change())
        lap_spin.bind("<Return>", lambda _e: self._on_lap_change())

        sensor_wrap = tk.Frame(btn_section, bg=T.BTN)
        sensor_wrap.pack(fill="x", pady=6)
        tk.Label(
            sensor_wrap, text="센서 COM위치", bg=T.BTN, fg=T.BTN_FG, font=T.FONT_UI
        ).pack(anchor="w", padx=8, pady=(6, 0))
        sensor_line = tk.Frame(sensor_wrap, bg=T.BTN)
        sensor_line.pack(fill="x", padx=6, pady=6)
        self.com_var = tk.StringVar(value="")
        self.com_box = ttk.Combobox(sensor_line, textvariable=self.com_var, width=12)
        self.com_box.pack(side="left", fill="x", expand=True)
        tk.Button(
            sensor_line, text="↻", width=3, command=self._refresh_com_ports, bg=T.PANEL_DARK, fg="white"
        ).pack(side="left", padx=2)
        tk.Button(
            sensor_line, text="연결", command=self._connect_sensor, bg=T.PANEL_DARK, fg="white"
        ).pack(side="left", padx=2)
        # 초음파 랩/부정출발 계측 토글 (기본 OFF)
        self.ultrasonic_var = tk.BooleanVar(
            value=bool(self.engine.config.ultrasonic_enabled)
        )
        ultra_row = tk.Frame(sensor_wrap, bg=T.BTN)
        ultra_row.pack(fill="x", padx=8, pady=(0, 4))
        tk.Checkbutton(
            ultra_row,
            text="초음파 계측 사용",
            variable=self.ultrasonic_var,
            command=self._on_ultrasonic_toggle,
            bg=T.BTN,
            fg=T.BTN_FG,
            activebackground=T.BTN,
            activeforeground=T.BTN_FG,
            selectcolor=T.PANEL_DARK,
            font=T.FONT_UI,
            anchor="w",
        ).pack(side="left")
        self.sensor_status = tk.Label(
            sensor_wrap, text="센서: OFF", bg=T.BTN, fg="#D1D5DB", font=T.FONT_UI, anchor="w"
        )
        self.sensor_status.pack(fill="x", padx=8, pady=(0, 6))

        cam_row = tk.Frame(btn_section, bg="#E5E7EB")
        cam_row.pack(fill="x", pady=6)
        self.cam_var = tk.StringVar(value="0")
        ttk.Combobox(
            cam_row,
            textvariable=self.cam_var,
            values=["0", "1", "2", "3"],
            width=8,
            state="readonly",
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        self._gray_btn(cam_row, "카메라 연결", self._connect_camera).pack(
            side="left", fill="x", expand=True, padx=2
        )
        self._gray_btn(cam_row, "해제", self._disconnect_camera).pack(
            side="left", fill="x", expand=True, padx=(2, 0)
        )
        self.cam_status = tk.Label(
            btn_section, text="카메라: OFF", bg="#E5E7EB", fg=T.MUTED, font=T.FONT_UI, anchor="w"
        )
        self.cam_status.pack(fill="x", pady=(2, 4))

        # 수동 패널티 (Figma: 버튼 부)
        self._gray_btn(
            btn_section, "수동 패널티", self._open_manual_penalty, fill=True, pady=6
        )

        self._gray_btn(
            btn_section, "web에 기록 업로드", self._web_upload_records, fill=True, pady=6
        )
        tk.Button(
            btn_section,
            text="모든 기록 초기화",
            command=self._clear_all_records,
            bg="#DC2626",
            fg="#FFFFFF",
            activebackground="#B91C1C",
            activeforeground="#FFFFFF",
            relief="flat",
            font=T.FONT_BTN,
            cursor="hand2",
        ).pack(fill="x", pady=6)

        extra = tk.Frame(btn_section, bg="#E5E7EB")
        extra.pack(fill="x", pady=(4, 0))
        self._gray_btn(extra, "결승선 초기화", self._clear_finish_line).pack(
            side="left", fill="x", expand=True, padx=(0, 2)
        )
        self._gray_btn(extra, "서브모니터", self._open_sub_monitor).pack(
            side="left", fill="x", expand=True, padx=2
        )
        self._gray_btn(extra, "중단", self.engine.abort).pack(
            side="left", fill="x", expand=True, padx=(2, 0)
        )

        # --- 차량 정보 수정부 ---
        edit_section = tk.LabelFrame(
            right,
            text=" 차량 정보 수정부 ",
            bg="#F3F4F6",
            fg=T.MUTED,
            font=T.FONT_RANK,
            padx=8,
            pady=8,
            labelanchor="nw",
            relief="groove",
            bd=2,
        )
        edit_section.pack(fill="both", expand=True)

        vehicle = tk.Frame(
            edit_section, bg="#D1D5DB", highlightbackground="#9CA3AF", highlightthickness=1
        )
        vehicle.pack(fill="both", expand=True)

        header = tk.Frame(vehicle, bg=T.PANEL_DARK)
        header.pack(fill="x")
        for text, w in (("RC-ID", 8), ("학번", 12), ("이름", 12)):
            tk.Label(
                header, text=text, bg=T.PANEL_DARK, fg="white", font=T.FONT_UI, width=w
            ).pack(side="left", padx=3, pady=6)
        # RC-ID 숫자 = ArUco 마커 ID (예: RC-02 → 마커 2)

        self._row_vars.clear()
        existing = {p.rc_id: p for p in self.participants}
        # 마커 ID 0부터: RC-00 → marker 0, RC-01 → marker 1, …
        by_index = list(self.participants)
        for i in range(DEFAULT_LANES):
            rc_id = f"RC-{i:02d}"
            p = existing.get(rc_id) or (by_index[i] if i < len(by_index) else None)
            vars_row = {
                "rc_id": tk.StringVar(value=p.rc_id if p else rc_id),
                "student_id": tk.StringVar(value=p.student_id if p else ""),
                "name": tk.StringVar(value=p.name if p else ""),
            }
            self._row_vars.append(vars_row)
            line = tk.Frame(vehicle, bg=T.INPUT_BG)
            line.pack(fill="x", padx=4, pady=3)
            for key, w in (("rc_id", 8), ("student_id", 12), ("name", 12)):
                tk.Entry(
                    line,
                    textvariable=vars_row[key],
                    width=w,
                    justify="center",
                    bg=T.INPUT_BG,
                    fg=T.INPUT_FG,
                    insertbackground="white",
                    relief="flat",
                    font=T.FONT_UI,
                ).pack(side="left", padx=2, pady=4)

        self._gray_btn(vehicle, "업로드", self._upload_participants, fill=True, pady=8)
        tk.Label(
            edit_section,
            text="학번·이름 입력 후 업로드 · RC-ID 숫자=마커ID (RC-01→1)",
            bg="#F3F4F6",
            fg=T.MUTED,
            font=T.FONT_UI,
            anchor="w",
        ).pack(fill="x", pady=(6, 0))

        self.status_var = tk.StringVar(value="학번·이름 입력 → 업로드 → 결승선 설정 → 경기 시작")
        tk.Label(
            right,
            textvariable=self.status_var,
            bg=T.BG,
            fg=T.TEXT,
            font=T.FONT_UI,
            wraplength=360,
            justify="left",
            anchor="w",
        ).pack(fill="x", pady=(8, 0))

        self.phase_label = tk.Label(right, text="상태: 대기", bg=T.BG, fg=T.MUTED, anchor="w")
        self.phase_label.pack(fill="x")
        self.buzzer_label = tk.Label(right, text="부저: OFF", bg=T.BG, fg=T.MUTED, anchor="e")
        self.buzzer_label.pack(fill="x")

    # ----- 참가자 입력 -----
    def _collect_participants_from_form(self) -> list[Participant]:
        people: list[Participant] = []
        for i, row in enumerate(self._row_vars):
            rc_id = row["rc_id"].get().strip() or f"RC-{i:02d}"
            student_id = row["student_id"].get().strip()
            name = row["name"].get().strip()
            if not student_id and not name:
                continue
            if not student_id or not name:
                raise ValueError(f"{rc_id}: 학번과 이름을 모두 입력하세요.")
            # 마커 ID = RC-ID 숫자 (RC-01 → 1). 행 순서와 인쇄 마커가 다를 수 있음.
            digits = "".join(ch for ch in rc_id if ch.isdigit())
            marker_id = int(digits) if digits else i
            people.append(
                Participant(
                    rc_id=rc_id,
                    name=name,
                    student_id=student_id,
                    marker_id=marker_id,
                )
            )
        return people

    def _sync_marker_labels(self) -> None:
        labels = {p.marker_id: p.rc_id for p in self.participants}
        self.camera.set_marker_labels(labels)

    def _web_api_base(self) -> str:
        import os

        # apex(jijokrcrecord.kr)는 www 로 308 리다이렉트됨 → www 기본 사용
        base = os.environ.get("RCGLS_WEB_URL", "https://www.jijokrcrecord.kr").rstrip("/")
        if base in {"https://jijokrcrecord.kr", "http://jijokrcrecord.kr"}:
            base = "https://www.jijokrcrecord.kr"
        return base

    def _web_api_headers(self, with_json: bool = False) -> dict[str, str]:
        import os

        headers: dict[str, str] = {}
        if with_json:
            headers["Content-Type"] = "application/json; charset=utf-8"
        secret = os.environ.get("RCGLS_UPLOAD_SECRET", "").strip()
        if secret:
            headers["x-rcgls-upload-secret"] = secret
        return headers

    def _web_request(
        self,
        method: str,
        body: bytes | None = None,
        timeout: float = 12,
    ) -> dict:
        """web /api/records 호출. 실패 시 예외."""
        import json
        import urllib.error
        import urllib.request

        base = self._web_api_base()
        url = f"{base}/api/records"
        headers = self._web_api_headers(with_json=body is not None)

        class _MethodRedirectHandler(urllib.request.HTTPRedirectHandler):
            """308/307에서도 메서드·본문 유지."""

            def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N803
                m = req.get_method()
                if code in (301, 302, 303) and m != "GET":
                    m = "GET"
                    data = None
                else:
                    data = req.data
                return urllib.request.Request(
                    newurl,
                    data=data,
                    headers={k: v for k, v in req.headers.items()},
                    method=m,
                )

        opener = urllib.request.build_opener(_MethodRedirectHandler)
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with opener.open(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                detail = str(exc)
            raise RuntimeError(f"HTTP {exc.code}: {detail}\n대상: {url}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"웹 서버에 연결할 수 없습니다.\n대상: {url}\n{exc}"
            ) from exc

    def _web_upload_records(self) -> None:
        """Figma 웹 흐름: 전체 기록 → web API로 데이터 대입."""
        import json

        from ..storage import load_overall_records

        records = load_overall_records()
        if not records:
            messagebox.showwarning("web 업로드", "업로드할 기록이 없습니다.")
            return

        base = self._web_api_base()
        try:
            payload = self._web_request(
                "POST",
                body=json.dumps({"records": records}, ensure_ascii=False).encode("utf-8"),
            )
            count = payload.get("count", len(records))
            source = payload.get("source", "web")
            self.status_var.set(f"web 업로드 완료 ({count}건, {source}) → {base}")
            self._append_exec_log(f"web 기록 업로드 {count}건 ({source})")
            messagebox.showinfo(
                "web에 기록 업로드",
                f"{count}건을 웹에 반영했습니다.\n저장소: {source}\n{base}",
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("web 업로드 실패", str(exc))

    def _open_manual_penalty(self) -> None:
        if self.penalty_win is not None and self.penalty_win.winfo_exists():
            self.penalty_win.refresh_targets()
            self.penalty_win.lift()
            return
        self.penalty_win = ManualPenaltyWindow(
            self,
            self.engine,
            on_changed=lambda: self._append_exec_log("수동 패널티 UI에서 기록 갱신"),
        )

    def _upload_participants(self) -> None:
        try:
            people = self._collect_participants_from_form()
        except ValueError as exc:
            messagebox.showwarning("입력 오류", str(exc))
            return
        if not people:
            messagebox.showwarning("입력 오류", "최소 1명의 학번·이름을 입력하세요.")
            return
        save_participants(people)
        self.participants = people
        self.engine.set_participants(people)
        self._sync_marker_labels()
        msg = (
            f"업로드 완료 — {len(people)}명 저장 "
            f"(participants.json / participants.csv)"
        )
        self.status_var.set(msg)
        self._append_exec_log(msg)

    # ----- 센서 / 카메라 -----
    def _refresh_com_ports(self) -> None:
        ports = list_com_ports()
        self.com_box["values"] = ports
        if ports and self.com_var.get() not in ports:
            self.com_var.set(ports[0])

    def _on_ultrasonic_toggle(self) -> None:
        enabled = bool(self.ultrasonic_var.get())
        self.engine.set_ultrasonic_enabled(enabled)
        self._append_exec_log(f"초음파 계측 → {'ON' if enabled else 'OFF'}")

    def _connect_sensor(self) -> None:
        ok = self.hardware.connect(self.com_var.get().strip())
        state = self.hardware.snapshot()
        if ok:
            self.sensor_status.config(text=f"센서: ON ({state.port})", fg="#BBF7D0")
            self.status_var.set(f"센서 연결: {state.port}")
        else:
            self.sensor_status.config(text="센서: 실패", fg="#FECACA")
            messagebox.showwarning("센서", state.last_error or "COM 연결 실패")

    def _disconnect_sensor_ui(self) -> None:
        self.hardware.disconnect()
        self.sensor_status.config(text="센서: OFF", fg="#D1D5DB")

    def _connect_camera(self) -> None:
        idx = int(self.cam_var.get())
        self.camera.set_camera_index(idx)
        ok = self.camera.start()
        self.cam_status.config(
            text=f"카메라: {'ON' if ok else '실패'}",
            fg=T.OK if ok else T.ACCENT,
        )
        if not ok:
            messagebox.showwarning("카메라", f"카메라 {idx}를 열 수 없습니다.")

    def _disconnect_camera(self) -> None:
        self.camera.stop()
        self.cam_status.config(text="카메라: OFF", fg=T.MUTED)
        self.cam_canvas.delete("all")

    # ----- 가상 결승선 -----
    def _on_camera_click(self, event) -> None:
        if self._latest_frame is None:
            messagebox.showinfo("결승선", "먼저 카메라를 연결하세요.")
            return
        ox, oy = self._display_offset
        scale = self._display_scale or 1.0
        if scale <= 0:
            return
        fx = (event.x - ox) / scale
        fy = (event.y - oy) / scale
        h, w = self._latest_frame.shape[:2]
        if fx < 0 or fy < 0 or fx >= w or fy >= h:
            self.status_var.set("영상 영역 안을 클릭하세요.")
            return
        self.finish_line.add_point(fx, fy)
        n = len(self.finish_line.points)
        if n == 1:
            self.line_hint.config(text="결승선: 점 1 설정됨 — 두 번째 점을 클릭하세요")
            self._append_exec_log(f"결승선 점1 ({int(fx)},{int(fy)})")
        elif self.finish_line.ready:
            a, b = self.finish_line.points
            self.line_hint.config(
                text=f"결승선 설정 완료 ({a.x:.0f},{a.y:.0f})-({b.x:.0f},{b.y:.0f})"
            )
            self.status_var.set("가상 결승선 설정 완료")
            self._append_exec_log(
                f"가상 결승선 설정 ({int(a.x)},{int(a.y)})-({int(b.x)},{int(b.y)})"
            )
        # 즉시 다시 그려 점이 보이게
        self._show_frame(self._latest_frame)

    def _clear_all_records(self) -> None:
        if not messagebox.askyesno(
            "모든 기록 초기화",
            "로컬 + 웹(Supabase) 전체 기록을 모두 삭제합니다.\n"
            "이 작업은 되돌릴 수 없습니다.\n\n계속할까요?",
            parent=self,
        ):
            return
        try:
            clear_all_records()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("초기화 실패", str(exc), parent=self)
            return

        web_ok = False
        web_detail = ""
        try:
            import json

            # POST clear — DELETE는 구배포/일부 프록시에서 405
            payload = self._web_request(
                "POST",
                body=json.dumps({"clear": True}, ensure_ascii=False).encode("utf-8"),
            )
            if not payload.get("cleared") and payload.get("count", -1) != 0:
                # 구 API가 clear를 무시하고 빈 병합만 한 경우
                raise RuntimeError(
                    "웹 서버가 초기화(clear)를 지원하지 않습니다. "
                    "최신 web을 배포한 뒤 다시 시도하세요."
                )
            web_ok = True
            web_detail = str(payload.get("source", "web"))
            self._append_exec_log(f"web 기록 초기화 ({web_detail})")
        except Exception as exc:  # noqa: BLE001
            web_detail = str(exc)
            self._append_exec_log(f"web 기록 초기화 실패: {exc}")

        self.status_var.set(
            "모든 기록 초기화 완료"
            if web_ok
            else "로컬 초기화됨 · 웹 초기화 실패"
        )
        self._append_exec_log("로컬 모든 기록 초기화")
        try:
            if self.sub is not None and self.sub.winfo_exists():
                self.sub.refresh_history()
        except tk.TclError:
            self.sub = None

        if web_ok:
            messagebox.showinfo(
                "초기화 완료",
                f"로컬·웹 기록을 모두 비웠습니다.\n웹 저장소: {web_detail}",
                parent=self,
            )
        else:
            messagebox.showwarning(
                "부분 초기화",
                "로컬 기록은 비웠지만 웹 초기화에 실패했습니다.\n\n"
                f"{web_detail}\n\n"
                "원인: 배포된 웹에 초기화 API가 없거나(HTTP 405),\n"
                "RCGLS_UPLOAD_SECRET / 배포가 최신이 아닐 수 있습니다.\n"
                "web 폴더를 Vercel에 재배포한 뒤 다시 시도하세요.",
                parent=self,
            )

    def _clear_finish_line(self) -> None:
        self.finish_line.clear()
        self.line_hint.config(text="카메라 클릭 2점으로 가상 결승선 설정")
        self.status_var.set("결승선이 초기화되었습니다.")
        self._append_exec_log("가상 결승선 초기화")
        if self._latest_frame is not None:
            self._show_frame(self._latest_frame)

    # ----- 경기 -----
    def _read_lap_count(self) -> int:
        try:
            laps = int(self.lap_var.get())
        except (TypeError, ValueError, tk.TclError):
            laps = 1
        return max(1, min(10, laps))

    def _append_exec_log(self, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        line = f"[{stamp}] {message}"
        self.exec_log.insert("end", line)
        self.exec_log.see("end")
        # 과도한 적재 방지
        if self.exec_log.size() > 500:
            self.exec_log.delete(0, 100)

    def _clear_exec_log(self) -> None:
        self.exec_log.delete(0, "end")

    def _on_lap_change(self, *_args) -> None:
        laps = self._read_lap_count()
        self.lap_var.set(laps)
        self.engine.set_lap_count(laps)
        self._append_exec_log(f"랩 수 설정 → {laps}")

    def _start_race(self) -> None:
        try:
            people = self._collect_participants_from_form()
        except ValueError as exc:
            messagebox.showwarning("입력 오류", str(exc))
            return
        if people:
            self.participants = people
            self.engine.set_participants(people)
            self._sync_marker_labels()
        elif not self.participants:
            messagebox.showwarning("참가자", "학번/이름을 입력하고 업로드하세요.")
            return
        if not self.finish_line.ready:
            if not messagebox.askyesno(
                "결승선",
                "가상 결승선이 없습니다. 카메라에서 2점을 찍어 설정하는 것을 권장합니다.\n그래도 시작할까요?",
            ):
                return
        laps = self._read_lap_count()
        self._clear_exec_log()
        self._append_exec_log(f"경기 시작 요청 (목표 {laps}랩, 참가 {len(self.participants)}명)")
        # 경기마다 교차/정방향 이력 초기화 (이전 경기 역주행 락 잔존 방지)
        self.finish_line.reset_crossing_state()
        if self.finish_line.ready:
            self._append_exec_log("가상 결승선: 설정됨")
        else:
            self._append_exec_log("가상 결승선: 미설정")
        # 서브모니터를 닫아도 self.sub 참조가 남을 수 있음 → 존재 확인 후만 갱신
        # (실패해도 경기 시작은 반드시 진행)
        try:
            if self.sub is not None and self.sub.winfo_exists():
                self.sub.refresh_history()
            else:
                self.sub = None
        except tk.TclError:
            self.sub = None
        self.engine.start_race(lap_count=laps)

    def _open_sub_monitor(self) -> None:
        try:
            alive = self.sub is not None and self.sub.winfo_exists()
        except tk.TclError:
            alive = False
            self.sub = None
        if not alive:
            self.sub = SubMonitor(self)
            self.sub.protocol("WM_DELETE_WINDOW", self._on_sub_closed)
        else:
            self.sub.lift()

    def _on_sub_closed(self) -> None:
        if self.sub is not None:
            try:
                self.sub.destroy()
            except tk.TclError:
                pass
        self.sub = None

    # ----- 콜백 -----
    def _on_status(self, message: str) -> None:
        def apply() -> None:
            self.status_var.set(message)
            self._append_exec_log(message)

        self.after(0, apply)

    def _on_phase(self, phase: RacePhase) -> None:
        label = PHASE_LABEL.get(phase, phase.name)

        def apply() -> None:
            self.phase_label.config(text=f"상태: {label}")
            self._append_exec_log(f"단계 변경 → {label}")

        self.after(0, apply)

    def _on_rank(self, rows: list[RankRow]) -> None:
        def apply() -> None:
            # 순위/랩 표는 서브모니터(현재 경기·랩 기록)에 표시
            try:
                if self.sub is not None and self.sub.winfo_exists():
                    self.sub.update_ranks(rows)
                    if self.engine.phase == RacePhase.FINISHED:
                        self.sub.refresh_history()
                else:
                    self.sub = None
            except tk.TclError:
                self.sub = None
            if self.engine.phase == RacePhase.FINISHED:
                ranked = [r for r in rows if r.rank > 0 and not r.disqualified]
                if ranked:
                    summary = ", ".join(
                        f"{r.rank}위 {r.name}({r.rc_id}) {r.total_label}"
                        for r in ranked[:3]
                    )
                    self._append_exec_log(f"최종 순위 — {summary}")

        self.after(0, apply)

    def _on_markers(self, markers: list[int]) -> None:
        for mid in markers:
            self.engine.on_marker_seen(mid)

    def _on_marker_poses(self, poses: list[tuple[int, float, float]]) -> None:
        for marker_id, cx, cy in poses:
            if self.finish_line.check_crossing(marker_id, cx, cy):
                self.engine.record_finish_line_pass(marker_id)

    def _on_camera_frame(self, frame: np.ndarray) -> None:
        self._latest_frame = frame.copy()
        h, w = frame.shape[:2]
        self._frame_size = (w, h)
        now = time.monotonic()
        if self._fps_t0 <= 0:
            self._fps_t0 = now
        self._fps_frames += 1
        elapsed = now - self._fps_t0
        if elapsed >= 0.5:
            self._fps_value = self._fps_frames / elapsed
            self._fps_frames = 0
            self._fps_t0 = now

    def _tick(self) -> None:
        state = self.hardware.snapshot()
        if state.connected:
            self.sensor_status.config(text=f"센서: ON ({state.port})", fg="#BBF7D0")
        self.buzzer_label.config(
            text=f"부저: {'ON' if state.buzzer_on else 'OFF'}",
            fg=T.BUZZER_ON if state.buzzer_on else T.MUTED,
        )
        if self._latest_frame is not None:
            self._show_frame(self._latest_frame)
            w, h = self._frame_size
            if w > 0 and h > 0:
                self.fps_label.config(text=f"{w} X {h}   FPS: {self._fps_value:.0f}")
            else:
                self.fps_label.config(text=f"--- X ---   FPS: {self._fps_value:.0f}")
        if self.sub and self.sub.winfo_exists():
            self.sub.update_hardware(state)
        self.after(80, self._tick)

    def _draw_finish_line_bgr(self, frame: np.ndarray) -> np.ndarray:
        """프레임(BGR)에 결승선 오버레이 — 축소 후에도 보이도록 굵기 보정."""
        drawn = frame.copy()
        if not self.finish_line.points:
            return drawn
        h, w = drawn.shape[:2]
        # 화면 축소 비율을 가정해 선/점 굵기 키움 (고해상도에서도 보이게)
        thick = max(3, int(round(min(h, w) / 240)))
        radius = max(8, thick * 2)
        for p in self.finish_line.points:
            cv2.circle(drawn, (int(p.x), int(p.y)), radius, (0, 255, 255), -1)
            cv2.circle(drawn, (int(p.x), int(p.y)), radius + 2, (0, 0, 0), 2)
        if self.finish_line.ready:
            a, b = self.finish_line.points
            cv2.line(
                drawn,
                (int(a.x), int(a.y)),
                (int(b.x), int(b.y)),
                (0, 0, 0),
                thick + 4,
            )
            cv2.line(
                drawn,
                (int(a.x), int(a.y)),
                (int(b.x), int(b.y)),
                (0, 0, 255),
                thick,
            )
        return drawn

    def _draw_finish_line_canvas(self) -> None:
        """메인 캔버스에 결승선을 화면 좌표로 직접 그림 (축소로 안 보이는 문제 방지)."""
        if not self.finish_line.points:
            return
        ox, oy = self._display_offset
        scale = self._display_scale or 1.0
        pts = []
        for p in self.finish_line.points:
            cx = ox + p.x * scale
            cy = oy + p.y * scale
            pts.append((cx, cy))
            r = 7
            self.cam_canvas.create_oval(
                cx - r, cy - r, cx + r, cy + r,
                fill="#FACC15", outline="#111827", width=2, tags=("finish_line",),
            )
        if len(pts) == 2:
            (x1, y1), (x2, y2) = pts
            self.cam_canvas.create_line(
                x1, y1, x2, y2, fill="#111827", width=6, tags=("finish_line",),
            )
            self.cam_canvas.create_line(
                x1, y1, x2, y2, fill="#EF4444", width=3, tags=("finish_line",),
            )

    def _show_frame(self, frame: np.ndarray) -> None:
        drawn = self._draw_finish_line_bgr(frame)

        cw = max(self.cam_canvas.winfo_width(), 1)
        ch = max(self.cam_canvas.winfo_height(), 1)
        h, w = drawn.shape[:2]
        scale = min(cw / w, ch / h)
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        resized = cv2.resize(drawn, (nw, nh))
        ok, buf = cv2.imencode(".png", resized)
        if not ok:
            return
        photo = tk.PhotoImage(data=buf.tobytes())
        self._photo_main = photo
        self._display_scale = scale
        self._display_offset = ((cw - nw) // 2, (ch - nh) // 2)
        self.cam_canvas.delete("all")
        self.cam_canvas.create_image(
            self._display_offset[0],
            self._display_offset[1],
            anchor="nw",
            image=photo,
        )
        self._draw_finish_line_canvas()
        try:
            if self.sub is not None and self.sub.winfo_exists():
                self.sub.update_camera_frame(drawn)
            else:
                self.sub = None
        except tk.TclError:
            self.sub = None

    def _on_close(self) -> None:
        self.engine.abort()
        self.camera.stop()
        self.hardware.disconnect()
        if self.sub and self.sub.winfo_exists():
            self.sub.destroy()
        self.destroy()


def run() -> None:
    app = MainMonitor()
    app.mainloop()
