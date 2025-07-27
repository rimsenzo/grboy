import tkinter as tk
from tkinter import ttk, messagebox, font, filedialog
import threading
import requests
import json
import warnings
import configparser
import os
import time
from collections import Counter
import sys

# --- ▼▼▼ [핵심 수정] 라이브러리 임포트를 스크립트 최상단으로 이동 ▼▼▼ ---
# 이 라이브러리들은 프로그램 실행 시 설치되어 있어야 합니다.
# pip install torch sentence-transformers transformers gspread pandas oauth2client-contrib serpapi
try:
    import pandas as pd
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
    from serpapi import GoogleSearch
    # 아래 라이브러리들은 무거워서 필요할 때마다 로드하도록 유지합니다.
    # import torch, transformers, sentence_transformers
except ImportError as e:
    # 이 코드는 명령 프롬프트에서 실행 시에만 유용하므로, GUI에서는 시작점에서 처리합니다.
    print(f"오류: 필수 라이브R러리가 없습니다: {e.name}. 'pip install {e.name}'으로 설치해주세요.")
    # GUI 환경을 위해 messagebox를 사용하려면 Tk() 초기화가 필요하므로 시작점에서 처리하는 것이 더 안전합니다.
    # tk.Tk().withdraw(); messagebox.showerror("라이브러리 오류", f"필수 라이브러리 누락: {e.name}"); sys.exit()


# --- ▲▲▲ [수정 완료] ▲▲▲ ---

def resource_path(relative_path):
    """ 개발 환경과 PyInstaller 실행 환경 모두에서 리소스 절대 경로를 올바르게 반환합니다. """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


# 불필요한 경고 메시지 무시
warnings.filterwarnings("ignore", category=UserWarning, message=".*pkg_resources is deprecated.*")
warnings.filterwarnings('ignore', message='Unverified HTTPS request')


# ------------------- 백엔드 로직: ReviewAnalyzer 클래스 -------------------
class ReviewAnalyzer:
    """ API 호출, 데이터 가공, AI 분석 등 핵심 비즈니스 로직을 담당합니다. """

    def __init__(self, api_keys, paths):
        """ [수정] 트립어드바이저 API 키 설정을 복원합니다. """
        # --- API 키 및 경로 초기화 ---
        self.KOREA_TOUR_API_KEY = api_keys.get('korea_tour_api_key')
        self.TRIPADVISOR_API_KEY = api_keys.get('tripadvisor_api_key')  # 이 줄 복원
        self.SERPAPI_API_KEY = api_keys.get('serpapi_api_key')

        self.KOREA_TOUR_API_URL = "http://apis.data.go.kr/B551011/KorService2/areaBasedList2"
        self.TRIPADVISOR_API_URL = "https://api.content.tripadvisor.com/api/v1"  # 이 줄 복원

        self.paths = paths
        self.GOOGLE_SHEET_KEY_FILENAME = self.paths.get('google_sheet_key_path')
        self.scopes = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']

        # --- 데이터프레임 및 AI 모델 초기화 ---
        self.company_df = pd.DataFrame()
        self.review_df = pd.DataFrame()
        self.preference_df = pd.DataFrame()
        self.sbert_model = None
        self.category_embeddings = None

        self.get_company_data_from_sheet()

        # --- 리뷰 분류 카테고리 정의 ---
        self.CATEGORIES = {
            'K-문화': ['K팝', 'K드라마', '영화 촬영지', '한류', '부산국제영화제', 'BIFF', '아이돌', '팬미팅', 'SNS', '인스타그램', '핫플레이스', '슬램덩크'],
            '해양': ['바다', '해변', '해수욕장', '해안', '항구', '섬', '등대', '요트', '해상케이블카', '스카이캡슐', '해변열차', '파도', '수족관', '서핑',
                   '스카이워크'],
            '웰니스': ['힐링', '휴식', '스파', '사우나', '온천', '족욕', '마사지', '산책', '자연', '평화', '평온', '치유', '고요함', '명상', '건강'],
            '뷰티': ['미용', '헤어', '피부', '메이크업', '네일', '에스테틱', '피부관리', '뷰티서비스', '마사지', '미용실', '헤어샵', '네일샵', '살롱', '화장품',
                   'K-뷰티', '퍼스널컬러', '스타일링', '시술', '페이셜'],
            'e스포츠': ['e스포츠', '게임', 'PC방', '대회', '경기장', '프로게이머', '리그오브레전드', 'LCK', '스타크래프트', '페이커', '이스포츠'],
            '미식': ['맛집', '음식', '레스토랑', '카페', '해산물', '시장', '회', '조개구이', '돼지국밥', '디저트', '식도락']
        }

    def get_location_id_from_tripadvisor(self, spot_name):
        """ [복원] 트립어드바이저 Location ID를 검색합니다. """
        print(f"\n--- TripAdvisor Location ID 탐색 시작: '{spot_name}' ---")
        if not spot_name or not self.TRIPADVISOR_API_KEY: return None
        try:
            params = {'key': self.TRIPADVISOR_API_KEY, 'searchQuery': spot_name, 'language': 'ko'}
            response = requests.get(f"{self.TRIPADVISOR_API_URL}/location/search", params=params,
                                    headers={'accept': 'application/json'}, timeout=10)
            if response.status_code == 200:
                data = response.json().get('data', [])
                if data:
                    location_id = data[0].get('location_id')
                    print(f"  - 성공: Location ID '{location_id}'를 찾았습니다.")
                    return location_id
            print(f"  - 실패: 유효한 Location ID를 찾지 못했습니다. (상태코드: {response.status_code})")
            return None
        except requests.exceptions.RequestException as e:
            print(f"  - 실패: API 요청 중 오류 발생: {e}")
            return None

    def get_tripadvisor_reviews(self, location_id):
        """ [복원] 트립어드바이저 리뷰를 수집합니다. """
        print(f"\n--- TripAdvisor 리뷰 수집 시작 (Location ID: {location_id}) ---")
        if not location_id or not self.TRIPADVISOR_API_KEY: return []
        try:
            params = {'key': self.TRIPADVISOR_API_KEY, 'language': 'ko'}
            response = requests.get(f"{self.TRIPADVISOR_API_URL}/location/{location_id}/reviews", params=params,
                                    headers={'accept': 'application/json'}, timeout=10)
            if response.status_code == 200:
                reviews = response.json().get('data', [])
                extracted = [{'source': 'TripAdvisor', 'text': r['text']} for r in reviews if r.get('text')]
                print(f"  - 성공: {len(extracted)}개의 리뷰를 수집했습니다.")
                return extracted
            print(f"  - 실패: 리뷰를 수집하지 못했습니다. (상태코드: {response.status_code})")
            return []
        except requests.exceptions.RequestException as e:
            print(f"  - 실패: API 요청 중 오류 발생: {e}")
            return []

    def get_company_data_from_sheet(self):
        """ Google Sheets API를 통해 기업/리뷰/선호분야 데이터를 로드하고 DataFrame으로 변환합니다. """
        MAX_RETRIES = 3
        RETRY_DELAY = 5
        for attempt in range(MAX_RETRIES):
            try:
                creds = ServiceAccountCredentials.from_json_keyfile_name(resource_path(self.GOOGLE_SHEET_KEY_FILENAME),
                                                                         self.scopes)
                gc = gspread.authorize(creds)
                spreadsheet = gc.open(self.paths['spreadsheet_name'])

                def load_sheet_safely(worksheet_name):
                    worksheet = spreadsheet.worksheet(worksheet_name)
                    all_values = worksheet.get_all_values()
                    if not all_values or len(all_values) < 2: return pd.DataFrame()
                    header = all_values[0]
                    data = all_values[1:]
                    df = pd.DataFrame(data, columns=header)
                    if '' in df.columns: df = df.drop(columns=[''])
                    return df

                self.company_df = load_sheet_safely(self.paths['company_sheet_name'])
                print(f"--- '기업 정보' 로딩 완료: {len(self.company_df)}개 기업 ---")

                self.review_df = load_sheet_safely("기업리뷰")
                if '평점' in self.review_df.columns: self.review_df['평점'] = pd.to_numeric(self.review_df['평점'],
                                                                                        errors='coerce')
                print(f"--- '기업리뷰' 로딩 완료: {len(self.review_df)}개 리뷰 ---")

                self.preference_df = load_sheet_safely("선호분야")
                if '평점' in self.preference_df.columns: self.preference_df['평점'] = pd.to_numeric(
                    self.preference_df['평점'], errors='coerce')
                print(f"--- '선호분야' 로딩 완료: {len(self.preference_df)}개 평가 ---")
                return
            except gspread.exceptions.APIError as e:
                if e.response.status_code in [429, 503] and attempt < MAX_RETRIES - 1:
                    print(
                        f"경고: Google API 오류 (상태코드: {e.response.status_code}). {RETRY_DELAY}초 후 재시도... ({attempt + 1}/{MAX_RETRIES})")
                    time.sleep(RETRY_DELAY)
                else:
                    messagebox.showerror("구글 시트 오류", f"데이터 로드 실패 (API 오류):\n{e}");
                    return
            except Exception as e:
                messagebox.showerror("구글 시트 오류", f"데이터 로드 실패:\n{e}");
                return

    def get_tourist_spots_in_busan(self):
        """ 국문관광정보 API를 호출하여 부산 지역의 고유한 관광지 목록을 수집합니다. """
        all_spots = []
        seen_titles = set()
        content_type_ids = ['12', '14', '28']  # 관광지, 문화시설, 레포츠
        print(f"\n--- 부산 관광정보 수집 시작 (타입: {content_type_ids}) ---")

        for content_type_id in content_type_ids:
            try:
                params = {
                    'serviceKey': self.KOREA_TOUR_API_KEY, 'numOfRows': 500, 'pageNo': 1,
                    'MobileOS': 'ETC', 'MobileApp': 'AppTest', '_type': 'json',
                    'areaCode': 6, 'contentTypeId': content_type_id
                }
                response = requests.get(self.KOREA_TOUR_API_URL, params=params, timeout=15)
                if response.status_code != 200:
                    print(f"  - API 오류: 타입 ID={content_type_id}, 상태 코드={response.status_code}")
                    continue
                items = response.json().get('response', {}).get('body', {}).get('items', {}).get('item', [])
                if items:
                    count = 0
                    for item in items:
                        title = item.get('title')
                        if title and title not in seen_titles:
                            seen_titles.add(title)
                            all_spots.append({'title': title, 'addr1': item.get('addr1', '')})
                            count += 1
                    print(f"  - 타입 ID '{content_type_id}'에서 {count}개의 신규 장소 추가됨")
            except requests.exceptions.RequestException as e:
                print(f"  - API 요청 실패 (타입 ID: {content_type_id}): {e}")
            except Exception as e:
                print(f"  - 데이터 처리 중 오류 발생 (타입 ID: {content_type_id}): {e}")

        print(f"--- 총 {len(all_spots)}개의 고유한 관광지 정보를 수집했습니다. ---")
        return all_spots

    def get_google_place_id_via_serpapi(self, spot_name):
        """ SerpApi(Google)를 통해 리뷰 수집에 필요한 고유 Place ID를 탐색합니다. """
        precise_query = f"{spot_name}, 부산"
        print(f"\n--- Google Place ID 탐색 시작 (정밀 검색어: '{precise_query}') ---")
        try:
            print("  - [1단계] Knowledge Panel에서 Place ID를 탐색합니다.")
            params = {"engine": "google", "q": precise_query, "api_key": self.SERPAPI_API_KEY, "hl": "ko"}
            results = GoogleSearch(params).get_dict()
            if "knowledge_graph" in results and results.get("knowledge_graph", {}).get("place_id"):
                place_id = results["knowledge_graph"]["place_id"]
                print(f"  - 성공 (Knowledge Panel): Place ID '{place_id}'를 찾았습니다.")
                return place_id
        except Exception as e:
            print(f"  - 경고: Knowledge Panel 탐색 중 오류 발생 ({e}).")

        try:
            print("  - [2단계] Google Maps API에서 Place ID를 탐색합니다.")
            params = {"engine": "google_maps", "q": precise_query, "api_key": self.SERPAPI_API_KEY, "hl": "ko"}
            results = GoogleSearch(params).get_dict()
            if "local_results" in results and results["local_results"] and results["local_results"][0].get("place_id"):
                place_id = results["local_results"][0]["place_id"]
                print(f"  - 성공 (Maps Local): Place ID '{place_id}'를 찾았습니다.")
                return place_id
            if "place_results" in results and results.get('place_results', {}).get("place_id"):
                place_id = results['place_results']["place_id"]
                print(f"  - 성공 (Maps Place): Place ID '{place_id}'를 찾았습니다.")
                return place_id
        except Exception as e:
            print(f"  - 최종 실패: Maps API 탐색 중 예외 발생: {e}")

        print(f"  - 최종 실패: 유효한 Place ID를 찾지 못했습니다.")
        return None

    def get_google_reviews_via_serpapi(self, place_id, review_count=50):
        """ SerpApi(Google)를 통해 특정 장소의 리뷰를 목표 개수만큼 수집합니다. (페이지네이션 지원) """
        print(f"\n--- Google 리뷰 수집 시작 (Place ID: {place_id}, 목표 개수: {review_count}) ---")
        if not place_id: return []

        all_reviews_data = []
        params = {"engine": "google_maps_reviews", "place_id": place_id, "hl": "ko", "api_key": self.SERPAPI_API_KEY}
        search = GoogleSearch(params)

        while True:
            try:
                results = search.get_dict()
                if "error" in results: print(f"  - SerpApi 오류: {results['error']}"); break
                reviews = results.get("reviews", [])
                if not reviews: print("  - 현재 페이지에 더 이상 리뷰가 없어 수집을 중단합니다."); break

                all_reviews_data.extend(reviews)
                print(f"  - 리뷰 {len(reviews)}개 추가 (총 {len(all_reviews_data)}개 수집)")

                if len(all_reviews_data) >= review_count: print(f"  - 목표 리뷰 개수({review_count}개) 이상 수집 완료."); break

                pagination = results.get("serpapi_pagination")
                if pagination and "next_page_token" in pagination:
                    search.params_dict['next_page_token'] = pagination['next_page_token']
                else:
                    print("  -> 다음 페이지 없음. 리뷰 수집 완료.");
                    break
            except Exception as e:
                print(f"  - 리뷰 수집 중 예외 발생: {e}");
                break

        final_reviews = all_reviews_data[:review_count]
        extracted = [{'source': 'Google', 'text': r.get('snippet', '')} for r in final_reviews if r.get('snippet')]
        print(f"  - 최종적으로 내용이 있는 리뷰 {len(extracted)}개를 추출했습니다.")
        return extracted

    def _classify_reviews_by_similarity(self, all_reviews, threshold=0.4):
        """ [폴백 기능] 파인튜닝 모델이 없을 때, 범용 SBERT 모델로 리뷰와 카테고리 간 유사도를 계산하여 분류합니다. """
        from sentence_transformers import util
        import torch

        if not self.sbert_model or not self.category_embeddings:
            print("오류: 유사도 분석 모델이 로드되지 않았습니다.")
            return []

        classified_results = []
        review_texts = [review.get('text', '') for review in all_reviews if review.get('text', '').strip()]
        if not review_texts: return []

        review_embeddings = self.sbert_model.encode(review_texts, convert_to_tensor=True)

        for i, review_data in enumerate(filter(lambda r: r.get('text', '').strip(), all_reviews)):
            review_embedding = review_embeddings[i]
            scores = {cat: util.cos_sim(review_embedding, emb).max().item() for cat, emb in
                      self.category_embeddings.items()}

            if scores and max(scores.values()) >= threshold:
                best_category = max(scores, key=scores.get)
            else:
                best_category = '기타'

            classified_results.append({
                'review': review_data.get('text'),
                'source': review_data.get('source', '알 수 없음'),
                'category': best_category
            })
        return classified_results

ㄹ    def classify_reviews(self, all_reviews):
        """ [핵심 AI 기능] 파인튜닝된 AI 모델을 로드하여 리뷰를 분류합니다. 모델이 없으면 유사도 기반으로 폴백합니다. """
        from transformers import pipeline
        import torch

        model_path = resource_path('my_review_classifier')

        if not os.path.exists(model_path):
            print(f"경고: 파인튜닝된 모델 폴더('{model_path}')를 찾을 수 없습니다. 유사도 기반 분류로 전환합니다.")
            return self._classify_reviews_by_similarity(all_reviews)

        print(f"\n--- AI 모델 '{model_path}'을 사용하여 리뷰 분류 시작 ---")
        review_texts = [review.get('text', '') for review in all_reviews if review.get('text', '').strip()]
        if not review_texts: return []

        try:
            device = 0 if torch.cuda.is_available() else -1
            classifier = pipeline('text-classification', model=model_path, device=device)
            predictions = classifier(review_texts, truncation=True)
        except Exception as e:
            print(f"오류: AI 파이프라인 생성 또는 예측 중 오류 발생: {e}. 유사도 기반으로 전환합니다.")
            return self._classify_reviews_by_similarity(all_reviews)

        classified_results = []
        pred_idx = 0
        for review_data in all_reviews:
            text = review_data.get('text', '')
            category = '기타'
            if text.strip():
                if pred_idx < len(predictions):
                    category = predictions[pred_idx]['label']
                    pred_idx += 1

            classified_results.append({
                'review': text, 'source': review_data.get('source', '알 수 없음'), 'category': category
            })

        print("--- AI 기반 리뷰 분류 완료 ---")
        return classified_results

    def classify_all_companies(self):
        """ 프로그램 시작 시, 모든 기업의 '사업내용'을 AI 모델로 분석하여 가장 관련성 높은 카테고리를 미리 계산합니다. """
        from sentence_transformers import util

        if self.company_df.empty or '사업내용' not in self.company_df.columns: return
        if not self.sbert_model or not self.category_embeddings:
            print("경고: 기업 분류에 필요한 AI 모델이 로드되지 않았습니다.");
            return

        print("\n--- 전체 기업 데이터 AI 기반 사전 분류 시작 ---")
        self.company_df['사업내용'] = self.company_df['사업내용'].fillna('')
        business_embeddings = self.sbert_model.encode(self.company_df['사업내용'].tolist(), convert_to_tensor=True)

        categories, scores = [], []
        for emb in business_embeddings:
            sim_scores = {cat: util.cos_sim(emb, cat_emb).max().item() for cat, cat_emb in
                          self.category_embeddings.items()}
            if not sim_scores:
                best_cat, best_score = '기타', 0
            else:
                best_cat = max(sim_scores, key=sim_scores.get)
                best_score = sim_scores[best_cat]
            categories.append(best_cat);
            scores.append(best_score)

        self.company_df['best_category'], self.company_df['category_score'] = categories, scores
        print(f"--- 기업 분류 완료: {len(self.company_df)}개 기업에 카테고리 및 점수 부여 완료 ---")

    def recommend_companies(self, category, top_n=5):
        """ 사전 분류된 기업 목록에서 특정 카테고리의 기업을 유사도 점수 순으로 추천합니다. """
        if self.company_df.empty or 'best_category' not in self.company_df.columns: return []
        recommended_df = self.company_df[self.company_df['best_category'] == category].copy()
        recommended_df.sort_values(by='category_score', ascending=False, inplace=True)
        return recommended_df.head(top_n)['기업명'].tolist()

    # --- 기업 정보 페이지를 위한 데이터 요약 헬퍼 함수들 ---
    def get_reviews_by_type(self, company_name):
        """ 선택된 기업에 대한 리뷰를 '외부기관'과 익명화된 '동료 입주기업'으로 분리합니다. """
        if self.review_df.empty: return pd.DataFrame(), pd.DataFrame()
        all_internal_companies = self.company_df['기업명'].unique().tolist()
        target_reviews = self.review_df[self.review_df['기업명'] == company_name].copy()

        external_reviews = target_reviews[~target_reviews['평가기관'].isin(all_internal_companies)]
        peer_reviews = target_reviews[target_reviews['평가기관'].isin(all_internal_companies)].copy()

        if not peer_reviews.empty:
            peer_reviews['평가기관'] = peer_reviews['평가기관'].map({
                name: f"입주기업 {i + 1}" for i, name in enumerate(peer_reviews['평가기관'].unique())
            })
        return external_reviews, peer_reviews

    def get_preference_summary(self, company_name):
        """ 특정 기업이 평가한 외부 기관별 협업 만족도를 문장 리스트로 요약합니다. """
        if self.preference_df.empty: return []
        prefs_df = self.preference_df[self.preference_df['평가기업명'] == company_name]
        if prefs_df.empty: return []

        summary = []
        for target, group in prefs_df.groupby('평가대상기관'):
            total, pos = len(group), len(group[group['평점'] >= 4])
            ratio = (pos / total) * 100 if total > 0 else 0
            summary.append(f"{company_name}은(는) '{target}'과의 협업을 {ratio:.0f}% 긍정적으로 평가했습니다.")
        return summary

    def summarize_reviews(self, reviews_df, reviewer_type, target_company):
        """ 주어진 리뷰 DF를 문장 리스트로 요약합니다. """
        if reviews_df.empty: return []
        summary = []
        if reviewer_type == '외부기관':
            for evaluator, group in reviews_df.groupby('평가기관'):
                total, pos, avg_score = len(group), len(group[group['평점'] >= 4]), group['평점'].mean()
                ratio = (pos / total) * 100 if total > 0 else 0
                summary.append(f"'{evaluator}'의 {ratio:.0f}%가 '{target_company}'을(를) 긍정 평가 (평균 {avg_score:.1f}점).")
        elif reviewer_type == '입주기업':
            total, pos, avg_score = len(reviews_df), len(reviews_df[reviews_df['평점'] >= 4]), reviews_df['평점'].mean()
            ratio = (pos / total) * 100 if total > 0 else 0
            summary.append(f"'입주기업'들의 {ratio:.0f}%가 '{target_company}'을(를) 긍정 평가 (평균 {avg_score:.1f}점).")
        return summary

    def judge_sentiment_by_rating(self, rating):
        """ 평점을 기반으로 감성(긍정/중립/부정)을 판단합니다. """
        try:
            return "긍정 😊" if float(rating) >= 4 else "중립 😐" if float(rating) >= 3 else "부정 😠"
        except (ValueError, TypeError):
            return "정보 없음"


# ------------------- 프론트엔드 UI 위젯 및 페이지들 -------------------
class AutocompleteEntry(tk.Frame):
    """
    [개선된 버전] 자동완성 Entry와 전체 목록 보기 버튼을 포함하는 복합 위젯.
    - 디바운싱, 키보드 탐색, 마우스 클릭, 엔터 키 입력, 포커스 관리 기능이 모두 개선되었습니다.
    """

    def __init__(self, parent, controller, *args, **kwargs):
        self.on_select_callback = kwargs.pop('on_select_callback', None)
        self.completion_list = kwargs.pop('completion_list', [])

        # Frame을 기반으로 위젯을 만듭니다.
        super().__init__(parent)

        self.controller = controller
        self.debounce_timer = None
        self.just_selected = False

        # 실제 텍스트 입력창 (Entry)
        self.entry = ttk.Entry(self, *args, **kwargs)
        self.entry.pack(side='left', expand=True, fill='x')
        self.var = self.entry["textvariable"] = tk.StringVar()

        # 전체 목록 보기 버튼
        self.arrow_button = ttk.Button(self, text="▼", width=3, command=self._toggle_full_list)
        self.arrow_button.pack(side='right')

        # --- 이벤트 바인딩 ---
        self.var.trace_add('write', self._debounce_autocomplete)
        self.entry.bind("<FocusOut>", self._hide_popup_delayed)
        self.entry.bind("<Down>", self._move_selection)
        self.entry.bind("<Up>", self._move_selection)
        self.entry.bind("<Return>", self._handle_return_key)
        self.entry.bind("<Escape>", self._hide_popup)

        # --- 자동완성 팝업 윈도우 ---
        self._popup_window = tk.Toplevel(controller)
        self._popup_window.overrideredirect(True)
        self._popup_window.withdraw()
        self._listbox = tk.Listbox(self._popup_window, font=("Helvetica", 11), selectmode=tk.SINGLE,
                                   exportselection=False, highlightthickness=0)
        self._listbox.pack(expand=True, fill='both')
        # 마우스 클릭으로 항목 선택
        self._listbox.bind("<ButtonRelease-1>", self._select_item_from_click)

    # --- 공개 메서드들 ---
    def set_completion_list(self, new_list):
        self.completion_list = new_list

    def get(self):
        return self.var.get()

    def set(self, text):
        self.var.set(text)

    def focus_set(self):
        self.entry.focus_set()

    # --- 내부 로직 (이벤트 핸들러) ---
    def _toggle_full_list(self):
        """'▼' 버튼 클릭 시 전체 목록을 보여주거나 팝업을 닫습니다."""
        if self._popup_window.winfo_viewable():
            self._hide_popup()
        else:
            self._show_autocomplete(show_all=True)

    def _debounce_autocomplete(self, *args):
        """[핵심 기능] 타이핑 랙을 막기 위한 디바운싱을 구현합니다."""
        if self.just_selected: self.just_selected = False; return
        if self.debounce_timer: self.after_cancel(self.debounce_timer)
        self.debounce_timer = self.after(300, self._show_autocomplete)  # 300ms 디바운싱

    def _show_autocomplete(self, show_all=False):
        """팝업에 자동완성 목록을 표시합니다."""
        typed_text = self.var.get().lower().strip()

        if show_all:
            filtered = self.completion_list
        else:
            if not typed_text: self._hide_popup(); return
            filtered = [item for item in self.completion_list if typed_text in item.lower()]

        if not filtered: self._hide_popup(); return

        self._listbox.delete(0, tk.END)
        for item in filtered: self._listbox.insert(tk.END, item)

        x, y = self.entry.winfo_rootx(), self.entry.winfo_rooty() + self.entry.winfo_height() + 2
        w = self.entry.winfo_width() + self.arrow_button.winfo_width()
        h = self._listbox.size() * 24 if self._listbox.size() <= 10 else 240

        self._popup_window.geometry(f"{w}x{h}+{x}+{y}")
        if not self._popup_window.winfo_viewable(): self._popup_window.deiconify()
        self._listbox.selection_set(0);
        self._listbox.see(0)

    def _hide_popup(self, event=None):
        if self._popup_window.winfo_viewable():
            self._popup_window.withdraw()

    def _hide_popup_delayed(self, event=None):
        """포커스가 다른 위젯으로 이동할 때 팝업을 닫습니다."""
        self.after(150, self._hide_popup)

    def _handle_return_key(self, event=None):
        """엔터 키 입력 시 항목을 선택합니다."""
        if self._popup_window.winfo_viewable():
            self._select_item_from_key()
        elif self.on_select_callback:
            self.on_select_callback()
        return "break"

    def _select_item_from_click(self, event):
        """마우스 클릭으로 항목을 선택합니다."""
        indices = self._listbox.curselection()
        if indices: self._finalize_selection(indices[0])

    def _select_item_from_key(self):
        """키보드(엔터)로 항목을 선택합니다."""
        indices = self._listbox.curselection()
        if indices: self._finalize_selection(indices[0])

    def _finalize_selection(self, index):
        """[핵심 기능] 선택된 항목으로 값을 설정하고, 포커스를 되돌려 UI 먹통을 방지합니다."""
        value = self._listbox.get(index)
        self.just_selected = True  # 콜백 실행 중 불필요한 재검색 방지
        self.var.set(value)
        self._hide_popup()

        # 메인 윈도우로 포커스를 강제로 되돌려줍니다.
        self.controller.focus_force()

        if self.on_select_callback:
            self.on_select_callback()

    def _move_selection(self, event):
        """키보드 방향키로 팝업 내 선택 항목을 이동합니다."""
        if not self._popup_window.winfo_viewable(): return "break"
        indices = self._listbox.curselection()
        size = self._listbox.size()

        if not indices:
            current_idx = -1
        else:
            current_idx = indices[0]

        next_idx = current_idx + (1 if event.keysym == "Down" else -1)

        if 0 <= next_idx < size:
            self._listbox.selection_clear(0, tk.END)
            self._listbox.selection_set(next_idx);
            self._listbox.see(next_idx)
        return "break"


class StartPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        tk.Label(self, text="리뷰 기반 관광-기업 분석기", font=("Helvetica", 22, "bold")).pack(pady=50)
        tk.Button(self, text="기업 검색", font=("Helvetica", 16), width=20, height=3,
                  command=controller.navigate_to_company_search).pack(pady=15)
        tk.Button(self, text="관광지 검색", font=("Helvetica", 16), width=20, height=3,
                  command=lambda: controller.show_frame("TouristSearchPage")).pack(pady=15)


class CompanySearchPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        # --- 상단 컨트롤 프레임 ---
        top_frame = tk.Frame(self)
        top_frame.pack(pady=10, padx=20, fill='x')

        btn_container = tk.Frame(top_frame)
        btn_container.pack(side='left', padx=(0, 15))
        tk.Button(btn_container, text="< 시작 화면으로", command=lambda: controller.show_frame("StartPage")).pack(side='left')
        self.result_back_button = tk.Button(btn_container, text="< 분석 결과로 돌아가기",
                                            command=lambda: controller.show_frame("ResultPage"))

        tk.Label(top_frame, text="기업 선택:", font=("Helvetica", 12, "bold")).pack(side='left', padx=(0, 10))

        # ▼▼▼ [수정] 개선된 AutocompleteEntry 사용 ▼▼▼
        self.company_entry = AutocompleteEntry(top_frame, controller, font=("Helvetica", 12),
                                               on_select_callback=self.show_company_review)
        self.company_entry.pack(side='left', expand=True, fill='x')
        self.company_var = self.company_entry.var  # 변수 연결
        # ▲▲▲ [수정 완료] ▲▲▲

        ttk.Button(top_frame, text="목록 새로고침", command=self.refresh_data).pack(side='left', padx=(10, 0))

        # --- 하단 결과 표시 영역 (기존과 동일) ---
        self.status_label = tk.Label(self, text="", fg="blue")
        self.status_label.pack(pady=(0, 5))
        main_pane = ttk.PanedWindow(self, orient='vertical')
        main_pane.pack(expand=True, fill='both', padx=20, pady=10)

        summary_frame = ttk.LabelFrame(main_pane, text="종합 평가 요약", padding=10)
        main_pane.add(summary_frame, weight=1)
        self.summary_text = tk.Text(summary_frame, wrap='word', height=8, font=("Helvetica", 11), state='disabled',
                                    bg='#f0f0f0', fg = "black")
        self.summary_text.pack(expand=True, fill='both')

        detail_frame = ttk.LabelFrame(main_pane, text="상세 평가 목록", padding=10)
        main_pane.add(detail_frame, weight=2)
        self.detail_text = tk.Text(detail_frame, wrap='word', font=("Helvetica", 11), state='disabled')
        self.detail_text.pack(expand=True, fill='both')

    def toggle_result_back_button(self, show):
        if show and not self.result_back_button.winfo_ismapped():
            self.result_back_button.pack(side='left', padx=(5, 0))
        elif not show:
            self.result_back_button.pack_forget()

    def update_company_list(self):
        companies = sorted(self.controller.analyzer.company_df['기업명'].unique().tolist())
        self.company_entry.set_completion_list(companies)
        if companies:
            self.company_entry.just_selected = True
            self.company_var.set(companies[0])
            self.show_company_review()

    def refresh_data(self):
        self.status_label.config(text="상태: 구글 시트 정보 새로고침 중...")
        threading.Thread(target=self._refresh_thread, daemon=True).start()

    def _refresh_thread(self):
        self.controller.analyzer.get_company_data_from_sheet()
        self.after(0, self.update_company_list)
        self.after(0, self.status_label.config, {"text": ""})

    def show_company_review(self, event=None):
        company_name = self.company_var.get()
        if not company_name: return

        self.summary_text.config(state='normal');
        self.detail_text.config(state='normal')
        self.summary_text.delete('1.0', tk.END);
        self.detail_text.delete('1.0', tk.END)

        summary_items = {
            "외부 기관 협업 평가": self.controller.analyzer.get_preference_summary(company_name),
            "외부 기관의 평가 요약": self.controller.analyzer.summarize_reviews(
                self.controller.analyzer.get_reviews_by_type(company_name)[0], '외부기관', company_name),
            "동료 입주기업의 평가 요약": self.controller.analyzer.summarize_reviews(
                self.controller.analyzer.get_reviews_by_type(company_name)[1], '입주기업', company_name)
        }

        has_summary = False
        for title, summaries in summary_items.items():
            if summaries:
                self.summary_text.insert(tk.END, f"--- {title} ---\n", "bold")
                self.summary_text.insert(tk.END, "".join([f"• {s}\n" for s in summaries]) + "\n")
                has_summary = True
        if not has_summary: self.summary_text.insert(tk.END, "표시할 평가 요약 정보가 없습니다.")

        ext_rev, peer_rev = self.controller.analyzer.get_reviews_by_type(company_name)
        all_reviews = pd.concat([ext_rev, peer_rev], ignore_index=True)
        if all_reviews.empty:
            self.detail_text.insert(tk.END, "표시할 상세 평가 정보가 없습니다.")
        else:
            for _, row in all_reviews.iterrows():
                self.detail_text.insert(tk.END, f"[작성: {row['평가기관']}]\n", "bold")
                sentiment = self.controller.analyzer.judge_sentiment_by_rating(row.get('평점', 0))
                self.detail_text.insert(tk.END, f"평점: {row.get('평점', 0):.1f}  |  분석: {sentiment}\n")
                self.detail_text.insert(tk.END, f"내용: {row.get('평가내용', '')}\n---------------------------------\n")

        self.summary_text.tag_config("bold", font=("Helvetica", 11, "bold"))
        self.detail_text.tag_config("bold", font=("Helvetica", 11, "bold"))
        self.summary_text.config(state='disabled');
        self.detail_text.config(state='disabled')
        self.controller.focus_set()


class TouristSearchPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        # 상단 헤더
        tk.Button(self, text="< 시작 화면으로", command=lambda: controller.show_frame("StartPage")).pack(side='top',
                                                                                                   anchor='nw', padx=10,
                                                                                                   pady=10)
        tk.Label(self, text="분석할 관광지 이름을 입력하세요.", font=("Helvetica", 14)).pack(pady=10)

        # ▼▼▼ [수정] 개선된 AutocompleteEntry 사용 ▼▼▼
        input_frame = tk.Frame(self);
        input_frame.pack(pady=5, padx=20, fill='x')
        self.spot_entry = AutocompleteEntry(input_frame, controller, font=("Helvetica", 12),
                                            on_select_callback=self._focus_on_analyze_button)
        self.spot_entry.pack(expand=True, fill='x')
        # ▲▲▲ [수정 완료] ▲▲▲

        # 분석 컨트롤
        ctrl_frame = tk.Frame(self);
        ctrl_frame.pack(pady=10)
        tk.Label(ctrl_frame, text="Google 리뷰 수:", font=("Helvetica", 11)).pack(side='left')
        self.review_count_var = tk.StringVar(value='50')
        ttk.Combobox(ctrl_frame, textvariable=self.review_count_var, values=[10, 20, 50, 100, 200], width=5,
                     state="readonly").pack(side='left', padx=5)
        self.analyze_button = tk.Button(ctrl_frame, text="분석 시작", font=("Helvetica", 14, "bold"),
                                        command=self.start_analysis)
        self.analyze_button.pack(side='left', padx=10)

        # 하단 상태 표시줄
        status_frame = tk.Frame(self);
        status_frame.pack(fill='x', padx=20, pady=(5, 10), side='bottom')
        self.status_label = tk.Label(status_frame, text="상태: 대기 중", font=("Helvetica", 10))
        self.status_label.pack()
        self.progress_bar = ttk.Progressbar(status_frame, orient='horizontal', mode='determinate')

    def _focus_on_analyze_button(self): self.analyze_button.focus_set()

    def update_autocomplete_list(self, spot_list):
        spot_names = sorted([spot['title'] for spot in spot_list if spot and spot.get('title')])
        self.spot_entry.set_completion_list(spot_names)
        self.status_label.config(text=f"상태: 대기 중 ({len(spot_names)}개 관광지 로드 완료)")

    def start_analysis(self):
        spot_name = self.spot_entry.var.get()
        if not spot_name: messagebox.showwarning("입력 오류", "분석할 관광지 이름을 입력해주세요."); return
        self.controller.start_full_analysis(spot_name, int(self.review_count_var.get()))

    def analysis_start_ui(self, spot_name):
        self.status_label.config(text=f"'{spot_name}' 분석을 시작합니다...");
        self.progress_bar.pack(fill='x', pady=5)
        self.analyze_button.config(state='disabled')

    def update_progress_ui(self, value, message):
        self.progress_bar['value'] = value;
        self.status_label.config(text=message)

    def analysis_complete_ui(self):
        self.progress_bar.pack_forget();
        self.analyze_button.config(state='normal')
        self.status_label.config(text="분석 완료! 결과 페이지로 이동합니다.");
        self.spot_entry.var.set("")

    def analysis_fail_ui(self, error_message):
        messagebox.showerror("분석 오류", error_message);
        self.progress_bar.pack_forget()
        self.analyze_button.config(state='normal');
        self.status_label.config(text="분석 실패")


class ResultPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        header_frame = tk.Frame(self);
        header_frame.pack(fill='x', pady=10, padx=10)
        tk.Button(header_frame, text="< 관광지 검색으로", command=lambda: controller.show_frame("TouristSearchPage")).pack(
            side='left')
        self.title_label = tk.Label(header_frame, text="", font=("Helvetica", 18, "bold"));
        self.title_label.pack(side='left', padx=20)
        tk.Button(header_frame, text="리뷰 텍스트로 내보내기 💾", command=self.export_reviews_to_txt).pack(side='right')

        canvas = tk.Canvas(self);
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.scrollable_frame = ttk.Frame(canvas)
        self.scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True, padx=10);
        scrollbar.pack(side="right", fill="y")

    def export_reviews_to_txt(self):
        result = self.controller.analysis_result
        if not result or 'classified_reviews' not in result: messagebox.showwarning("내보내기 오류", "결과 없음"); return
        spot_name = result.get('spot_name', 'untitle_reviews')
        safe_name = "".join(c for c in spot_name if c.isalnum() or c in ' _-').rstrip()

        filepath = filedialog.asksaveasfilename(defaultextension=".txt", initialfile=f"{safe_name}_리뷰.txt",
                                                title="리뷰 저장")
        if not filepath: return

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(f"--- '{spot_name}' 관광지 리뷰 데이터 ---\n\n")
                for review_data in result['classified_reviews']:
                    text = review_data.get('review', '').strip().replace('\n', ' ')
                    if text: f.write(f"{text}\n")
            messagebox.showinfo("저장 완료", f"리뷰를 성공적으로 저장했습니다.\n경로: {filepath}")
        except Exception as e:
            messagebox.showerror("파일 저장 오류", f"파일 저장 중 오류 발생:\n{e}")

    def update_results(self):
        for widget in self.scrollable_frame.winfo_children(): widget.destroy()
        result = self.controller.analysis_result
        if not result: return

        self.title_label.config(text=f"'{result.get('spot_name', '')}' 분석 결과")

        if result.get('recommended_companies'):
            frame = ttk.LabelFrame(self.scrollable_frame, text=f"🏫 '{result.get('best_category')}' 연관 기업 추천",
                                   padding=10)
            frame.pack(fill='x', padx=10, pady=10, anchor='n')
            for name in result['recommended_companies']:
                link = tk.Label(frame, text=f"  - {name}", font=("Helvetica", 12, "underline"), fg="blue",
                                cursor="hand2")
                link.pack(anchor='w', pady=3)
                link.bind("<Button-1>", lambda e, n=name: self.controller.navigate_to_company_details_from_result(n))

        frame = ttk.LabelFrame(self.scrollable_frame, text="💬 리뷰 카테고리 분류 결과", padding=10)
        frame.pack(fill='x', padx=10, pady=10, anchor='n')
        for cat, count in Counter(r['category'] for r in result['classified_reviews']).most_common():
            f = tk.Frame(frame);
            f.pack(fill='x', pady=5)
            tk.Label(f, text=f"● {cat}: {count}개", font=("Helvetica", 14)).pack(side='left')
            tk.Button(f, text="상세 리뷰 보기", command=lambda c=cat: self.show_details(c)).pack(side='right')

    def show_details(self, category):
        self.controller.frames["DetailPage"].update_details(category)
        self.controller.show_frame("DetailPage")


class DetailPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        header_frame = tk.Frame(self);
        header_frame.pack(fill='x', pady=10, padx=10)
        tk.Button(header_frame, text="< 분석 결과로", command=lambda: controller.show_frame("ResultPage")).pack(side='left')
        self.title_label = tk.Label(header_frame, text="", font=("Helvetica", 16, "bold"));
        self.title_label.pack(side='left', padx=10)

        text_frame = tk.Frame(self);
        text_frame.pack(pady=10, padx=20, fill='both', expand=True)
        self.text_area = tk.Text(text_frame, wrap='word', font=("Helvetica", 12))
        scrollbar = tk.Scrollbar(text_frame, command=self.text_area.yview)
        self.text_area.config(yscrollcommand=scrollbar.set, state='disabled')
        scrollbar.pack(side='right', fill='y');
        self.text_area.pack(side='left', fill='both', expand=True)

    def update_details(self, category):
        result = self.controller.analysis_result
        self.title_label.config(text=f"[{category}] 상세 리뷰 목록")
        self.text_area.config(state='normal');
        self.text_area.delete(1.0, 'end')

        filtered = [r for r in result['classified_reviews'] if r.get('category') == category]
        for i, r in enumerate(filtered, 1):
            self.text_area.insert('end', f"--- 리뷰 {i} (출처: {r.get('source', '알 수 없음')}) ---\n", "gray_tag")
            self.text_area.insert('end', f"{r.get('review', '내용 없음').strip()}\n\n")

        self.text_area.tag_config("gray_tag", foreground="gray")
        self.text_area.config(state='disabled')


# ------------------- 메인 애플리케이션 클래스 (컨트롤러) -------------------
class TouristApp(tk.Tk):
    def __init__(self, api_keys, paths):
        super().__init__()
        self.withdraw()  # 로딩 중 메인 윈도우 숨기기
        self.title("관광-기업 연계 분석기");
        self.geometry("800x650")
        font.nametofont("TkDefaultFont").configure(family="Helvetica", size=12)

        try:
            import torch
            self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        except ImportError:
            self.device = 'cpu'
        print(f"--- 실행 장치(Device)가 '{self.device}'로 설정되었습니다. ---")

        self.analyzer = ReviewAnalyzer(api_keys, paths)
        self.analysis_result = {}

        container = tk.Frame(self);
        container.pack(side="top", fill="both", expand=True)
        container.grid_rowconfigure(0, weight=1);
        container.grid_columnconfigure(0, weight=1)

        self.frames = {}
        for F in (StartPage, CompanySearchPage, TouristSearchPage, ResultPage, DetailPage):
            frame = F(parent=container, controller=self)
            self.frames[F.__name__] = frame;
            frame.grid(row=0, column=0, sticky="nsew")

        self.show_frame("StartPage")
        # UI가 렌더링될 시간을 준 후, 로딩 팝업을 띄우고 백그라운드 작업을 시작합니다.
        self.after(100, self.show_popup_and_prepare_loading)

    def show_popup_and_prepare_loading(self):
        """로딩 팝업을 생성하고, 리소스 로딩 스레드를 시작합니다."""
        self.create_loading_popup()
        # 팝업이 확실히 그려진 후 스레드를 시작하도록 짧은 딜레이를 줍니다.
        self.after(50, self.load_initial_resources)

    def create_loading_popup(self):
        """시각적으로 보기 좋은 로딩 팝업창을 생성합니다."""
        self.loading_popup = tk.Toplevel(self)
        self.loading_popup.title("로딩 중")
        self.loading_popup.resizable(False, False)
        # 사용자가 닫지 못하게 설정
        self.loading_popup.protocol("WM_DELETE_WINDOW", lambda: None)
        # 메인 창 위에 항상 떠 있도록 설정
        self.loading_popup.transient(self)
        self.loading_popup.grab_set()

        # 화면 중앙에 위치시키기
        w, h = 400, 150
        x = (self.winfo_screenwidth() // 2) - (w // 2)
        y = (self.winfo_screenheight() // 2) - (h // 2)
        self.loading_popup.geometry(f'{w}x{h}+{x}+{y}')

        tk.Label(self.loading_popup, text="프로그램을 준비하고 있습니다...", font=("Helvetica", 14, "bold")).pack(pady=20)
        self.loading_status_label = tk.Label(self.loading_popup, text="초기화 중...", font=("Helvetica", 10))
        self.loading_status_label.pack(pady=5)
        self.loading_progress_bar = ttk.Progressbar(self.loading_popup, orient='horizontal', length=300,
                                                    mode='determinate')
        self.loading_progress_bar.pack(pady=10)
        self.loading_popup.update_idletasks()  # 팝업 즉시 그리기

    def close_loading_popup(self):
        """로딩 팝업을 닫고 메인 윈도우를 활성화합니다."""
        if hasattr(self, 'loading_popup') and self.loading_popup.winfo_exists():
            self.loading_popup.grab_release()
            self.loading_popup.destroy()
        # 숨겨뒀던 메인 윈도우를 보여주고 포커스를 줍니다.
        self.deiconify()
        self.lift()
        self.focus_force()

    def load_initial_resources(self):
        """백그라운드 스레드를 시작하여 리소스를 로드합니다."""
        threading.Thread(target=self._load_resources_thread, daemon=True).start()

    def _load_resources_thread(self):
        """[백그라운드 실행] 시간이 오래 걸리는 모든 작업을 여기서 처리합니다."""

        # UI 업데이트는 메인 스레드에서 안전하게 실행되도록 self.after를 사용합니다.
        def update_popup(progress, message):
            self.loading_progress_bar['value'] = progress
            self.loading_status_label.config(text=message)

        try:
            # 1단계: 관광지 목록 로딩
            self.after(0, update_popup, 20, "자동완성용 관광지 목록 로딩 중...")
            spots = self.analyzer.get_tourist_spots_in_busan()
            self.frames["TouristSearchPage"].update_autocomplete_list(spots)

            # 2단계: AI 모델 로딩 (지연 import)
            self.after(0, update_popup, 50, f"AI 분석 모델 로딩 중... (장치: {self.device})")
            from sentence_transformers import SentenceTransformer
            self.analyzer.sbert_model = SentenceTransformer('jhgan/ko-sroberta-multitask', device=self.device)
            self.analyzer.category_embeddings = {cat: self.analyzer.sbert_model.encode(kw, convert_to_tensor=True)
                                                 for cat, kw in self.analyzer.CATEGORIES.items()}
            print("--- AI SBERT 모델 및 카테고리 임베딩 로딩 완료 ---")

            # 3단계: 기업 정보 AI 기반 분류
            self.after(0, update_popup, 80, "기업 정보 분석 및 분류 중...")
            self.analyzer.classify_all_companies()

            self.after(0, update_popup, 100, "준비 완료!")
            # 로딩 완료 후 0.5초 뒤 팝업을 닫아 사용자가 완료 메시지를 볼 시간을 줍니다.
            self.after(500, self.close_loading_popup)
        except Exception as e:
            msg = f"프로그램 준비 중 오류가 발생했습니다.\n\n오류: {e}"
            # 에러 발생 시 안전하게 메인 스레드에서 메시지박스를 띄웁니다.
            self.after(0, self._show_error_message_safely, "초기화 오류", msg)

    def _show_error_message_safely(self, title, message):
        """메인 스레드에서 안전하게 에러 메시지 팝업을 띄우고 프로그램을 종료합니다."""
        self.close_loading_popup()
        messagebox.showerror(title, message)
        self.destroy()

    def start_full_analysis(self, spot_name, review_count):
        threading.Thread(target=self._analysis_thread, args=(spot_name, review_count), daemon=True).start()

    def _analysis_thread(self, spot_name, review_count):
        page = self.frames["TouristSearchPage"]
        try:
            self.after(0, page.analysis_start_ui, spot_name)
            steps, total_steps = 0, 4  # 단계 추가 (ID탐색 2개, 리뷰수집 2개)

            def update(msg):
                nonlocal steps;
                steps += 1
                self.after(0, page.update_progress_ui, (steps / total_steps) * 100, msg)

            update("1/4: 리뷰 수집을 위한 ID 탐색 중...")
            trip_id = self.analyzer.get_location_id_from_tripadvisor(spot_name)
            google_id = self.analyzer.get_google_place_id_via_serpapi(spot_name)

            update("2/4: TripAdvisor 및 Google 리뷰 수집 중...")
            trip_reviews = self.analyzer.get_tripadvisor_reviews(trip_id)
            google_reviews = self.analyzer.get_google_reviews_via_serpapi(google_id, review_count)
            all_reviews = trip_reviews + google_reviews

            if not all_reviews:
                self.after(0, page.analysis_fail_ui, f"'{spot_name}'에 대한 리뷰를 찾을 수 없습니다.")
                return

            update("3/4: AI 모델로 리뷰 분류 중...")
            classified = self.analyzer.classify_reviews(all_reviews)
            if not classified:
                self.after(0, page.analysis_fail_ui, "리뷰 카테고리 분류에 실패했습니다.")
                return

            update("4/4: 결과 처리 및 기업 추천 중...")
            # '기타'를 제외한 가장 빈번한 카테고리 찾기
            category_counts = Counter(r['category'] for r in classified if r['category'] != '기타')
            best_cat = category_counts.most_common(1)[0][0] if category_counts else "기타"

            self.analysis_result = {
                'spot_name': spot_name,
                'best_category': best_cat,
                'classified_reviews': classified,
                'recommended_companies': self.analyzer.recommend_companies(best_cat)
            }

            self.after(0, page.analysis_complete_ui)
            self.after(200, lambda: self.show_frame("ResultPage"))

        except Exception as e:
            import traceback
            traceback.print_exc()  # 터미널에 상세 오류 출력
            self.after(0, page.analysis_fail_ui, f"분석 중 오류 발생: {e}")

    def show_frame(self, page_name):
        frame = self.frames[page_name]
        if page_name == "CompanySearchPage" and not frame.company_var.get(): frame.update_company_list()
        if page_name == "ResultPage": frame.update_results()
        frame.tkraise()

    def navigate_to_company_search(self):
        self.frames["CompanySearchPage"].toggle_result_back_button(show=False)
        self.show_frame("CompanySearchPage")

    def navigate_to_company_details_from_result(self, company_name):
        page = self.frames["CompanySearchPage"]
        page.toggle_result_back_button(show=True)
        page.company_var.set(company_name)
        page.show_company_review()
        self.show_frame("CompanySearchPage")

    def _show_error_message_safely(self, title, message):
        self.close_loading_popup()
        messagebox.showerror(title, message)
        self.destroy()


# ------------------- 프로그램 시작점 -------------------
if __name__ == "__main__":
    # 라이브러리 존재 여부 최종 확인
    try:
        import pandas, gspread, serpapi, oauth2client
    except ImportError as e:
        # Tkinter는 기본 라이브러리이므로 이 시점에서 사용 가능
        root = tk.Tk()
        root.withdraw()  # 메인 창은 필요 없으므로 숨김
        messagebox.showerror("라이브러리 오류", f"필수 라이브러리가 설치되지 않았습니다: {e.name}\n\n'pip install {e.name}' 명령어로 설치해주세요.")
        sys.exit()

    # 설정 파일 로드
    try:
        config = configparser.ConfigParser()
        config.read(resource_path('config.ini'), encoding='utf-8')
        api_keys = dict(config.items('API_KEYS'))
        paths = dict(config.items('PATHS'))
    except Exception as e:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("설정 오류", f"config.ini 파일 로드에 실패했습니다.\n파일이 실행파일과 같은 위치에 있는지 확인해주세요.\n\n오류: {e}")
        sys.exit()

    app = TouristApp(api_keys, paths)
    app.mainloop()