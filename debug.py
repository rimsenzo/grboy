import configparser
import os
from serpapi import GoogleSearch


def load_api_key():
    try:
        config = configparser.ConfigParser()
        config_path = os.path.join(os.path.dirname(__file__), 'config.ini')
        if not config.read(config_path, encoding='utf-8'):
            raise FileNotFoundError("config.ini 파일을 찾을 수 없습니다.")
        return config.get('API_KEYS', 'serpapi_api_key')
    except Exception as e:
        print(f"오류: config.ini 파일에서 API 키를 읽는 데 실패했습니다. - {e}")
        return None


def get_google_place_info(api_key, location_name, location_address):
    print(f"\n--- [1단계] '{location_name}'의 Place ID와 정보 검색 시작 ---")
    search_query = f"{location_name}, {location_address}"
    print(f"   - 검색어: \"{search_query}\"")

    try:
        params = {"engine": "google_maps", "q": search_query, "type": "search", "hl": "ko", "api_key": api_key}
        search = GoogleSearch(params)
        results = search.get_dict()

        local_results = results.get("local_results", [])
        if not local_results:
            print("   - 결과: API 응답에 'local_results'가 없습니다. 장소를 찾지 못했습니다.")
            return None

        found_place = local_results[0]

        # ⭐⭐⭐ 핵심 디버깅 출력: 구글이 실제로 찾아준 장소의 정보 ⭐⭐⭐
        print("\n[구글맵 검색 결과]")
        print(f"  - 찾은 장소 이름: {found_place.get('title')}")
        print(f"  - 찾은 장소 주소: {found_place.get('address')}")
        print(f"  - 찾은 장소 Place ID: {found_place.get('place_id')}")
        # ⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐

        return found_place

    except Exception as e:
        print(f"오류: SerpApi로 Place ID 검색 중 오류 발생 - {e}")
        return None


# --- 메인 실행 코드 ---
if __name__ == "__main__":
    # 테스트할 관광지 정보 (실제 프로그램과 최대한 유사하게 구성)
    tourist_spot_name = "감지해변"
    # 한국관광공사 API가 제공했을 법한 상세 주소 (예시)
    tourist_spot_address = "부산광역시 영도구 동삼동"

    serp_api_key = load_api_key()

    if serp_api_key:
        # 1단계: 장소 정보를 가져옵니다.
        place_info = get_google_place_info(serp_api_key, tourist_spot_name, tourist_spot_address)

        if place_info:
            print(f"\n[결론] '{tourist_spot_name}'으로 검색했지만, 실제로는 '{place_info.get('title')}'의 리뷰를 가져오게 됩니다.")
        else:
            print("\n[결론] Place ID를 찾지 못했습니다.")
