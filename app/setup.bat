@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [1/3] 가상환경 만드는 중...
if not exist .venv ( py -3.12 -m venv .venv || python -m venv .venv )
echo [2/3] 필요한 프로그램 설치 중 (처음 한 번, 몇 분 걸려요)...
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt
echo [3/3] 인식 모델 받는 중 (약 210MB)...
.venv\Scripts\python models.py
echo 완료! 이제 "수식캡처.bat" 을 실행하세요.
pause
