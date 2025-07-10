import requests
import json

# --- 사용자 설정 ---
# ※ 중요: 본인의 SerpApi API 키를 이곳에 입력해주세요.
SERPAPI_API_KEY = "d7fd95ed11bc75bf6ab9b41c68229727066b6a3b5e73f1dc63b86796e62c9436"
# 확인할 장소 이름
PLACE_NAME = "밀락더마켓"


# --------------------------------------------------------------------------

def check_reviews():
    """
    특정 장소의 리뷰 수집 과정을 단계별로 테스트하는 함수
    1. 장소 이름으로 Place ID 검색
    2. Place ID로 리뷰 데이터 요청
    3. API 원본 응답 확인 및 결과 분석
    """

    if SERPAPI_API_KEY == "YOUR_SERPAPI_API_KEY":
        print("!!! 오류: 코드를 실행하기 전에 SERPAPI_API_KEY를 본인의 키로 변경해주세요. !!!")
        return

    # --- 1단계: 장소 이름으로 Place ID 검색 ---
    print(f"--- 1단계: '{PLACE_NAME}'의 Place ID 검색 시작 ---")
    search_params = {
        "engine": "google_maps",
        "q": PLACE_NAME,
        "api_key": SERPAPI_API_KEY
    }

    try:
        search_response = requests.get("https://serpapi.com/search.json", params=search_params)
        search_response.raise_for_status()  # HTTP 오류 발생 시 예외 처리
        search_data = search_response.json()
    except requests.exceptions.RequestException as e:
        print(f"!!! 1단계 오류: 장소 검색 API 요청에 실패했습니다. -> {e}")
        return

    place_id = search_data.get("place_results", {}).get("place_id")

    if place_id:
        print(f"-> 성공: Place ID를 찾았습니다: {place_id}")
        # 참고: '밀락더마켓'의 알려진 Place ID는 'ChIJcWnFpE2naDURw2Nb0o2wP3g' 입니다.
        if place_id != "ChIJcWnFpE2naDURw2Nb0o2wP3g":
            print("-> 경고: 알려진 Place ID와 다릅니다. 검색어가 부정확할 수 있습니다.")
    else:
        print("!!! 1단계 실패: Place ID를 찾을 수 없습니다.")
        print("API 응답 원본:")
        print(json.dumps(search_data, indent=2, ensure_ascii=False))
        return  # Place ID가 없으면 다음 단계 진행 불가

    print("\n" + "=" * 50 + "\n")

    # --- 2단계: 찾은 Place ID로 리뷰 데이터 요청 ---
    print(f"--- 2단계: Place ID '{place_id}'로 리뷰 요청 시작 ---")
    reviews_params = {
        "engine": "google_maps_reviews",
        "place_id": place_id,
        "api_key": SERPAPI_API_KEY
    }

    try:
        reviews_response = requests.get("https://serpapi.com/search.json", params=reviews_params)
        reviews_response.raise_for_status()
        reviews_data = reviews_response.json()
    except requests.exceptions.RequestException as e:
        print(f"!!! 2단계 오류: 리뷰 API 요청에 실패했습니다. -> {e}")
        return

    # --- 3단계: API 원본 응답 확인 및 최종 분석 ---
    print("--- 3단계: 리뷰 API로부터 받은 원본 응답(Raw Data)입니다 ---")
    print(json.dumps(reviews_data, indent=2, ensure_ascii=False))

    print("\n" + "=" * 50 + "\n")
    print("--- 최종 분석 결과 ---")

    if "error" in reviews_data:
        print(f"-> 문제 확인: API가 오류를 반환했습니다. 메시지: {reviews_data['error']}")
    elif "reviews" in reviews_data and reviews_data["reviews"]:
        review_count = len(reviews_data["reviews"])
        print(f"-> 성공: {review_count}개의 리뷰를 정상적으로 가져왔습니다.")
        print("-> 원인 추정: API는 정상입니다. 기존 프로젝트 코드에서 이 데이터를 처리(파싱, 필터링)하는 부분에 문제가 있을 가능성이 매우 높습니다.")
    else:
        print("-> 문제 확인: API가 리뷰 데이터를 반환하지 않았습니다. ('reviews' 키가 없거나 비어있음)")
        print("-> 원인 추정: SerpApi 측에서 이 장소의 리뷰를 제공하지 않거나, 일시적인 API 문제일 수 있습니다.")


if __name__ == "__main__":
    check_reviews()
