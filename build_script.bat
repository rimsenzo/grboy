@echo off
setlocal

:: 1. 가상 환경 생성
echo "--- 1. Creating virtual environment 'venv' ---"
python -m venv venv

:: 2. 모든 의존성 설치
echo "--- 2. Installing dependencies ---"
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\python.exe -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
venv\Scripts\python.exe -m pip install sentence-transformers requests serpapi
venv\Scripts\python.exe -m pip install pyinstaller

:: 3. 실행 파일 빌드
echo "--- 3. Building executable ---"
venv\Scripts\python.exe -m pyinstaller --noconsole --onefile --name "TouristReviewAnalyzer" --add-data "config.ini;." main_app.py

:: 4. [최후의 진단] 빌드 결과물이 실제로 존재하는지 확인
echo "--- 4. Verifying build output in 'dist' folder ---"
dir dist

echo "--- Build script completed successfully! ---"
