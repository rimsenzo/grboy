@echo off
setlocal

:: 1. 가상 환경 생성
echo "--- 1. Creating virtual environment 'venv' ---"
python -m venv venv

:: 2. 애플리케이션의 모든 의존성을 먼저 설치
echo "--- 2. Installing ALL application dependencies FIRST ---"
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\python.exe -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
venv\Scripts\python.exe -m pip install sentence-transformers requests serpapi

:: 3. 빌드 도구(PyInstaller)는 가장 마지막에 설치
echo "--- 3. Installing the build tool (PyInstaller) at the very end ---"
venv\Scripts\python.exe -m pip install pyinstaller

:: 4. [최후의 진단] pyinstaller.exe 파일이 실제로 존재하는지 확인
echo "--- 4. Verifying that pyinstaller.exe exists ---"
dir venv\Scripts\pyinstaller.exe

:: 5. [궁극의 해결책] 파이썬 모듈(-m)이 아닌, 실행 파일(.exe)을 직접 호출하여 빌드
echo "--- 5. Building executable by calling pyinstaller.exe directly ---"
venv\Scripts\pyinstaller.exe --noconsole --onefile --name "TouristReviewAnalyzer" --add-data "config.ini;." main_app.py

echo "--- Build script completed successfully! ---"
