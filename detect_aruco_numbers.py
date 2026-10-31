"""
ArUco 마커 숫자 인식 예제
웹캠(또는 이미지 파일)에서 ArUco 마커를 찾고, 마커 ID를 숫자로 표시합니다.
ID 0~9 → 숫자 0~9

사용법:
  python detect_aruco_numbers.py              # 웹캠
  python detect_aruco_numbers.py image.png    # 이미지 파일
  q 키로 종료
"""

import sys

import cv2
import numpy as np


def get_aruco_dict(dict_name: int = cv2.aruco.DICT_4X4_50):
    if hasattr(cv2.aruco, "getPredefinedDictionary"):
        return cv2.aruco.getPredefinedDictionary(dict_name)
    return cv2.aruco.Dictionary_get(dict_name)


def get_detector(aruco_dict):
    """OpenCV 버전별 Detector 생성."""
    if hasattr(cv2.aruco, "ArucoDetector"):
        params = cv2.aruco.DetectorParameters()
        return cv2.aruco.ArucoDetector(aruco_dict, params)

    # 구버전: detectMarkers 직접 사용용 래퍼
    class LegacyDetector:
        def __init__(self, dictionary):
            self.dictionary = dictionary
            self.parameters = cv2.aruco.DetectorParameters_create()

        def detectMarkers(self, image):
            return cv2.aruco.detectMarkers(image, self.dictionary, parameters=self.parameters)

    return LegacyDetector(aruco_dict)


def draw_detections(frame: np.ndarray, corners, ids) -> list[int]:
    """검출된 마커를 그리고, 인식된 숫자 목록을 반환."""
    numbers: list[int] = []
    if ids is None:
        return numbers

    cv2.aruco.drawDetectedMarkers(frame, corners, ids)

    for i, marker_id in enumerate(ids.flatten()):
        number = int(marker_id)
        numbers.append(number)

        # 마커 중심 좌표
        pts = corners[i][0]
        cx = int(pts[:, 0].mean())
        cy = int(pts[:, 1].mean())

        # 큰 숫자 오버레이
        label = str(number)
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale, thickness = 2.0, 3
        (tw, th), _ = cv2.getTextSize(label, font, scale, thickness)
        cv2.rectangle(
            frame,
            (cx - tw // 2 - 8, cy - th - 8),
            (cx + tw // 2 + 8, cy + 12),
            (0, 0, 0),
            -1,
        )
        cv2.putText(
            frame,
            label,
            (cx - tw // 2, cy),
            font,
            scale,
            (0, 255, 0),
            thickness,
            cv2.LINE_AA,
        )

    return numbers


def process_frame(frame: np.ndarray, detector) -> np.ndarray:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    corners, ids, _rejected = detector.detectMarkers(gray)
    numbers = draw_detections(frame, corners, ids)

    status = f"Numbers: {numbers}" if numbers else "Numbers: (none)"
    cv2.putText(
        frame,
        status,
        (12, 36),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        (0, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return frame


def run_webcam(detector):
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("웹캠을 열 수 없습니다. 카메라 인덱스를 확인하세요.")
        return

    print("웹캠 인식 중... (종료: q)")
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame = process_frame(frame, detector)
        cv2.imshow("ArUco Number Detection", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


def run_image(path: str, detector):
    frame = cv2.imread(path)
    if frame is None:
        print(f"이미지를 읽을 수 없습니다: {path}")
        return

    frame = process_frame(frame, detector)
    print("인식 결과 창을 표시합니다. (종료: 아무 키)")
    cv2.imshow("ArUco Number Detection", frame)
    cv2.waitKey(0)
    cv2.destroyAllWindows()


def main():
    aruco_dict = get_aruco_dict(cv2.aruco.DICT_4X4_50)
    detector = get_detector(aruco_dict)

    if len(sys.argv) > 1:
        run_image(sys.argv[1], detector)
    else:
        run_webcam(detector)


if __name__ == "__main__":
    main()
