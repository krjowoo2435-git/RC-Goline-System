from __future__ import annotations

from typing import Mapping, Optional

import cv2
import numpy as np


def draw_marker_rc_labels(
    frame: np.ndarray,
    corners,
    ids,
    labels: Optional[Mapping[int, str]] = None,
) -> list[int]:
    """ArUco 인식 프레임 위에 배경 없이 RC-ID만 표시."""
    numbers: list[int] = []
    if ids is None:
        return numbers

    # 테두리만 (정보 박스 없음)
    cv2.aruco.drawDetectedMarkers(frame, corners, ids)

    for i, marker_id in enumerate(ids.flatten()):
        mid = int(marker_id)
        numbers.append(mid)
        pts = corners[i][0]
        cx = int(pts[:, 0].mean())
        cy = int(pts[:, 1].mean())

        label = (labels or {}).get(mid, f"RC-{mid:02d}")
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale, thickness = 1.2, 2
        (tw, th), _ = cv2.getTextSize(label, font, scale, thickness)
        # 배경 없이 텍스트만 (가독성용 얇은 외곽선)
        x = cx - tw // 2
        y = max(th + 4, cy - 12)
        cv2.putText(frame, label, (x, y), font, scale, (0, 0, 0), thickness + 2, cv2.LINE_AA)
        cv2.putText(frame, label, (x, y), font, scale, (0, 255, 0), thickness, cv2.LINE_AA)

    return numbers
