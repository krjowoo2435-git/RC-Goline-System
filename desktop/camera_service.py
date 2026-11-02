from __future__ import annotations

import sys
import threading
from typing import Callable, Mapping, Optional

import cv2
import numpy as np

from detect_aruco_numbers import get_aruco_dict, get_detector

from .overlay import draw_marker_rc_labels


MarkerCallback = Callable[[list[int]], None]
MarkerPoseCallback = Callable[[list[tuple[int, float, float]]], None]
FrameCallback = Callable[[np.ndarray], None]

# Arducam B0332 (OV9281) — MJPG만 고FPS. YUY2는 ~10fps.
B0332_WIDTH = 1280
B0332_HEIGHT = 800
B0332_FPS = 120


class CameraService:
    def __init__(
        self,
        camera_index: int = 0,
        on_markers: Optional[MarkerCallback] = None,
        on_marker_poses: Optional[MarkerPoseCallback] = None,
        on_frame: Optional[FrameCallback] = None,
        width: int = B0332_WIDTH,
        height: int = B0332_HEIGHT,
        fps: int = B0332_FPS,
    ) -> None:
        self.camera_index = camera_index
        self.on_markers = on_markers
        self.on_marker_poses = on_marker_poses
        self.on_frame = on_frame
        self.target_width = width
        self.target_height = height
        self.target_fps = fps
        self.marker_labels: dict[int, str] = {}
        self._cap: Optional[cv2.VideoCapture] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self.connected = False
        self.actual_width = 0
        self.actual_height = 0
        self.actual_fps = 0.0
        self.last_frame: Optional[np.ndarray] = None
        self.last_markers: list[int] = []
        self.last_poses: list[tuple[int, float, float]] = []
        aruco_dict = get_aruco_dict(cv2.aruco.DICT_4X4_50)
        self._detector = get_detector(aruco_dict)

    def set_marker_labels(self, labels: Mapping[int, str]) -> None:
        self.marker_labels = dict(labels)

    def set_camera_index(self, index: int) -> None:
        was_running = self._running
        if was_running:
            self.stop()
        self.camera_index = index
        if was_running:
            self.start()

    @staticmethod
    def _open_capture(index: int) -> cv2.VideoCapture:
        # Windows DirectShow: MJPG/고FPS 협상에 유리 (MSMF 기본은 낮은 FPS로 떨어지는 경우 많음)
        if sys.platform.startswith("win"):
            cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
            if cap.isOpened():
                return cap
            cap.release()
        return cv2.VideoCapture(index)

    def _apply_b0332_profile(self, cap: cv2.VideoCapture) -> None:
        # FourCC → 해상도 → FPS 순서가 DSHOW에서 안정적
        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
        cap.set(cv2.CAP_PROP_FOURCC, fourcc)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(self.target_width))
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(self.target_height))
        cap.set(cv2.CAP_PROP_FPS, float(self.target_fps))
        # 결승선 타이밍용: 버퍼 최소화로 지연 감소
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:  # noqa: BLE001
            pass

    def _read_negotiated(self, cap: cv2.VideoCapture) -> None:
        self.actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        self.actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        self.actual_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)

    def negotiated_summary(self) -> str:
        w = self.actual_width or self.target_width
        h = self.actual_height or self.target_height
        fps = self.actual_fps if self.actual_fps > 0 else float(self.target_fps)
        return f"{w}x{h}@{fps:.0f} MJPG"

    def start(self) -> bool:
        # 읽기 실패로 루프만 죽은 경우 _running 잔존 → 재시작 가능하도록 정리
        if self._running and self._thread is not None and self._thread.is_alive():
            return True
        if self._running:
            self.stop()
        self._cap = self._open_capture(self.camera_index)
        if not self._cap.isOpened():
            self.connected = False
            self._cap.release()
            self._cap = None
            return False
        self._apply_b0332_profile(self._cap)
        self._read_negotiated(self._cap)
        self.connected = True
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self._thread = None
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self.connected = False
        self.actual_width = 0
        self.actual_height = 0
        self.actual_fps = 0.0

    def _loop(self) -> None:
        assert self._cap is not None
        try:
            while self._running:
                ok, frame = self._cap.read()
                if not ok:
                    break
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                corners, ids, _ = self._detector.detectMarkers(gray)
                markers = draw_marker_rc_labels(frame, corners, ids, self.marker_labels)
                poses: list[tuple[int, float, float]] = []
                if ids is not None:
                    for i, marker_id in enumerate(ids.flatten()):
                        pts = corners[i][0]
                        cx = float(pts[:, 0].mean())
                        cy = float(pts[:, 1].mean())
                        poses.append((int(marker_id), cx, cy))
                self.last_markers = markers
                self.last_poses = poses
                self.last_frame = frame
                if self.on_markers and markers:
                    self.on_markers(markers)
                if self.on_marker_poses and poses:
                    self.on_marker_poses(poses)
                if self.on_frame:
                    self.on_frame(frame)
        finally:
            # 프레임 실패·정상 종료 모두: 재연결을 위해 실행 플래그 해제
            self._running = False
            self.connected = False
            if self._cap is not None:
                self._cap.release()
                self._cap = None
