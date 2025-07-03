@echo off
setlocal

:: 1. 가상 환경 생성
echo "--- 1. Creating virtual environment 'venv' ---"
python -m venv venv

:: 2. 애플리케이션의 모든 의존성을 먼저 설치
echo "--- 2. Installing ALL application dependencies FIRST ---"
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\python.exe -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
REM [핵심 수정] serpapi 대신 google-search-results를 설치합니다.
venv\Scripts\python.exe -m pip install sentence-transformers requests google-search-results

:: 3. 빌드 도구(PyInstaller)는 가장 마지막에 설치
echo "--- 3. Installing the build tool (PyInstaller) at the very end ---"
venv\Scripts\python.exe -m pip install pyinstaller

:: 4. 실행 파일 빌드
echo "--- 4. Building executable ---"
venv\Scripts\pyinstaller.exe --noconsole --onefile --name "TouristReviewAnalyzer" --add-data "config.ini;." main_app.py

echo "--- Build script completed successfully! ---"
