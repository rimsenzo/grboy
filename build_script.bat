@echo off
setlocal

:: 1. 가상 환경 생성
echo "--- 1. Creating virtual environment 'venv' ---"
python -m venv venv

:: 2. [핵심 변경] 애플리케이션의 의존성을 먼저 모두 설치
echo "--- 2. Installing ALL application dependencies FIRST ---"
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\python.exe -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
venv\Scripts\python.exe -m pip install sentence-transformers requests serpapi

:: 3. [핵심 변경] 빌드 도구(PyInstaller)는 가장 마지막에 설치
echo "--- 3. Installing the build tool (PyInstaller) at the very end ---"
venv\Scripts\python.exe -m pip install pyinstaller

:: 4. [최후의 진단] PyInstaller가 정말 설치되었는지 즉시 확인
echo "--- 4. Verifying PyInstaller installation IMMEDIATELY ---"
venv\Scripts\python.exe -m pyinstaller --version

:: 5. 실행 파일 빌드
echo "--- 5. Building executable ---"
venv\Scripts\python.exe -m pyinstaller --noconsole --onefile --name "TouristReviewAnalyzer" --add-data "config.ini;." main_app.py

echo "--- Build script completed successfully! ---"
