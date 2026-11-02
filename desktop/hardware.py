from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Optional


# D3~D7 각 핀에 LED 1개 (총 5개)
LED_COUNT = 5


@dataclass
class HardwareState:
    led_on: list[bool] = field(default_factory=lambda: [False] * LED_COUNT)
    buzzer_on: bool = False
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
    """아두이노 LED/부저 — COM 시리얼 연결.

    송신:
      LED,1,1,0,0,0   # LED1~5 (D3~D7)
      BUZZ,200        # 능동 부저 (D9, HIGH=ON)
      STATUS,1        # 상태 LED (D8)
      TEST            # LED1→5 순차 점등
    """

    def __init__(self) -> None:
        self.state = HardwareState()
        self._lock = threading.Lock()
        self._ser = None
        self._reader: Optional[threading.Thread] = None
        self._running = False

    @staticmethod
    def _format_open_error(port: str, exc: BaseException) -> str:
        msg = str(exc)
        low = msg.lower()
        if (
            "access is denied" in low
            or "permissionerror" in low
            or "액세스가 거부" in msg
            or "엑세스가 거부" in msg
            or "거부되었습니다" in msg
        ):
            return (
                f"{port} 엑세스 거부\n\n"
                "COM 포트를 다른 프로그램이 사용 중입니다.\n"
                "· Arduino IDE 시리얼 모니터 닫기\n"
                "· 다른 RC Goal Line / 시리얼 앱 종료\n"
                "· USB 뽑았다가 다시 연결 후 재시도"
            )
        if "could not open port" in low or "filenotfound" in low:
            return (
                f"{port} 을(를) 열 수 없습니다.\n"
                "USB 연결과 COM 번호(↻ 새로고침)를 확인하세요."
            )
        return f"{port} 연결 실패: {msg}"

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

        ser = None
        last_exc: Optional[BaseException] = None
        # 업로드/모니터 직후 포트가 잠깐 잠겨 있을 수 있어 재시도
        for attempt in range(5):
            try:
                ser = serial.Serial(
                    port=port,
                    baudrate=baudrate,
                    timeout=0.05,
                    write_timeout=1.0,
                )
                last_exc = None
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                time.sleep(0.4 * (attempt + 1))

        if ser is None:
            with self._lock:
                self.state.last_error = self._format_open_error(
                    port, last_exc or RuntimeError("unknown")
                )
                self.state.connected = False
                self.state.port = port
            return False

        # USB 시리얼 오픈 시 아두이노 리셋 → 부팅 완료 대기
        time.sleep(2.0)
        try:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
        except Exception:  # noqa: BLE001
            pass

        with self._lock:
            self._ser = ser
            self.state.connected = True
            self.state.port = port
            self.state.last_error = ""
        self._running = True
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self.set_status_led(True)
        self.all_leds_off()
        return True

    def disconnect(self) -> None:
        self._running = False
        if self._reader and self._reader.is_alive():
            self._reader.join(timeout=1.0)
        self._reader = None
        with self._lock:
            ser = self._ser
            self._ser = None
            self.state.connected = False
        if ser is not None:
            try:
                # 종료 전 소등 시도 (실패해도 포트는 반드시 닫음)
                ser.write(b"ALL,0\n")
                ser.flush()
            except Exception:  # noqa: BLE001
                pass
            try:
                ser.close()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.15)

    def _write_line(self, line: str) -> None:
        with self._lock:
            ser = self._ser
            connected = self.state.connected
            if not connected or ser is None:
                return
            try:
                ser.write((line.strip() + "\n").encode("utf-8"))
                ser.flush()
            except Exception as exc:  # noqa: BLE001
                self.state.last_error = str(exc)
                self.state.connected = False

    def set_leds(self, pattern: list[bool]) -> None:
        with self._lock:
            padded = list(pattern[:LED_COUNT]) + [False] * max(0, LED_COUNT - len(pattern))
            self.state.led_on = padded
            bits = list(self.state.led_on)
        self._write_line("LED," + ",".join(str(int(b)) for b in bits))

    def sequential_led_on(self, index: int) -> None:
        """index=0 → LED1만, index=4 → LED1~5 전부 점등."""
        idx = max(0, min(int(index), LED_COUNT - 1))
        pattern = [i <= idx for i in range(LED_COUNT)]
        self.set_leds(pattern)

    def all_leds_off(self) -> None:
        self.set_leds([False] * LED_COUNT)

    def set_status_led(self, on: bool) -> None:
        self._write_line(f"STATUS,{int(bool(on))}")

    def test_leds(self) -> None:
        """LED1→5 누적 점등 자가진단."""
        self._write_line("TEST")

    def buzz(self, duration_s: float = 0.25) -> None:
        ms = max(1, int(duration_s * 1000))
        with self._lock:
            self.state.buzzer_on = True
        self._write_line(f"BUZZ,{ms}")

        def _clear() -> None:
            time.sleep(duration_s)
            with self._lock:
                self.state.buzzer_on = False

        threading.Thread(target=_clear, daemon=True).start()

    def snapshot(self) -> HardwareState:
        with self._lock:
            return HardwareState(
                led_on=list(self.state.led_on),
                buzzer_on=self.state.buzzer_on,
                connected=self.state.connected,
                port=self.state.port,
                last_error=self.state.last_error,
            )

    def _read_loop(self) -> None:
        """아두이노 OK 응답 등을 비워 버퍼 적체를 막는다."""
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
