import gspread
from oauth2client.service_account import ServiceAccountCredentials
import configparser

# config.ini 파일 읽기
config = configparser.ConfigParser()
config.read('config.ini', encoding='utf-8')
key_path = config['PATHS']['google_sheet_key_path']
spreadsheet_id = config['PATHS']['spreadsheet_id']

# 인증 및 접속
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_name(key_path, scope)
gs = gspread.authorize(creds)
spreadsheet = gs.open_by_key(spreadsheet_id)

# 테스트 시트 데이터 읽기
try:
    # 1. '기업리뷰_데이터' 시트를 테스트합니다.
    worksheet_data = spreadsheet.worksheet('기업리뷰_데이터')
    values_data = worksheet_data.get_all_values()
    print(f"--- '기업리뷰_데이터' 시트 ---")
    print(f"총 줄 수: {len(values_data)}")
    if len(values_data) > 1:
        print(f"헤더: {values_data[0]}")
        print(f"첫 데이터 행: {values_data[1]}")
    else:
        print("데이터가 없거나 헤더만 있습니다.")

    print("\n" + "="*30 + "\n")

    # 2. '최종_테스트' 시트를 테스트합니다.
    worksheet_test = spreadsheet.worksheet('기업리뷰    ')
    values_test = worksheet_test.get_all_values()
    print(f"--- '최종_테스트' 시트 ---")
    print(f"총 줄 수: {len(values_test)}")
    if len(values_test) > 1:
        print(f"헤더: {values_test[0]}")
        print(f"첫 데이터 행: {values_test[1]}")
    else:
        print("데이터가 없거나 헤더만 있습니다.")

except Exception as e:
    print(f"오류 발생: {e}")
