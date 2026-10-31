from __future__ import annotations

import threading
from typing import Callable, Mapping, Optional

import cv2
import numpy as np

from detect_aruco_numbers import get_aruco_dict, get_detector

from .overlay import draw_marker_rc_labels


MarkerCallback = Callable[[list[int]], None]
MarkerPoseCallback = Callable[[list[tuple[int, float, float]]], None]
FrameCallback = Callable[[np.ndarray], None]


class CameraService:
    def __init__(
        self,
        camera_index: int = 0,
        on_markers: Optional[MarkerCallback] = None,
        on_marker_poses: Optional[MarkerPoseCallback] = None,
        on_frame: Optional[FrameCallback] = None,
    ) -> None:
        self.camera_index = camera_index
        self.on_markers = on_markers
        self.on_marker_poses = on_marker_poses
        self.on_frame = on_frame
        self.marker_labels: dict[int, str] = {}
        self._cap: Optional[cv2.VideoCapture] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self.connected = False
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

    def start(self) -> bool:
        # 읽기 실패로 루프만 죽은 경우 _running 잔존 → 재시작 가능하도록 정리
        if self._running and self._thread is not None and self._thread.is_alive():
            return True
        if self._running:
            self.stop()
        self._cap = cv2.VideoCapture(self.camera_index)
        if not self._cap.isOpened():
            self.connected = False
            self._cap.release()
            self._cap = None
            return False
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
