## 프로그램의 흐름

### (1) 프로그램 셋팅
프로그램 실행 → 연결할 카메라 번호를 선택 후 카메라 연결(버튼) → 마우스로 두 점을 지정하여 그 사이를 직선(선분아님)으로 이음(가상 골라인)

### (2) 선수 등록 흐름
차량 목록 칸 옆에있는 입력 칸 두개에 학번, 이름순으로 기입(최종 구조는 차량아이디(RC-n) | 학번 | 이름→ 저장 버튼을 클릭 → 기록 창에 업로드

### (3) 경기 시작 시 흐름
프로그램 사용자가 시작 버튼을 클릭 → 빨간 LED 1초 간격으로 순차 점등(하드웨어) → 1초 - 3초중 랜덤하게 선택 → 앞서 선택된 시간이 지난후 빨간 LED 동시 소등(하드웨어), 부저작동(하드웨어), 랩 타임 기록시작(mm:ss:ms)

### (4) 부정 출발 판정
빨간 LED 동시 소등 및 부저가 울리기 전에 ArCuo마크의 중앙이 가상 골라인의 반대쪽으로 이동 → 부정출발 처리 → 해당 차량코드에 10초를 추가함

### (5) 골라인 통과시 처리흐름
ArCuo마크의 중앙이 골라인을 통과 → 진행중인 랩과 랩 타임을 확인 → 당시 랩 타임, 경기 시작후 소요시간을 기록 창에 자동기입 → 랩 타임 초기화 → 3초간 해당 차량의 랩 타임 갱신 중지(부정행위 방지)

### (6) 경기 종료후 처리흐름
모든 차량이 마지막 랩 종료 → 랩타임을 CSV에 기록(ID, Student_num, name, 1lap_time, 2lap_time, 3lap_time)


idea by 고정우



환경 설치 명령어
- PowerShell에서:
winget install Python.Python.3.12 --accept-package-agreements --accept-source-agreements
설치 후 PowerShell을 닫았다가 다시 열고:
python --version
- python -m venv .venv
- .\.venv\Scripts\Activate.ps1
- pip install -r requirements.txt

실행 명령어
- python -m desktop
