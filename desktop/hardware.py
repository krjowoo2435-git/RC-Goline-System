from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

TriggerCallback = Callable[[int, float], None]  # sensor_index, distance_cm


@dataclass
class HardwareState:
    led_on: list[bool] = field(default_factory=lambda: [False, False, False])
    buzzer_on: bool = False
    distances_cm: list[float] = field(default_factory=lambda: [30.0, 30.0, 30.0])
    threshold_cm: float = 15.0
    connected: bool = False
    port: str = ""
    last_error: str = ""


def list_com_ports() -> list[str]:
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [p.device for p in list_ports.comports()]


class HardwareController:
    """아두이노 초음파/LED/부저 — COM 시리얼 연결 + 시뮬레이터.

    수신 프로토콜(한 줄):
      D,12.5,13.0,14.2
      DIST,12.5,13.0,14.2
    송신:
      LED,1,1,0
      BUZZ,200
    """

    def __init__(self, on_pass: Optional[TriggerCallback] = None) -> None:
        self.state = HardwareState()
        self.on_pass = on_pass
        self._armed = [True, True, True]
        self._lock = threading.Lock()
        self._ser = None
        self._reader: Optional[threading.Thread] = None
        self._running = False

    def connect(self, port: str, baudrate: int = 115200) -> bool:
        self.disconnect()
        port = (port or "").strip()
        if not port:
            with self._lock:
                self.state.last_error = "COM 포트를 선택하세요."
                self.state.connected = False
            return False
        try:
            import serial
        except ImportError as exc:
            with self._lock:
                self.state.last_error = f"pyserial 미설치: {exc}"
                self.state.connected = False
            return False

        try:
            ser = serial.Serial(port, baudrate=baudrate, timeout=0.05)
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self.state.last_error = str(exc)
                self.state.connected = False
                self.state.port = port
            return False

        with self._lock:
            self._ser = ser
            self.state.connected = True
            self.state.port = port
            self.state.last_error = ""
        self._running = True
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        return True

    def disconnect(self) -> None:
        self._running = False
        if self._reader and self._reader.is_alive():
            self._reader.join(timeout=1.0)
        self._reader = None
        with self._lock:
            if self._ser is not None:
                try:
                    self._ser.close()
                except Exception:  # noqa: BLE001
                    pass
                self._ser = None
            self.state.connected = False

    def _write_line(self, line: str) -> None:
        with self._lock:
            ser = self._ser
            connected = self.state.connected
        if not connected or ser is None:
            return
        try:
            ser.write((line.strip() + "\n").encode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self.state.last_error = str(exc)
                self.state.connected = False

    def set_leds(self, pattern: list[bool]) -> None:
        with self._lock:
            self.state.led_on = list(pattern[:3]) + [False] * max(0, 3 - len(pattern))
            bits = self.state.led_on
        self._write_line(f"LED,{int(bits[0])},{int(bits[1])},{int(bits[2])}")

    def sequential_led_on(self, index: int) -> None:
        pattern = [i <= index for i in range(3)]
        self.set_leds(pattern)

    def all_leds_off(self) -> None:
        self.set_leds([False, False, False])

    def buzz(self, duration_s: float = 0.25) -> None:
        ms = max(1, int(duration_s * 1000))

        def _pulse() -> None:
            with self._lock:
                self.state.buzzer_on = True
            self._write_line(f"BUZZ,{ms}")
            time.sleep(duration_s)
            with self._lock:
                self.state.buzzer_on = False

        threading.Thread(target=_pulse, daemon=True).start()

    def snapshot(self) -> HardwareState:
        with self._lock:
            return HardwareState(
                led_on=list(self.state.led_on),
                buzzer_on=self.state.buzzer_on,
                distances_cm=list(self.state.distances_cm),
                threshold_cm=self.state.threshold_cm,
                connected=self.state.connected,
                port=self.state.port,
                last_error=self.state.last_error,
            )

    def simulate_pass(self, sensor_index: int) -> None:
        """초음파 통과 시뮬레이션 (거리 단축)."""
        if sensor_index < 0 or sensor_index > 2:
            return
        with self._lock:
            self.state.distances_cm[sensor_index] = 5.0
        self._emit_if_pass(sensor_index)
        time.sleep(0.05)
        with self._lock:
            self.state.distances_cm[sensor_index] = 30.0
            self._armed[sensor_index] = True

    def set_distance(self, sensor_index: int, distance_cm: float) -> None:
        with self._lock:
            self.state.distances_cm[sensor_index] = distance_cm
        self._emit_if_pass(sensor_index)

    def _apply_distances(self, distances: list[float]) -> None:
        for i, dist in enumerate(distances[:3]):
            with self._lock:
                self.state.distances_cm[i] = float(dist)
            self._emit_if_pass(i)

    def _parse_line(self, line: str) -> None:
        text = line.strip()
        if not text:
            return
        parts = text.replace(" ", "").split(",")
        if not parts:
            return
        head = parts[0].upper()
        if head in ("D", "DIST") and len(parts) >= 4:
            try:
                distances = [float(parts[1]), float(parts[2]), float(parts[3])]
            except ValueError:
                return
            self._apply_distances(distances)

    def _read_loop(self) -> None:
        buf = ""
        while self._running:
            with self._lock:
                ser = self._ser
            if ser is None:
                break
            try:
                raw = ser.readline()
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self.state.last_error = str(exc)
                    self.state.connected = False
                break
            if not raw:
                continue
            try:
                buf += raw.decode("utf-8", errors="ignore")
            except Exception:  # noqa: BLE001
                continue
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                self._parse_line(line)

    def _emit_if_pass(self, sensor_index: int) -> None:
        with self._lock:
            dist = self.state.distances_cm[sensor_index]
            threshold = self.state.threshold_cm
            armed = self._armed[sensor_index]
            if dist < threshold and armed:
                self._armed[sensor_index] = False
                callback = self.on_pass
            else:
                if dist >= threshold:
                    self._armed[sensor_index] = True
                callback = None
                dist = 0.0
        if callback is not None:
            callback(sensor_index, dist)

    def reset_triggers(self) -> None:
        with self._lock:
            self._armed = [True, True, True]
            self.state.distances_cm = [30.0, 30.0, 30.0]
