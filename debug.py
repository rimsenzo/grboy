import gspread
from oauth2client.service_account import ServiceAccountCredentials
import configparser
import os

# --- 개발자님의 환경에 맞게 이 부분을 수정하세요 ---
CONFIG_FILE = 'config.ini'


# ------------------------------------------------

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


print("--- 구글 시트 연결 테스트 시작 ---")

try:
    # 1. 설정 파일 읽기
    config = configparser.ConfigParser()
    config.read(resource_path(CONFIG_FILE), encoding='utf-8')
    key_filename = config['PATHS']['google_sheet_key_path']
    spreadsheet_name = config['PATHS']['spreadsheet_name']
    print(f"  - 설정 파일 로드 완료: 시트 이름 '{spreadsheet_name}'")

    # 2. 인증 시도
    scopes = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name(resource_path(key_filename), scopes)
    gc = gspread.authorize(creds)
    print("  - 구글 API 인증 성공!")

    # 3. 스프레드시트 열기 시도
    spreadsheet = gc.open(spreadsheet_name)
    print(f"  - 스프레드시트 '{spreadsheet.title}' 열기 성공!")

    # 4. 첫 번째 워크시트 읽기 시도
    worksheet = spreadsheet.sheet1
    print(f"  - 첫 번째 워크시트 '{worksheet.title}' 읽기 성공!")

    print("\n🎉 테스트 성공! Google Sheets 연결에 문제가 없습니다.")

except FileNotFoundError:
    print(f"\n❌ 테스트 실패: 설정 파일 '{CONFIG_FILE}' 또는 키 파일 '{key_filename}'을 찾을 수 없습니다.")
except Exception as e:
    print(f"\n❌ 테스트 실패: 예상치 못한 오류가 발생했습니다.")
    print(f"  - 오류 유형: {type(e).__name__}")
    print(f"  - 오류 내용: {e}")
    print("\n  - 해결 방안: 위에서 제안한 네트워크, API 키, 공유/권한 설정을 확인해보세요.")

