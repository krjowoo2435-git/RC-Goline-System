
import cv2
from pathlib import Path

output_dir = Path("markers")
output_dir.mkdir(exist_ok=True)

dictionary = cv2.aruco.getPredefinedDictionary(
    cv2.aruco.DICT_4X4_50
)

for marker_id in range(4):
    marker = cv2.aruco.generateImageMarker(
        dictionary,
        marker_id,
        600
    )

    filename = output_dir / f"marker_{marker_id}.png"
    cv2.imwrite(str(filename), marker)
    print(f"생성 완료: {filename}")