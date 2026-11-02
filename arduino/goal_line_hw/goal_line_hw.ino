/*
 * RC Goal Line — LED 5개 + 상태 LED + 부저
 *
 *   D3  LED1
 *   D4  LED2
 *   D5  LED3
 *   D6  LED4
 *   D7  LED5
 *   D8  상태 LED
 *   D9  능동 부저 (Active Buzzer)
 *
 * 각 Dn에 LED 1개 (양극→핀, 음극→GND, 저항 220Ω)
 * 능동 부저: + → D9, − → GND  (내장 발진 → HIGH면 울림)
 *
 * 시리얼 115200
 *   LED,1,1,0,0,0
 *   BUZZ,200
 *   STATUS,1
 *   ALL,0 / ALL,1
 *   TEST
 */

const uint8_t PIN_LED[5] = {3, 4, 5, 6, 7};
const uint8_t PIN_STATUS = 8;
const uint8_t PIN_BUZZER = 9;

String serialBuf;
unsigned long buzzUntilMs = 0;
bool buzzing = false;

void setLed(uint8_t i, bool on) {
  if (i >= 5) return;
  digitalWrite(PIN_LED[i], on ? HIGH : LOW);
}

void setLeds(const bool bits[5]) {
  for (uint8_t i = 0; i < 5; i++) {
    setLed(i, bits[i]);
  }
}

void setAllLeds(bool on) {
  for (uint8_t i = 0; i < 5; i++) {
    setLed(i, on);
  }
}

void buzzerOff() {
  digitalWrite(PIN_BUZZER, LOW);
  buzzing = false;
  buzzUntilMs = 0;
}

void startBuzz(unsigned long ms) {
  if (ms == 0) {
    buzzerOff();
    return;
  }
  // 능동 부저: HIGH = ON (음높이 고정, tone 불필요)
  digitalWrite(PIN_BUZZER, HIGH);
  buzzing = true;
  buzzUntilMs = millis() + ms;
}

void updateBuzz() {
  if (buzzing && (long)(millis() - buzzUntilMs) >= 0) {
    buzzerOff();
  }
}

void parseBits(const String& line, int start, bool bits[5]) {
  for (uint8_t i = 0; i < 5; i++) bits[i] = false;
  if (start < 0) return;
  for (uint8_t i = 0; i < 5; i++) {
    if (start > (int)line.length()) break;
    int next = line.indexOf(',', start);
    String token = (next < 0) ? line.substring(start) : line.substring(start, next);
    token.trim();
    if (token.length() == 0) break;
    bits[i] = (token.toInt() != 0);
    if (next < 0) break;
    start = next + 1;
  }
}

void runSelfTest() {
  setAllLeds(false);
  for (uint8_t i = 0; i < 5; i++) {
    setLed(i, true);
    delay(200);
  }
  delay(300);
  setAllLeds(false);
  startBuzz(80);
  Serial.println(F("OK,TEST"));
}

void handleCommand(String line) {
  line.trim();
  if (line.length() == 0) return;
  line.replace(" ", "");

  int comma = line.indexOf(',');
  String head = (comma < 0) ? line : line.substring(0, comma);
  head.toUpperCase();

  if (head == "LED") {
    bool bits[5];
    parseBits(line, comma + 1, bits);
    setLeds(bits);
    return;
  }

  if (head == "BUZZ") {
    unsigned long ms = 200;
    if (comma >= 0) ms = (unsigned long)line.substring(comma + 1).toInt();
    if (ms < 1) ms = 1;
    if (ms > 5000) ms = 5000;
    startBuzz(ms);
    return;
  }

  if (head == "STATUS") {
    bool on = (comma >= 0) && (line.substring(comma + 1).toInt() != 0);
    digitalWrite(PIN_STATUS, on ? HIGH : LOW);
    return;
  }

  if (head == "ALL") {
    int v = (comma >= 0) ? line.substring(comma + 1).toInt() : 0;
    setAllLeds(v != 0);
    digitalWrite(PIN_STATUS, v != 0 ? HIGH : LOW);
    if (v == 0) startBuzz(0);
    return;
  }

  if (head == "TEST") {
    runSelfTest();
  }
}

void setup() {
  for (uint8_t i = 0; i < 5; i++) {
    pinMode(PIN_LED[i], OUTPUT);
    digitalWrite(PIN_LED[i], LOW);
  }
  pinMode(PIN_STATUS, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  digitalWrite(PIN_STATUS, LOW);
  digitalWrite(PIN_BUZZER, LOW);

  Serial.begin(115200);
  serialBuf.reserve(64);

  // 부팅: LED1→5 누적 점등 후 소등
  digitalWrite(PIN_STATUS, HIGH);
  for (uint8_t i = 0; i < 5; i++) {
    setLed(i, true);
    delay(150);
  }
  delay(200);
  setAllLeds(false);
  startBuzz(60);

  Serial.println(F("OK,GOAL_LINE_HW,LED5"));
}

void loop() {
  updateBuzz();

  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      handleCommand(serialBuf);
      serialBuf = "";
    } else if (serialBuf.length() < 96) {
      serialBuf += c;
    } else {
      serialBuf = "";
    }
  }
}
