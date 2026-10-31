"""
ArUco 마커 생성기
숫자 0~9에 해당하는 마커 이미지를 markers/ 폴더에 저장합니다.
각 마커 ID = 숫자 값 (ID 0 → 숫자 0, ID 5 → 숫자 5)
"""

from pathlib import Path

import cv2
import numpy as np


# OpenCV 4.7+ / 구버전 모두 대응
def get_aruco_dict(dict_name: int = cv2.aruco.DICT_4X4_50):
    if hasattr(cv2.aruco, "getPredefinedDictionary"):
        return cv2.aruco.getPredefinedDictionary(dict_name)
    return cv2.aruco.Dictionary_get(dict_name)


def generate_marker(aruco_dict, marker_id: int, size_px: int = 400) -> np.ndarray:
    """단일 ArUco 마커 이미지 생성."""
    if hasattr(cv2.aruco, "generateImageMarker"):
        return cv2.aruco.generateImageMarker(aruco_dict, marker_id, size_px)

    # 구버전 OpenCV
    marker = np.zeros((size_px, size_px), dtype=np.uint8)
    cv2.aruco.drawMarker(aruco_dict, marker_id, size_px, marker, 1)
    return marker


def add_label(marker: np.ndarray, label: str) -> np.ndarray:
    """마커 아래에 숫자 라벨을 붙여 인쇄용으로 보기 좋게 만듭니다."""
    h, w = marker.shape[:2]
    labeled = np.ones((h + 60, w), dtype=np.uint8) * 255
    labeled[:h, :] = marker
    cv2.putText(
        labeled,
        label,
        (w // 2 - 20, h + 45),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.5,
        0,
        2,
        cv2.LINE_AA,
    )
    return labeled


def main():
    out_dir = Path("markers")
    out_dir.mkdir(exist_ok=True)

    aruco_dict = get_aruco_dict(cv2.aruco.DICT_4X4_50)
    size_px = 400

    print(f"마커 저장 경로: {out_dir.resolve()}")
    print("딕셔너리: DICT_4X4_50 (ID = 숫자)")

    for number in range(10):  # 0 ~ 9
        marker = generate_marker(aruco_dict, marker_id=number, size_px=size_px)
        labeled = add_label(marker, str(number))

        path = out_dir / f"number_{number}.png"
        cv2.imwrite(str(path), labeled)
        print(f"  생성: {path.name}  (ArUco ID={number})")

    # 한 장에 0~9 모두 배치 (인쇄용 시트)
    cols, rows = 5, 2
    cell = size_px + 80
    sheet = np.ones((rows * cell, cols * cell), dtype=np.uint8) * 255
    for number in range(10):
        r, c = divmod(number, cols)
        marker = generate_marker(aruco_dict, number, size_px)
        labeled = add_label(marker, str(number))
        y0, x0 = r * cell + 10, c * cell + 10
        sheet[y0 : y0 + labeled.shape[0], x0 : x0 + labeled.shape[1]] = labeled

    sheet_path = out_dir / "numbers_0_to_9_sheet.png"
    cv2.imwrite(str(sheet_path), sheet)
    print(f"  생성: {sheet_path.name}  (인쇄용 전체 시트)")
    print("완료.")


if __name__ == "__main__":
    main()
