import csv, json, time, threading
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox
import cv2
from PIL import Image, ImageTk

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "cars.json"
PARTICIPANTS_CONFIG = HERE / "participants.json"
TARGET_WIDTH = 1920
TARGET_HEIGHT = 1080
TARGET_FPS = 120
GUI_INTERVAL_MS = 8  # 약 120Hz를 목표로 요청하되, 실제 Tkinter 갱신률은 PC 성능에 따라 달라짐

DEFAULT_CARS = {
    "0":{"car_id":"RC-01"}, 
    "1":{"car_id":"RC-02"}, 
    "2":{"car_id":"RC-03"},
    "3":{"car_id":"RC-04"}
}
if not CONFIG.exists():
    CONFIG.write_text(json.dumps(DEFAULT_CARS, ensure_ascii=False, indent=2), encoding="utf-8")
cars = {
    int(k): v["car_id"]
    for k, v in json.loads(
        CONFIG.read_text(encoding="utf-8")
    ).items()
}
if not PARTICIPANTS_CONFIG.exists():
    PARTICIPANTS_CONFIG.write_text("{}", encoding="utf-8")
try:
    participants = {int(k): v for k, v in json.loads(PARTICIPANTS_CONFIG.read_text(encoding="utf-8")).items()}
except (ValueError, json.JSONDecodeError):
    participants = {}
for marker_id, car_name in cars.items():
    participants.setdefault(marker_id, {"car_id": car_name, "student_num": "", "name": ""})

class App:
    def __init__(self, root):
        self.root = root
        root.title("RC카 결승선 기록 시스템")
        root.geometry("1320x800")
        root.minsize(1050, 650)
        self.cap = None
        self.frame = None
        self.capture_thread = None
        self.capture_stop = threading.Event()
        self.frame_lock = threading.Lock()
        self.latest_frame = None
        self.capture_fps = 0.0
        self.display_fps = 0.0
        self.detect_fps = 0.0
        self._display_count = 0
        self._display_fps_start = time.perf_counter()
        self._detect_count = 0
        self._detect_fps_start = time.perf_counter()
        self.scale = 1
        self.offset = (0, 0)
        self.line = None
        self.clicks = []
        self.prev = {}
        self.racing = False
        self.start_time = 0
        self.last_crossing = {}
        self.lap_counts = {mid: 0 for mid in cars}
        self.last_lap = {}
        self.total_elapsed = {}
        self.results = []
        self.lap_limit = 3
        self.cam = tk.IntVar(value=0)
        self.student_num_var = tk.StringVar()
        self.student_name_var = tk.StringVar()
        self.selected_marker_var = tk.StringVar(value=str(min(cars) if cars else 0))
        self.record_window = None
        self.record_tree = None

        if not hasattr(cv2, "aruco"):
            messagebox.showerror("OpenCV 오류", "ArUco 기능이 없습니다. python -m pip install opencv-contrib-python 을 실행하세요.")
            root.destroy()
            return
        dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        self.detector = cv2.aruco.ArucoDetector(dictionary, cv2.aruco.DetectorParameters())

        # 전체 화면: 위쪽은 카메라와 제어/차량 등록, 아래쪽은 프로그램 실행 기록
        body = ttk.Frame(root, padding=10)
        body.pack(fill="both", expand=True)
        upper = ttk.Frame(body)
        upper.pack(fill="both", expand=True)
        left = ttk.Frame(upper)
        left.pack(side="left", fill="both", expand=True)
        right = ttk.Frame(upper, width=340)
        right.pack(side="right", fill="y", padx=(10, 0))
        right.pack_propagate(False)

        ttk.Label(left, text="메인 화면 · 카메라 / 가상 골라인", font=("맑은 고딕", 12, "bold")).pack(anchor="w")
        self.view = ttk.Label(left, text="카메라를 연결하세요", anchor="center", relief="sunken")
        self.view.pack(fill="both", expand=True, pady=(6, 2))
        self.camera_info = ttk.Label(left, text=f"목표: {TARGET_WIDTH} × {TARGET_HEIGHT} @ {TARGET_FPS} FPS", anchor="w")
        self.camera_info.pack(fill="x", pady=(0, 3))
        self.view.bind("<Button-1>", self.click_video)

        # 오른쪽 제어부는 스케치처럼 위에서부터 시작/카메라/설정, 선수 등록 순서
        ttk.Button(right, text="경기 시작", command=self.start).pack(fill="x", pady=(0, 4))
        ttk.Button(right, text="카메라 연결 / 전환", command=self.connect).pack(fill="x", pady=2)
        ttk.Button(right, text="설정", command=self.open_settings).pack(fill="x", pady=2)
        ttk.Button(right, text="기록 화면 열기", command=self.open_records).pack(fill="x", pady=2)
        ttk.Separator(right).pack(fill="x", pady=7)

        camrow = ttk.Frame(right)
        camrow.pack(fill="x", pady=2)
        ttk.Label(camrow, text="카메라 번호").pack(side="left")
        ttk.Spinbox(camrow, from_=0, to=5, width=5, textvariable=self.cam).pack(side="right")
        ttk.Button(right, text="가상 골라인 초기화", command=self.reset_line).pack(fill="x", pady=2)
        self.line_status = tk.StringVar(value="결승선: 미설정 · 영상에서 두 점을 클릭하세요")
        ttk.Label(right, textvariable=self.line_status, wraplength=320).pack(fill="x", pady=3)

        ttk.Separator(right).pack(fill="x", pady=7)
        ttk.Label(right, text="차량 / 선수 등록", font=("맑은 고딕", 11, "bold")).pack(anchor="w")
        ttk.Label(right, text="차량 ID").pack(anchor="w", pady=(4, 0))
        self.roster_tree = ttk.Treeview(right, columns=("id", "student", "name"), show="headings", height=4)
        for col, title, width in [("id", "ID", 75), ("student", "학번", 90), ("name", "이름", 100)]:
            self.roster_tree.heading(col, text=title)
            self.roster_tree.column(col, width=width, anchor="center")
        self.roster_tree.pack(fill="x", pady=(2, 4))
        self.roster_tree.bind("<<TreeviewSelect>>", self.select_roster_row)
        form = ttk.Frame(right)
        form.pack(fill="x")
        ttk.Label(form, text="차량").grid(row=0, column=0, sticky="w", padx=(0, 5), pady=2)
        self.car_select = ttk.Combobox(form, state="readonly", width=10, values=[f"{mid}: {name}" for mid, name in sorted(cars.items())])
        if cars:
            self.car_select.current(0)
        self.car_select.grid(row=0, column=1, sticky="ew", pady=2)
        ttk.Label(form, text="학번").grid(row=1, column=0, sticky="w", padx=(0, 5), pady=2)
        ttk.Entry(form, textvariable=self.student_num_var).grid(row=1, column=1, sticky="ew", pady=2)
        ttk.Label(form, text="이름").grid(row=2, column=0, sticky="w", padx=(0, 5), pady=2)
        ttk.Entry(form, textvariable=self.student_name_var).grid(row=2, column=1, sticky="ew", pady=2)
        form.columnconfigure(1, weight=1)
        ttk.Button(right, text="업로드 / 저장", command=self.save_participant).pack(fill="x", pady=(4, 2))
        ttk.Separator(right).pack(fill="x", pady=7)
        self.status = tk.StringVar(value="대기 중")
        ttk.Label(right, text="경기 상태", font=("맑은 고딕", 10, "bold")).pack(anchor="w")
        ttk.Label(right, textvariable=self.status, wraplength=320).pack(fill="x", pady=(2, 3))
        self.detected = tk.StringVar(value="인식 확인: 마커 미검출")
        ttk.Label(right, textvariable=self.detected, foreground="#176B37", wraplength=320).pack(fill="x", pady=2)
        controls = ttk.Frame(right)
        controls.pack(fill="x", pady=(5, 2))
        ttk.Button(controls, text="경기 종료", command=self.stop).pack(side="left", fill="x", expand=True, padx=(0, 2))
        ttk.Button(controls, text="기록 초기화", command=self.clear).pack(side="left", fill="x", expand=True, padx=(2, 0))
        ttk.Button(right, text="결과 CSV 저장", command=self.save).pack(fill="x", pady=2)

        lower = ttk.LabelFrame(body, text="프로그램 실행 기록", padding=5)
        lower.pack(fill="x", expand=False, pady=(8, 0))
        self.log = ttk.Treeview(lower, columns=("time", "car", "lap", "lap_time", "message"), show="headings", height=5)
        for col, title, width in [("time", "경과 시간(s)", 105), ("car", "차량 ID", 100), ("lap", "랩", 60), ("lap_time", "랩타임(s)", 105), ("message", "이벤트", 600)]:
            self.log.heading(col, text=title)
            self.log.column(col, width=width, anchor="center" if col != "message" else "w")
        self.log.pack(fill="both", expand=True)

        self.refresh_roster()
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.tick()

    def log_event(self, message, elapsed=None, car="—", lap="—", lap_time="—"):
        if not hasattr(self, "log"):
            return
        if elapsed is None:
            elapsed = max(0.0, time.perf_counter() - self.start_time) if self.start_time else 0.0
        self.log.insert("", "end", values=(f"{elapsed:.3f}", car, lap, lap_time, message))
        children = self.log.get_children()
        if children:
            self.log.see(children[-1])

    def refresh_roster(self):
        if not hasattr(self, "roster_tree"):
            return
        for item in self.roster_tree.get_children():
            self.roster_tree.delete(item)
        for mid, car_name in sorted(cars.items()):
            info = participants.get(mid, {})
            self.roster_tree.insert("", "end", iid=str(mid), values=(car_name, info.get("student_num", ""), info.get("name", "")))

    def select_roster_row(self, _event=None):
        selected = self.roster_tree.selection()
        if not selected:
            return
        marker_id = int(selected[0])
        for i, mid in enumerate(sorted(cars)):
            if mid == marker_id:
                self.car_select.current(i)
                break
        info = participants.get(marker_id, {})
        self.student_num_var.set(info.get("student_num", ""))
        self.student_name_var.set(info.get("name", ""))

    def save_participant(self):
        selection = self.car_select.get()
        if not selection:
            messagebox.showwarning("차량 선택", "등록할 차량을 선택하세요.")
            return
        try:
            marker_id = int(selection.split(":", 1)[0])
        except ValueError:
            messagebox.showerror("차량 오류", "차량 목록을 다시 선택하세요.")
            return
        participants[marker_id] = {"car_id": cars[marker_id], "student_num": self.student_num_var.get().strip(), "name": self.student_name_var.get().strip()}
        PARTICIPANTS_CONFIG.write_text(json.dumps({str(k): v for k, v in participants.items()}, ensure_ascii=False, indent=2), encoding="utf-8")
        self.refresh_roster()
        if self.record_window and self.record_window.winfo_exists():
            self.refresh_records_window()
        self.log_event(f"선수 등록 저장: {cars[marker_id]}", car=cars[marker_id])
        self.status.set(f"{cars[marker_id]} 선수 정보 저장됨")

    def open_settings(self):
        win = tk.Toplevel(self.root)
        win.title("설정")
        win.geometry("320x150")
        win.transient(self.root)
        frame = ttk.Frame(win, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="랩 수 (최대 3)").pack(anchor="w", pady=(0, 8))
        lap_var = tk.IntVar(value=self.lap_limit)
        ttk.Combobox(frame, state="readonly", values=(1, 2, 3), textvariable=lap_var, width=8).pack(anchor="w")
        def apply_settings():
            self.lap_limit = int(lap_var.get())
            self.log_event(f"설정 변경: {self.lap_limit}랩 경기")
            win.destroy()
        ttk.Button(frame, text="적용", command=apply_settings).pack(fill="x", pady=(14, 0))

    def open_records(self):
        if self.record_window and self.record_window.winfo_exists():
            self.record_window.deiconify()
            self.record_window.lift()
            return
        win = tk.Toplevel(self.root)
        self.record_window = win
        win.title("기록 표시")
        win.geometry("1050x480")
        frame = ttk.Frame(win, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="경기 기록", font=("맑은 고딕", 13, "bold")).pack(anchor="w", pady=(0, 8))
        columns = ("id", "student", "name") + tuple(f"lap{i}" for i in range(1, self.lap_limit + 1)) + ("elapsed",)
        self.record_tree = ttk.Treeview(frame, columns=columns, show="headings")
        labels = [("id", "ID", 100), ("student", "학번", 100), ("name", "이름", 120)]
        labels += [(f"lap{i}", f"{i}랩 시간", 120) for i in range(1, self.lap_limit + 1)]
        labels += [("elapsed", "경기 시작 후 소요 시간 (mm:ss:ms)", 220)]
        for col, label, width in labels:
            self.record_tree.heading(col, text=label)
            self.record_tree.column(col, width=width, anchor="center")
        self.record_tree.pack(fill="both", expand=True)
        ttk.Button(frame, text="CSV 저장", command=self.save).pack(anchor="e", pady=(8, 0))
        self.refresh_records_window()

    def refresh_records_window(self):
        if not self.record_tree or not self.record_window or not self.record_window.winfo_exists():
            return
        old = self.record_tree
        for item in old.get_children():
            old.delete(item)
        for mid, car_name in sorted(cars.items()):
            info = participants.get(mid, {})
            times = {int(r["lap"]): r for r in self.results if r["marker_id"] == mid}
            values = [car_name, info.get("student_num", ""), info.get("name", "")]
            for lap in range(1, self.lap_limit + 1):
                values.append(f'{times[lap]["lap_time_seconds"]:.3f}' if lap in times else "—")
            elapsed = max((r["elapsed_seconds"] for r in self.results if r["marker_id"] == mid), default=None)
            values.append(self.format_elapsed(elapsed) if elapsed is not None else "—")
            old.insert("", "end", values=values)

    @staticmethod
    def format_elapsed(seconds):
        if seconds is None:
            return "—"
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        millis = int((seconds - int(seconds)) * 1000)
        return f"{minutes:02d}:{secs:02d}:{millis:03d}"

    def connect(self):
        self.disconnect_camera()
        index=self.cam.get()

        # Windows 카메라 백엔드를 순서대로 시도하고, 실제 프레임 수신까지 확인
        backends=[]
        if hasattr(cv2,"CAP_DSHOW"):
            backends.append(("DirectShow",cv2.CAP_DSHOW))
        if hasattr(cv2,"CAP_MSMF"):
            backends.append(("Media Foundation",cv2.CAP_MSMF))
        backends.append(("기본",cv2.CAP_ANY))

        cap=None
        backend_name=""
        test_frame=None
        for name,backend in backends:
            candidate=cv2.VideoCapture(index,backend)
            if candidate.isOpened():
                # 카메라에 1080p / 120FPS를 요청한다.
                # 지원하지 않는 카메라는 요청값과 다른 모드로 열릴 수 있으므로
                # 실제 수신 해상도와 FPS를 아래 상태 표시에서 확인한다.
                candidate.set(cv2.CAP_PROP_FRAME_WIDTH, TARGET_WIDTH)
                candidate.set(cv2.CAP_PROP_FRAME_HEIGHT, TARGET_HEIGHT)
                candidate.set(cv2.CAP_PROP_FPS, TARGET_FPS)
                try:
                    candidate.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                except Exception:
                    pass
                ok,frame=candidate.read()
                if ok and frame is not None:
                    cap=candidate
                    backend_name=name
                    test_frame=frame
                    break
                candidate.release()

        if cap is None:
            self.status.set("카메라 연결 실패")
            messagebox.showerror("카메라 오류","카메라에서 프레임을 읽을 수 없습니다. 다른 앱에서 사용 중인지 확인하세요.")
            return

        self.cap=cap
        self.capture_stop=threading.Event()
        stop_event=self.capture_stop
        with self.frame_lock:
            self.latest_frame=test_frame
        self.capture_fps=0.0
        self.capture_thread=threading.Thread(
            target=self.capture_loop,args=(cap,stop_event),daemon=True,name="RC-camera"
        )
        self.capture_thread.start()
        h,w=test_frame.shape[:2]
        actual_fps = cap.get(cv2.CAP_PROP_FPS)
        self.status.set(
            f"카메라 {index} 연결됨 ({backend_name}, {w}×{h}, 설정 FPS {actual_fps:.1f}) · 결승선 설정 필요"
        )
        self.log_event(f"카메라 연결: {w}×{h}, 설정 FPS {actual_fps:.1f}")

    def capture_loop(self,cap,stop_event):
        count=0
        started=time.perf_counter()
        while not stop_event.is_set():
            ok,frame=cap.read()
            if stop_event.is_set():
                break
            if not ok or frame is None:
                time.sleep(0.01)
                continue
            with self.frame_lock:
                self.latest_frame=frame
            count+=1
            now=time.perf_counter()
            if now-started>=1.0:
                self.capture_fps=count/(now-started)
                count=0
                started=now

    def disconnect_camera(self):
        self.capture_stop.set()
        cap=self.cap
        self.cap=None
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass
        thread=self.capture_thread
        self.capture_thread=None
        if thread is not None and thread.is_alive():
            thread.join(timeout=0.3)
        with self.frame_lock:
            self.latest_frame=None

    def click_video(self,e):
        if self.frame is None: return
        x=e.x-self.offset[0]
        y=e.y-self.offset[1]
        w=int(self.frame.shape[1]*self.scale)
        h=int(self.frame.shape[0]*self.scale)
        if not (0<=x<w and 0<=y<h): return
        self.clicks.append((int(x/self.scale),int(y/self.scale)))
        if len(self.clicks)==2:
            self.line=(self.clicks[0],self.clicks[1])
            self.clicks=[]
            self.prev.clear()
            self.line_status.set(f"결승선 설정됨: {self.line[0]} → {self.line[1]}")

    def reset_line(self):
        self.line=None
        self.clicks=[]
        self.prev.clear()
        self.line_status.set("결승선: 미설정 · 영상에서 두 점을 클릭하세요")
        self.log_event("가상 골라인 초기화")

    def start(self):
        if self.cap is None or self.line is None:
            messagebox.showwarning("설정 필요","카메라를 연결하고 영상에서 결승선 양 끝을 클릭하세요.")
            return
        self.prev.clear()
        self.last_crossing.clear()
        self.lap_counts={mid:0 for mid in cars}
        self.last_lap={}
        self.total_elapsed={}
        self.results=[]
        for item in self.log.get_children():
            self.log.delete(item)
        self.start_time=time.perf_counter()
        self.racing=True
        self.status.set(f"경기 진행 중 · {self.lap_limit}랩 기록 중")
        self.log_event(f"경기 시작: {self.lap_limit}랩 설정")
        self.refresh_records_window()

    def stop(self):
        self.racing=False
        self.status.set("경기 종료 · 결과를 저장할 수 있습니다")
        self.log_event("경기 종료")
        self.refresh_records_window()

    def clear(self):
        if self.racing:
            messagebox.showwarning("경기 진행 중","먼저 경기를 종료하세요.")
            return
        self.results=[]
        self.lap_counts={mid:0 for mid in cars}
        self.last_lap={}
        self.total_elapsed={}
        self.prev.clear()
        for item in self.log.get_children():
            self.log.delete(item)
        self.status.set("기록 초기화됨")
        self.log_event("기록 초기화")
        self.refresh_records_window()

    @staticmethod
    def side(p,a,b): return (b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0])

    def crossing(self,p,q,a,b):
        s1=self.side(p,a,b)
        s2=self.side(q,a,b)
        if s1==0 or s2==0 or (s1>0)==(s2>0): return None
        frac=abs(s1)/(abs(s1)+abs(s2))
        x=p[0]+frac*(q[0]-p[0])
        y=p[1]+frac*(q[1]-p[1])
        dx=b[0]-a[0]
        dy=b[1]-a[1]
        den=dx*dx+dy*dy
        if den==0: return None
        t=((x-a[0])*dx+(y-a[1])*dy)/den
        return frac if -0.03<=t<=1.03 else None

    def refresh_table(self, visible):
        # 기존 내부 호출과의 호환성을 유지한다. 현재 GUI는 별도 기록 창에 결과를 표시한다.
        self.refresh_records_window()

    def tick(self):
        if self.cap is not None:
            with self.frame_lock:
                frame=self.latest_frame.copy() if self.latest_frame is not None else None

            if frame is not None:
                now=time.perf_counter()
                h,w=frame.shape[:2]

                self._display_count+=1
                display_elapsed=now-self._display_fps_start
                if display_elapsed>=1.0:
                    self.display_fps=self._display_count/display_elapsed
                    self._display_count=0
                    self._display_fps_start=now

                self.frame=frame.copy()
                visible=set()

                # ArUco 검출은 축소 영상에서 수행하고 좌표를 원본 해상도로 환산
                detect_scale=0.75
                small=cv2.resize(
                    frame,(max(1,int(w*detect_scale)),max(1,int(h*detect_scale))),
                    interpolation=cv2.INTER_AREA
                )
                gray=cv2.cvtColor(small,cv2.COLOR_BGR2GRAY)
                detect_start=time.perf_counter()
                corners,ids,_=self.detector.detectMarkers(gray)
                detect_elapsed=time.perf_counter()-detect_start
                self._detect_count+=1
                detect_now=time.perf_counter()
                fps_elapsed=detect_now-self._detect_fps_start
                if fps_elapsed>=1.0:
                    self.detect_fps=self._detect_count/fps_elapsed
                    self._detect_count=0
                    self._detect_fps_start=detect_now

                if ids is not None:
                    scale_back=1.0/detect_scale
                    for i,raw in enumerate(ids.flatten()):
                        pts=corners[i][0]*scale_back
                        mid=int(raw)
                        center=tuple(map(int,pts.mean(axis=0)))
                        visible.add(mid)
                        name=cars.get(mid,f"Unknown-{mid}")
                        cv2.polylines(frame,[pts.astype("int32")],True,(0,255,0),2)
                        cv2.circle(frame,center,5,(0,255,0),-1)
                        cv2.putText(frame,f"{name} / ID {mid}",(center[0]+8,center[1]-8),
                                    cv2.FONT_HERSHEY_SIMPLEX,.55,(0,255,0),2)

                        if self.racing and self.line and mid in self.prev:
                            prev,prev_time=self.prev[mid]
                            frac=self.crossing(prev,center,*self.line)
                            if frac is not None:
                                crossing_time=prev_time+frac*(now-prev_time)
                                if crossing_time-self.last_crossing.get(mid,-1e9)>=1.0:
                                    elapsed=max(0.0,crossing_time-self.start_time)
                                    lap=self.lap_counts.get(mid,0)+1
                                    if lap <= self.lap_limit:
                                        lap_time=elapsed if lap==1 else elapsed-self.total_elapsed.get(mid,0.0)
                                        self.lap_counts[mid]=lap
                                        self.last_lap[mid]=lap_time
                                        self.total_elapsed[mid]=elapsed
                                        self.last_crossing[mid]=crossing_time
                                        info=participants.get(mid,{})
                                        row={"car_id":name,"marker_id":mid,
                                             "student_num":info.get("student_num",""),"name":info.get("name",""),
                                             "lap":lap,"elapsed_seconds":elapsed,"lap_time_seconds":lap_time,
                                             "recorded_at":datetime.now().isoformat(timespec="seconds")}
                                        self.results.append(row)
                                        self.log_event("결승선 통과", elapsed, name, lap, f"{lap_time:.3f}")
                                        self.status.set(f"{name} · {lap}랩 · 랩타임 {lap_time:.3f}초")
                                        self.refresh_records_window()
                        self.prev[mid]=(center,now)

                if self.line:
                    cv2.line(frame,*self.line,(0,0,255),3)
                    cv2.circle(frame,self.line[0],5,(255,0,0),-1)
                    cv2.circle(frame,self.line[1],5,(255,0,0),-1)
                for point in self.clicks:
                    cv2.circle(frame,point,6,(0,255,255),-1)

                names=[cars.get(mid,f"ID-{mid}") for mid in sorted(visible)]
                self.detected.set("인식 확인: "+(", ".join(names) if names else "마커 미검출"))
                self.refresh_table(visible)
                self.camera_info.configure(
                    text=f"해상도: {w} × {h}    수신: {self.capture_fps:.1f} FPS    "
                         f"표시: {self.display_fps:.1f} FPS    검출: {self.detect_fps:.1f} FPS"
                )
                self.show(frame)
            else:
                self.camera_info.configure(text="카메라 프레임 수신 대기 중...")
        else:
            self.view.configure(text="  카메라가 연결되지 않았습니다.\\n'카메라 연결/재연결'을 누르세요.",image="")

        # 120FPS 목표: 약 8ms 간격으로 GUI 루프를 예약한다.
        # 실제 처리 속도는 카메라, ArUco 검출 시간, PC 성능에 의해 제한된다.
        self.root.after(GUI_INTERVAL_MS, self.tick)

    def show(self,frame):
        lw = max(self.view.winfo_width() - 4, 320)
        lh = max(self.view.winfo_height() - 4, 240)

        h, w = frame.shape[:2]
        self.scale = min(lw / w, lh / h)

        nw = max(1, int(w * self.scale))
        nh = max(1, int(h * self.scale))

        resized = cv2.resize(frame, (nw, nh))
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)

        photo = ImageTk.PhotoImage(Image.fromarray(rgb))
        self.view.configure(image=photo, text="")
        self.view.image = photo

        self.offset = (
            (self.view.winfo_width() - nw) // 2,
            (self.view.winfo_height() - nh) // 2
        )

    def save(self):
        if not self.results:
            messagebox.showinfo("기록 없음", "저장할 랩 기록이 없습니다.")
            return
        path = HERE / "results.csv"
        # 스케치에 맞춘 차량별 가로형 CSV: ID, 학번, 이름, 1lap_time ...
        fields = ["ID", "Student_num", "name"] + [f"{i}lap_time" for i in range(1, self.lap_limit + 1)] + ["elapsed_time"]
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for mid, car_name in sorted(cars.items()):
                info = participants.get(mid, {})
                rows = {int(r["lap"]): r for r in self.results if r["marker_id"] == mid}
                output = {"ID": car_name, "Student_num": info.get("student_num", ""), "name": info.get("name", "")}
                for lap in range(1, self.lap_limit + 1):
                    output[f"{lap}lap_time"] = f'{rows[lap]["lap_time_seconds"]:.3f}' if lap in rows else ""
                elapsed = max((r["elapsed_seconds"] for r in self.results if r["marker_id"] == mid), default=None)
                output["elapsed_time"] = self.format_elapsed(elapsed) if elapsed is not None else ""
                writer.writerow(output)
        self.log_event(f"CSV 저장 완료: {path.name}")
        messagebox.showinfo("저장 완료", f"랩 기록을 저장했습니다:\n{path}")

    def close(self):
        self.disconnect_camera()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()

    try:
        App(root)
        root.mainloop()
    except Exception as e:
        messagebox.showerror("실행 오류", str(e))
        raise