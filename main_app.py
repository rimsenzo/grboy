import tkinter as tk
from tkinter import ttk, messagebox, font
import threading
import requests
import json
import warnings
import configparser
import os
import time
from collections import Counter
import sys

# AI 모델 관련 라이브러리
from sentence_transformers import SentenceTransformer, util
import torch

# 외부 API 라이브러리
from serpapi import GoogleSearch
import gspread
import pandas as pd
from oauth2client.service_account import ServiceAccountCredentials


# --- [핵심] .exe 환경을 위한 절대 경로 변환 함수 ---
def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


# 경고 메시지 무시
warnings.filterwarnings("ignore", category=UserWarning, message=".*pkg_resources is deprecated.*")
warnings.filterwarnings('ignore', message='Unverified HTTPS request')


# ------------------- 백엔드 로직: ReviewAnalyzer 클래스 -------------------
class ReviewAnalyzer:
    def __init__(self, api_keys, paths):
        # API 키 및 경로 초기화
        self.KOREA_TOUR_API_KEY = api_keys['korea_tour_api_key']
        self.TRIPADVISOR_API_KEY = api_keys['tripadvisor_api_key']
        self.SERPAPI_API_KEY = api_keys['serpapi_api_key']

        self.KOREA_TOUR_API_URL = "http://apis.data.go.kr/B551011/KorService2/areaBasedList2"
        self.TRIPADVISOR_API_URL = "https://api.content.tripadvisor.com/api/v1"

        self.paths = paths
        self.GOOGLE_SHEET_KEY_FILENAME = self.paths['google_sheet_key_path']

        self.scopes = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']

        # 구글 시트 데이터 로딩
        self.company_df, self.review_df = self.get_company_data_from_sheet()

        # 카테고리 정의
        self.CATEGORIES = {
            'K-문화': ['K팝', 'K드라마', '영화 촬영지', '한류', '부산국제영화제', 'BIFF', '아이돌', '팬미팅', 'SNS', '인스타그램', '핫플레이스', '슬램덩크'],
            '해양': ['바다', '해변', '해수욕장', '해안', '항구', '섬', '등대', '요트', '해상케이블카', '스카이캡슐', '해변열차', '파도', '수족관', '서핑',
                   '스카이워크'],
            '웰니스': ['힐링', '휴식', '스파', '사우나', '온천', '족욕', '마사지', '산책', '자연', '평화', '평온', '치유', '고요함', '명상', '건강'],
            '뷰티': ['미용', '헤어', '피부', '메이크업', '네일', '에스테틱', '피부관리', '뷰티서비스', '마사지', '미용실', '헤어샵', '네일샵', '살롱', '화장품',
                   'K-뷰티', '퍼스널컬러', '스타일링', '시술', '페이셜'],
            'e스포츠': ['e스포츠', '게임', 'PC방', '대회', '경기장', '프로게이머', '리그오브레전드', 'LCK', '스타크래프트', '페이커', '이스포츠'],
            '미식': ['맛집', '음식', '레스토랑', '카페', '해산물', '길거리 음식', '시장', '회', '조개구이', '돼지국밥', '디저트', '식도락']
        }

    def get_company_data_from_sheet(self):
        print("\n--- Google Sheets 데이터 로딩 시작 ---")
        empty_dfs = (pd.DataFrame(), pd.DataFrame())

        # [추가] 재시도 로직을 위한 설정
        MAX_RETRIES = 3  # 최대 3번까지 재시도
        RETRY_DELAY = 5  # 재시도 전 5초 대기

        for attempt in range(MAX_RETRIES):
            try:
                # 1. 인증 및 스프레드시트 열기 (기존과 동일)
                creds = ServiceAccountCredentials.from_json_keyfile_name(resource_path(self.GOOGLE_SHEET_KEY_FILENAME),
                                                                         self.scopes)
                gc = gspread.authorize(creds)
                spreadsheet = gc.open(self.paths['spreadsheet_name'])

                # 2. '기업 정보' 시트 로딩
                print("--- '기업 정보' 시트 로딩 중... ---")
                company_sheet = spreadsheet.worksheet(self.paths['company_sheet_name'])
                company_values = company_sheet.get_all_values()
                if not company_values or len(company_values) < 2: return empty_dfs
                company_df = pd.DataFrame(company_values[1:], columns=company_values[0])
                if '' in company_df.columns: company_df = company_df.drop(columns=[''])

                # 3. '리뷰' 시트 로딩
                print("--- '리뷰' 시트 로딩 중... ---")
                review_sheet = spreadsheet.worksheet(self.paths['review_sheet_name'])
                review_values = review_sheet.get_all_values()
                if not review_values or len(review_values) < 2: return empty_dfs
                review_df = pd.DataFrame(review_values[1:], columns=review_values[0])
                if '' in review_df.columns: review_df = review_df.drop(columns=[''])

                print(f"  - 로딩 완료: 기업 {len(company_df)}개, 리뷰 {len(review_df)}개")

                # 4. 데이터 정제
                if '기업ID' in company_df.columns: company_df['기업ID'] = company_df['기업ID'].astype(
                    str).str.strip().str.lower()
                if '기업ID' in review_df.columns: review_df['기업ID'] = review_df['기업ID'].astype(
                    str).str.strip().str.lower()
                print("  - 데이터 정제 완료: '기업ID' 통일")

                return company_df, review_df  # 성공 시 데이터프레임 반환 및 함수 종료

            except gspread.exceptions.APIError as e:
                # [수정] 503 오류인 경우에만 재시도 로직 실행
                if e.response.status_code == 503 and attempt < MAX_RETRIES - 1:
                    print(f"  - 경고: Google API 503 오류. {RETRY_DELAY}초 후 재시도합니다... ({attempt + 1}/{MAX_RETRIES})")
                    time.sleep(RETRY_DELAY)
                else:  # 503 오류가 아니거나 마지막 시도인 경우, 오류 메시지 표시 후 종료
                    messagebox.showerror("구글 시트 오류", f"데이터 로드에 실패했습니다 (API 오류).\n\n오류: {e}")
                    return empty_dfs
            except Exception as e:
                messagebox.showerror("구글 시트 오류", f"구글 시트 데이터 로드에 실패했습니다.\n\n오류: {e}")
                return empty_dfs

        return empty_dfs  # 모든 재시도 실패 시 빈 데이터프레임 반환

    def get_detailed_reviews_for_company(self, company_id):
        if self.review_df.empty or '기업ID' not in self.review_df.columns: return pd.DataFrame()
        clean_company_id = str(company_id).strip().lower()
        return self.review_df[self.review_df['기업ID'] == clean_company_id].copy()

    def judge_sentiment_by_rating(self, rating):
        try:
            score = float(rating)
            return "긍정 😊" if score >= 4 else "중립 😐" if score >= 3 else "부정 😠"
        except (ValueError, TypeError):
            return "정보 없음"

    def summarize_sentiment_by_evaluator(self, reviews_df, company_name):
        if reviews_df.empty or '평가기관' not in reviews_df.columns: return []
        summary_list = []
        for evaluator, group in reviews_df.groupby('평가기관'):
            positive_count = sum(1 for rating in group['평점'] if "긍정" in self.judge_sentiment_by_rating(rating))
            if len(group) > 0:
                ratio = (positive_count / len(group)) * 100
                summary_list.append(f"'{evaluator}'의 {ratio:.1f}%가 '{company_name}'을 긍정적으로 평가합니다.")
        return summary_list

    def get_tourist_spots_in_busan(self):
        all_spots = []
        # 중복된 장소를 title 기준으로 걸러내기 위한 집합
        seen_titles = set()
        content_type_ids = ['12']
        print(f"\n--- 부산 관광정보 수집 시작 (타입: {content_type_ids}) ---")

        for content_type_id in content_type_ids:
            try:
                params = {
                    'serviceKey': self.KOREA_TOUR_API_KEY,
                    'numOfRows': 500,  # 각 타입별로 충분히 많은 데이터를 요청
                    'pageNo': 1,
                    'MobileOS': 'ETC',
                    'MobileApp': 'AppTest',
                    '_type': 'json',
                    'areaCode': 6,  # 부산
                    'contentTypeId': content_type_id
                }
                # 네트워크 타임아웃을 15초로 늘려 안정성 확보
                response = requests.get(self.KOREA_TOUR_API_URL, params=params, timeout=15)

                if response.status_code != 200:
                    print(f"  - API 오류: 타입 ID={content_type_id}, 상태 코드={response.status_code}")
                    continue

                items = response.json().get('response', {}).get('body', {}).get('items', {}).get('item', [])

                if items:
                    count = 0
                    for item in items:
                        title = item.get('title')
                        # title이 있고, 이전에 추가된 적 없는 장소만 추가
                        if title and title not in seen_titles:
                            seen_titles.add(title)
                            all_spots.append({'title': title, 'addr1': item.get('addr1', '')})
                            count += 1
                    print(f"  - 타입 ID '{content_type_id}'에서 {count}개의 신규 장소 추가됨")

            except requests.exceptions.RequestException as e:
                print(f"  - API 요청 실패 (타입 ID: {content_type_id}): {e}")
                continue  # 하나의 타입에서 오류가 나도 다음 타입 조회를 계속 시도
            except Exception as e:
                print(f"  - 데이터 처리 중 오류 발생 (타입 ID: {content_type_id}): {e}")
                continue

        print(f"--- 총 {len(all_spots)}개의 고유한 관광지 정보를 수집했습니다. ---")
        return all_spots

    def get_location_id_from_tripadvisor(self, spot_name):
        try:
            params = {'key': self.TRIPADVISOR_API_KEY, 'searchQuery': spot_name, 'language': 'ko'}
            response = requests.get(f"{self.TRIPADVISOR_API_URL}/location/search", params=params,
                                    headers={'accept': 'application/json'}, timeout=10)
            data = response.json().get('data', [])
            return data[0].get('location_id') if data else None
        except Exception:
            return None

    def get_google_place_id_via_serpapi(self, spot_name):
        precise_query = f"{spot_name}, 부산"
        print(f"\n--- Google Place ID 탐색 시작 (정밀 검색어: '{precise_query}') ---")

        # 1순위: 'google' 웹 검색 엔진을 통해 Knowledge Panel에서 Place ID 탐색 (가장 신뢰도 높음)
        try:
            print("  - [1단계] Knowledge Panel에서 Place ID를 탐색합니다.")
            params = {
                "engine": "google",
                "q": precise_query,
                "api_key": self.SERPAPI_API_KEY,
                "hl": "ko"
            }
            search = GoogleSearch(params)
            results = search.get_dict()

            if "knowledge_graph" in results:
                place_id = results.get("knowledge_graph", {}).get("place_id")
                if place_id:
                    print(f"  - 성공 (Knowledge Panel): Place ID '{place_id}'를 찾았습니다.")
                    return place_id
            print("  - 정보: Knowledge Panel에서 Place ID를 찾지 못했습니다. 2단계로 넘어갑니다.")

        except Exception as e:
            print(f"  - 경고: Knowledge Panel 탐색 중 오류 발생 ({e}). 2단계로 넘어갑니다.")

        # 2순위: 1단계 실패 시, 'google_maps' 엔진으로 재시도
        try:
            print("  - [2단계] Google Maps API에서 Place ID를 탐색합니다.")
            params = {
                "engine": "google_maps",
                "q": precise_query,
                "api_key": self.SERPAPI_API_KEY,
                "hl": "ko"
            }
            search = GoogleSearch(params)
            results = search.get_dict()

            if "local_results" in results and results["local_results"]:
                place_id = results["local_results"][0].get("place_id")
                if place_id:
                    print(f"  - 성공 (Maps Local): Place ID '{place_id}'를 찾았습니다.")
                    return place_id

            # [핵심 수정] 'data_id'가 아닌 'place_id'를 올바르게 사용합니다.
            if "place_results" in results:
                place_id = results.get('place_results', {}).get("place_id")
                if place_id:
                    print(f"  - 성공 (Maps Place): Place ID '{place_id}'를 찾았습니다.")
                    return place_id

            print(f"  - 최종 실패: API 응답에서 유효한 Place ID를 찾지 못했습니다.")
            return None

        except Exception as e:
            print(f"  - 최종 실패: Maps API 탐색 중 예외 발생: {e}")
            return None

    def get_tripadvisor_reviews(self, location_id):
        if not location_id: return []
        try:
            params = {'key': self.TRIPADVISOR_API_KEY}
            response = requests.get(f"{self.TRIPADVISOR_API_URL}/location/{location_id}/reviews", params=params,
                                    headers={'accept': 'application/json'}, timeout=10)
            return [{'source': 'TripAdvisor', 'text': r['text']} for r in response.json().get('data', []) if
                    r.get('text')]
        except Exception:
            return []

    def get_google_reviews_via_serpapi(self, place_id, review_count=50):
        print(f"\n--- Google 리뷰 수집 시작 (Place ID: {place_id}, 목표 개수: {review_count}) ---")
        if not place_id:
            print("  - 오류: Place ID가 없어 리뷰를 수집할 수 없습니다.")
            return []

        all_reviews_data = []

        # 첫 페이지 요청을 위한 파라미터 설정
        params = {
            "engine": "google_maps_reviews",
            "place_id": place_id,
            "hl": "ko",
            "api_key": self.SERPAPI_API_KEY
        }

        search = GoogleSearch(params)

        # 목표 개수에 도달하거나, 다음 페이지가 없을 때까지 반복
        while True:
            try:
                results = search.get_dict()

                if "error" in results:
                    print(f"  - SerpApi 오류 발생: {results['error']}")
                    break

                reviews = results.get("reviews", [])
                if reviews:
                    all_reviews_data.extend(reviews)
                    print(f"  - 리뷰 {len(reviews)}개를 추가했습니다. (총 {len(all_reviews_data)}개 수집)")
                else:
                    print("  - 현재 페이지에 더 이상 리뷰가 없어 수집을 중단합니다.")
                    break

                if len(all_reviews_data) >= review_count:
                    print(f"  - 목표 리뷰 개수({review_count}개) 이상을 수집하여 종료합니다.")
                    break

                pagination = results.get("serpapi_pagination")
                if pagination and "next_page_token" in pagination:
                    print("  -> 다음 페이지가 존재합니다. 계속 진행합니다.")

                    # [핵심 수정] 다음 페이지 요청을 위해 next_page_token만 추가합니다.
                    # place_id는 절대 제거하지 않습니다.
                    search.params_dict['next_page_token'] = pagination['next_page_token']
                else:
                    print("  -> 다음 페이지가 없습니다. 리뷰 수집을 완료합니다.")
                    break

            except Exception as e:
                print(f"  - 리뷰 수집 중 심각한 예외 발생: {e}")
                break

        # 최종적으로 목표 개수에 맞춰 리뷰를 잘라내고, 텍스트만 추출
        final_reviews = all_reviews_data[:review_count]
        extracted_reviews = [{'source': 'Google', 'text': r.get('snippet', '')} for r in final_reviews if
                             r.get('snippet')]

        print(f"  - 최종적으로 내용이 있는 리뷰 {len(extracted_reviews)}개를 성공적으로 추출했습니다.")
        return extracted_reviews

    def classify_reviews(self, all_reviews, model, category_embeddings, threshold=0.4):
        classified_results = []
        for review_data in all_reviews:
            review_text = review_data.get('text', '')
            if not review_text.strip(): continue
            review_embedding = model.encode(review_text, convert_to_tensor=True)
            scores = {cat: util.cos_sim(review_embedding, emb).max().item() for cat, emb in category_embeddings.items()}
            best_category = max(scores, key=scores.get) if scores and scores[
                max(scores, key=scores.get)] >= threshold else '기타'
            classified_results.append(
                {'review': review_text, 'source': review_data.get('source', '알 수 없음'), 'category': best_category})
        return classified_results

    def classify_all_companies(self, model, category_embeddings):
        """
        [신규] 모든 기업의 '사업내용'을 AI 모델로 분석하여 카테고리와 유사도 점수를 매깁니다.
        이 함수는 프로그램 시작 시 한 번만 호출됩니다.
        """
        if self.company_df.empty or '사업내용' not in self.company_df.columns:
            print("--- 기업 정보가 없어 분류를 건너뜁니다. ---")
            return

        print("\n--- 전체 기업 데이터 AI 기반 사전 분류 시작 ---")

        # NaN 값을 빈 문자열로 대체하여 오류 방지
        self.company_df['사업내용'] = self.company_df['사업내용'].fillna('')
        business_texts = self.company_df['사업내용'].tolist()

        # GPU/CPU 장치에 맞춰 텐서로 변환하여 계산
        business_embeddings = model.encode(business_texts, convert_to_tensor=True)

        categories = []
        scores = []

        # 각 사업내용과 카테고리 임베딩 간 유사도 계산
        for emb in business_embeddings:
            sim_scores = {cat: util.cos_sim(emb, cat_emb).max().item() for cat, cat_emb in category_embeddings.items()}

            if not sim_scores:  # 유사도 계산 불가 시
                categories.append('기타')
                scores.append(0)
                continue

            best_cat = max(sim_scores, key=sim_scores.get)
            best_score = sim_scores[best_cat]

            categories.append(best_cat)
            scores.append(best_score)

        # 결과를 데이터프레임의 새 컬럼으로 추가
        self.company_df['best_category'] = categories
        self.company_df['category_score'] = scores

        print(f"--- 기업 분류 완료: {len(self.company_df)}개 기업에 카테고리 및 점수 부여 완료 ---")

    def recommend_companies(self, category, top_n=5):
        """
        [수정] 사전 분류된 기업 목록에서 특정 카테고리와 일치하는 기업을
        유사도 점수가 높은 순으로 정렬하여 상위 n개를 추천합니다.
        """
        if self.company_df.empty or 'best_category' not in self.company_df.columns:
            return []

        # 해당 카테고리로 분류된 기업들을 필터링
        recommended_df = self.company_df[self.company_df['best_category'] == category].copy()

        # 'category_score' 기준으로 내림차순 정렬
        recommended_df.sort_values(by='category_score', ascending=False, inplace=True)

        # 상위 N개의 기업명만 리스트로 반환
        return recommended_df.head(top_n)['기업명'].tolist()


# ------------------- 프론트엔드 UI 페이지들 -------------------
class StartPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        tk.Label(self, text="리뷰 기반 관광-기업 분석기", font=("Helvetica", 22, "bold")).pack(pady=50)
        tk.Button(self, text="기업 검색", font=("Helvetica", 16), width=20, height=3,
                  command=lambda: controller.show_frame("CompanySearchPage")).pack(pady=15)
        tk.Button(self, text="관광지 검색", font=("Helvetica", 16), width=20, height=3,
                  command=lambda: controller.show_frame("TouristSearchPage")).pack(pady=15)


class CompanySearchPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        header_frame = tk.Frame(self)
        header_frame.pack(fill='x', pady=10, padx=10)

        # --- [수정] 왼쪽 내비게이션 버튼들을 담을 프레임 ---
        left_nav_frame = tk.Frame(header_frame)
        left_nav_frame.pack(side="left")

        tk.Button(left_nav_frame, text="< 시작 화면으로", command=lambda: controller.show_frame("StartPage")).pack(
            anchor='nw')

        # --- [추가] '분석 결과로 돌아가기' 버튼 ---
        tk.Button(left_nav_frame, text="< 분석 결과로 돌아가기",
                  command=lambda: controller.show_frame("ResultPage")).pack(anchor='nw', pady=(5, 0))

        # --- 오른쪽 '새로고침' 버튼 (기존과 동일) ---
        tk.Button(header_frame, text="목록 새로고침 🔃", command=self.refresh_list).pack(side='right')

        tk.Label(self, text="기업을 선택하여 평가를 확인하세요", font=("Helvetica", 18, "bold")).pack(pady=20)

        self.company_var = tk.StringVar()
        self.company_combo = ttk.Combobox(self, textvariable=self.company_var, font=("Helvetica", 14), state="readonly")
        self.company_combo.pack(pady=10, padx=20, fill='x')
        self.company_combo.bind("<<ComboboxSelected>>", self.show_company_review)

        text_frame = tk.Frame(self)
        text_frame.pack(pady=10, padx=20, fill='both', expand=True)

        self.text_area = tk.Text(text_frame, wrap='word', font=("Helvetica", 12), bg="#f0f0f0", fg="black")
        self.text_area.tag_configure("bold", font=("Helvetica", 12, "bold"))
        self.text_area.tag_configure("gray", foreground="gray")

        scrollbar = tk.Scrollbar(text_frame, command=self.text_area.yview)
        self.text_area.config(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.text_area.pack(side='left', fill='both', expand=True)

        def block_input(event): return "break"

        self.text_area.bind("<KeyPress>", block_input)
        self.text_area.bind("<Button>", block_input)

        self.status_label = tk.Label(self, text="", font=("Helvetica", 10))
        self.status_label.pack(pady=(5, 0))

    def show_company_review(self, event=None):
        selected_company_name = self.company_var.get()
        if not selected_company_name: return
        self.text_area.delete(1.0, 'end')
        try:
            company_info = self.controller.analyzer.company_df[
                self.controller.analyzer.company_df['기업명'] == selected_company_name]
            if company_info.empty:
                self.text_area.insert('end', "기업 정보를 찾을 수 없습니다.")
                return

            company_id = company_info['기업ID'].iloc[0]
            reviews_df = self.controller.analyzer.get_detailed_reviews_for_company(company_id)

            summary = self.controller.analyzer.summarize_sentiment_by_evaluator(reviews_df, selected_company_name)
            if summary:
                self.text_area.insert('end', "📊 평가 요약\n", "bold")
                for s in summary: self.text_area.insert('end', f"  - {s}\n")
                self.text_area.insert('end', "\n" + "=" * 50 + "\n\n")

            if reviews_df.empty:
                self.text_area.insert('end', "✅ 등록된 평가 정보가 없습니다.")
            else:
                self.text_area.insert('end', f"상세 평가 ({len(reviews_df)}개)\n\n", "bold")
                for _, row in reviews_df.iterrows():
                    self.text_area.insert('end', f"--- (작성: {row.get('평가기관', '정보 없음')}) ---\n", "gray")
                    self.text_area.insert('end',
                                          f"평점: {row.get('평점', '정보 없음')}  |  분석: {self.controller.analyzer.judge_sentiment_by_rating(row.get('평점'))}\n")
                    self.text_area.insert('end', f"내용: {row.get('평가내용', '내용 없음')}\n\n")
        except Exception as e:
            self.text_area.insert('end', f"⚠️ 리뷰 로딩 오류: {e}")

    def refresh_list(self):
        self.controller.refresh_company_data()

    def update_company_list(self):
        df = self.controller.analyzer.company_df
        self.company_combo['values'] = df['기업명'].tolist() if not df.empty else []
        if self.company_combo['values']: self.company_var.set(self.company_combo['values'][0])
        self.show_company_review()

    def refresh_display(self):
        self.update_company_list()


class TouristSearchPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.spot_names = []  # 전체 관광지 목록을 저장할 리스트

        header_frame = tk.Frame(self)
        header_frame.pack(fill='x', pady=10, padx=10)
        tk.Button(header_frame, text="< 시작 화면으로", command=lambda: controller.show_frame("StartPage")).pack(side='left')

        tk.Label(self, text="관광지를 검색하거나, 아래 목록에서 직접 선택하세요.", font=("Helvetica", 14)).pack(pady=5)

        # --- 상단 입력 및 목록 위젯 (기존과 동일) ---
        input_frame = tk.Frame(self)
        input_frame.pack(pady=5, padx=20, fill='x')
        tk.Label(input_frame, text="관광지 이름:", font=("Helvetica", 12)).pack(side='left', padx=(0, 5))
        self.entry_var = tk.StringVar()
        self.spot_combo = ttk.Combobox(input_frame, textvariable=self.entry_var, font=("Helvetica", 12))
        self.spot_combo.pack(side='left', expand=True, fill='x')
        self.spot_combo.bind('<KeyRelease>', self.check_autocomplete)
        self.spot_combo.bind('<Button-1>', self.show_full_list_on_click)

        list_frame = tk.Frame(self)
        list_frame.pack(pady=10, padx=20, fill='x', expand=False)
        self.listbox = tk.Listbox(list_frame, font=("Helvetica", 12), height=15)
        scrollbar = tk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        self.listbox.config(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.listbox.pack(side="left", fill="both", expand=True)
        self.listbox.insert(tk.END, "  ⏳ 한국관광공사 API에서 목록을 불러오는 중입니다...")
        self.listbox.config(state='disabled')
        self.listbox.bind('<<ListboxSelect>>', self.on_listbox_select)

        # --- [수정] 분석 버튼과 리뷰 개수 설정을 함께 담을 프레임 ---
        analysis_control_frame = tk.Frame(self)
        analysis_control_frame.pack(pady=(5, 0), padx=20)

        self.analyze_button = tk.Button(analysis_control_frame, text="분석 시작", font=("Helvetica", 14, "bold"),
                                        command=self.start_analysis)
        self.analyze_button.pack(side='left', padx=(0, 10))

        # --- [추가] 구글 리뷰 개수 설정 콤보박스 ---
        tk.Label(analysis_control_frame, text="Google 리뷰 수:", font=("Helvetica", 11)).pack(side='left')
        self.review_count_var = tk.StringVar()
        self.review_count_combo = ttk.Combobox(analysis_control_frame, textvariable=self.review_count_var,
                                               values=[10, 20, 50, 100, 200], width=5, font=("Helvetica", 11),
                                               state="readonly")
        self.review_count_combo.set(50)  # 기본값을 50개로 설정
        self.review_count_combo.pack(side='left')

        # --- 하단 상태 표시줄 (기존과 동일) ---
        status_frame = tk.Frame(self)
        status_frame.pack(fill='x', padx=20, pady=(5, 10))
        self.status_label = tk.Label(status_frame, text="", font=("Helvetica", 10))
        self.status_label.pack()
        self.progress_bar = ttk.Progressbar(status_frame, orient='horizontal', mode='determinate')


    def update_list_widgets(self, new_list):
        """콤보박스와 리스트박스를 동시에 업데이트하는 헬퍼 함수"""
        # 리스트박스 업데이트
        self.listbox.delete(0, tk.END)
        for item in new_list:
            self.listbox.insert(tk.END, item)
        # 콤보박스 드롭다운 목록 업데이트
        self.spot_combo['values'] = new_list

    def show_full_list_on_click(self, event):
        """콤보박스를 클릭했을 때, 드롭다운에 항상 전체 목록을 표시합니다."""
        # 현재 필터링된 텍스트와 상관없이, 드롭다운 목록을 전체 목록으로 재설정
        # 이 작업은 tkinter의 기본 드롭다운 이벤트보다 먼저 실행됩니다.
        self.spot_combo['values'] = self.spot_names

    def update_autocomplete_list(self, spot_list):
        """컨트롤러로부터 받은 전체 관광지 목록을 저장하고 위젯에 표시"""
        self.spot_names = sorted([spot['title'] for spot in spot_list if spot and spot.get('title')])

        # [수정] 리스트박스 상태를 정상으로 되돌리고 로딩 메시지 삭제
        self.listbox.config(state='normal')
        self.listbox.delete(0, tk.END)

        self.update_list_widgets(self.spot_names)
        self.status_label.config(text=f"상태: 대기 중 ({len(self.spot_names)}개 관광지 로드 완료)")

    def check_autocomplete(self, event):
        """사용자 입력에 따라 리스트박스와 드롭다운 목록을 실시간 필터링"""
        # 방향키, 엔터, Esc 등 기능 키 입력 시에는 자동완성을 실행하지 않음
        if event.keysym in ("Up", "Down", "Return", "Escape", "Tab"):
            return

        typed_text = self.entry_var.get().lower()

        # 입력된 텍스트가 있으면 필터링, 없으면 전체 목록을 사용
        filtered_list = [name for name in self.spot_names if
                         typed_text in name.lower()] if typed_text else self.spot_names

        # 리스트 위젯들(콤보박스 드롭다운, 리스트박스)을 필터링된 목록으로 업데이트
        self.update_list_widgets(filtered_list)

        # [수정] 사용자가 글자를 입력했을 때 드롭다운 메뉴를 강제로 표시
        if typed_text:
            # after를 사용하여 위젯 업데이트가 끝난 후 이벤트를 발생시켜 안정성을 높임
            self.after(10, lambda: self.spot_combo.event_generate('<Down>'))

    def on_listbox_select(self, event):
        """리스트박스에서 항목을 클릭했을 때, 그 값을 위쪽 입력창에 설정"""
        widget = event.widget
        selected_indices = widget.curselection()
        if selected_indices:
            selected_item = widget.get(selected_indices[0])
            self.entry_var.set(selected_item)

    def start_analysis(self):
        spot_name = self.entry_var.get()
        if not spot_name or spot_name not in self.spot_names:
            messagebox.showwarning("입력 오류", "목록에 있는 관광지를 정확히 선택해주세요.")
            return

        # [수정] 콤보박스에서 선택된 리뷰 개수를 가져옵니다.
        try:
            review_count = int(self.review_count_var.get())
        except (ValueError, TypeError):
            review_count = 50  # 오류 발생 시 기본값 50으로 설정

        # 컨트롤러의 분석 시작 함수에 리뷰 개수를 함께 전달합니다.
        self.controller.start_full_analysis(spot_name, review_count)

    # --- 진행률 표시 UI 제어 함수들 (기존과 동일) ---
    def analysis_start_ui(self, spot_name):
        self.status_label.config(text=f"'{spot_name}' 분석을 시작합니다...")
        # [수정] 프로그레스 바를 status_frame의 하단에 표시
        self.progress_bar.pack(side='bottom', fill='x', pady=(5, 0))
        self.analyze_button.config(state='disabled')

    def update_progress_ui(self, value, message):
        self.progress_bar['value'] = value
        self.status_label.config(text=message)

    def analysis_complete_ui(self):
        self.progress_bar.pack_forget()  # 숨기기
        self.analyze_button.config(state='normal')
        self.status_label.config(text="분석 완료! 결과 페이지로 이동합니다.")

    def analysis_fail_ui(self, error_message):
        messagebox.showerror("분석 오류", error_message)
        self.progress_bar.pack_forget()  # 숨기기
        self.analyze_button.config(state='normal')
        self.status_label.config(text="분석 실패")


class ResultPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        # --- 상단 헤더 프레임 ---
        header_frame = tk.Frame(self)
        header_frame.pack(fill='x', pady=10, padx=10, side='top')  # 명시적으로 위쪽에 고정
        tk.Button(header_frame, text="< 관광지 검색으로", command=lambda: controller.show_frame("TouristSearchPage")).pack(
            side='left')
        self.title_label = tk.Label(header_frame, text="", font=("Helvetica", 18, "bold"))
        self.title_label.pack(side='left', padx=20)

        # --- [수정] 중앙 정렬을 위한 메인 콘텐츠 프레임 ---
        # 이 프레임이 남은 공간을 모두 차지하며(expand=True), 그 안의 내용이 중앙에 보이게 됩니다.
        main_content_frame = tk.Frame(self)
        main_content_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Canvas와 Scrollbar를 새로운 메인 콘텐츠 프레임 안에配置
        canvas = tk.Canvas(main_content_frame)
        scrollbar = ttk.Scrollbar(main_content_frame, orient="vertical", command=canvas.yview)
        self.scrollable_frame = ttk.Frame(canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def update_results(self):
        # 기존 위젯들을 모두 삭제
        for widget in self.scrollable_frame.winfo_children(): widget.destroy()

        result = self.controller.analysis_result
        self.title_label.config(text=f"'{result.get('spot_name', '')}' 분석 결과")

        # --- [수정] 추천 기업 표시 로직 ---
        if result.get('recommended_companies'):
            reco_frame = ttk.LabelFrame(self.scrollable_frame, text=f"🏫 '{result.get('best_category')}' 연관 기업 추천",
                                        padding=10)
            reco_frame.pack(fill='x', padx=10, pady=10, anchor='n')

            # 추천된 기업 목록을 하나씩 버튼으로 만듭니다.
            for company_name in result['recommended_companies']:
                # 클릭 가능한 링크처럼 보이도록 Label 위젯을 사용
                company_link = tk.Label(reco_frame, text=f"  - {company_name}",
                                        font=("Helvetica", 12, "underline"), fg="blue", cursor="hand2")
                company_link.pack(anchor='w', pady=3)

                # Label 클릭 시 컨트롤러의 새 함수를 호출하도록 바인딩
                company_link.bind("<Button-1>",
                                  lambda event, name=company_name: self.controller.show_company_details_from_result(
                                      name))

        # --- 카테고리 분류 결과 표시 로직 (기존과 동일) ---
        cat_frame = ttk.LabelFrame(self.scrollable_frame, text="💬 리뷰 카테고리 분류 결과", padding=10)
        cat_frame.pack(fill='x', padx=10, pady=10, anchor='n')
        category_counts = Counter(r['category'] for r in result['classified_reviews'])
        for category, count in category_counts.most_common():
            f = tk.Frame(cat_frame)
            f.pack(fill='x', pady=5)
            tk.Label(f, text=f"● {category}: {count}개", font=("Helvetica", 14)).pack(side='left')
            tk.Button(f, text="상세 리뷰 보기", command=lambda c=category: self.show_details(c)).pack(side='right')

    def show_details(self, category):
        self.controller.frames["DetailPage"].update_details(category)
        self.controller.show_frame("DetailPage")


class DetailPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        header_frame = tk.Frame(self)
        header_frame.pack(fill='x', pady=10)
        tk.Button(header_frame, text="< 분석 결과로", command=lambda: controller.show_frame("ResultPage")).pack(side='left',
                                                                                                           padx=10)
        self.title_label = tk.Label(header_frame, text="", font=("Helvetica", 16, "bold"))
        self.title_label.pack(side='left')

        text_frame = tk.Frame(self)
        text_frame.pack(pady=10, padx=20, fill='both', expand=True)

        # [수정] 'text_area'를 'self.text_area'로 변경하여 클래스의 인스턴스 변수로 만듭니다.
        self.text_area = tk.Text(text_frame, wrap='word', font=("Helvetica", 12))
        scrollbar = tk.Scrollbar(text_frame, command=self.text_area.yview)
        self.text_area.config(yscrollcommand=scrollbar.set, state='disabled')
        scrollbar.pack(side='right', fill='y')
        self.text_area.pack(side='left', fill='both', expand=True)

    def update_details(self, category):
        result = self.controller.analysis_result
        self.title_label.config(text=f"'{result.get('spot_name', '')}' - [{category}] 리뷰 목록")
        self.text_area.config(state='normal')
        self.text_area.delete(1.0, 'end')
        filtered = [r for r in result['classified_reviews'] if r.get('category') == category]
        for i, r in enumerate(filtered, 1):
            self.text_area.insert('end', f"--- 리뷰 {i} (출처: {r.get('source', '알 수 없음')}) ---\n", "gray")
            self.text_area.insert('end', f"{r.get('review', '내용 없음')}\n\n")
        self.text_area.config(state='disabled')


# ------------------- 메인 애플리케이션 클래스 (컨트롤러) -------------------
class TouristApp(tk.Tk):
    def __init__(self, api_keys, paths):
        super().__init__()
        self.withdraw()  # [추가] 메인 윈도우를 초기에 숨깁니다.

        self.title("관광-기업 연계 분석기")
        self.geometry("800x650")
        font.nametofont("TkDefaultFont").configure(family="Helvetica", size=12)

        # [핵심] 로딩 팝업 생성 및 표시
        self.create_loading_popup()

        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        print(f"--- 실행 장치(Device)가 '{self.device}'로 설정되었습니다. ---")

        self.analyzer = ReviewAnalyzer(api_keys, paths)
        self.sbert_model = None
        self.category_embeddings = None
        self.analysis_result = {}

        container = tk.Frame(self)
        container.pack(side="top", fill="both", expand=True)
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        self.frames = {}
        for F in (StartPage, CompanySearchPage, TouristSearchPage, ResultPage, DetailPage):
            frame = F(parent=container, controller=self)
            self.frames[F.__name__] = frame
            frame.grid(row=0, column=0, sticky="nsew")

        self.show_frame("StartPage")
        self.load_initial_resources()

    def create_loading_popup(self):
        """로딩 상태를 보여주는 팝업 Toplevel 창을 생성하고 중앙에 배치합니다."""
        self.loading_popup = tk.Toplevel(self)
        self.loading_popup.title("로딩 중")
        self.loading_popup.resizable(False, False)
        self.loading_popup.protocol("WM_DELETE_WINDOW", lambda: None)  # 닫기 버튼 비활성화
        self.loading_popup.transient(self)
        self.loading_popup.grab_set()

        popup_width = 400
        popup_height = 150
        x = (self.winfo_screenwidth() // 2) - (popup_width // 2)
        y = (self.winfo_screenheight() // 2) - (popup_height // 2)
        self.loading_popup.geometry(f'{popup_width}x{popup_height}+{x}+{y}')

        tk.Label(self.loading_popup, text="프로그램을 준비하고 있습니다...", font=("Helvetica", 14, "bold")).pack(pady=20)
        self.loading_status_label = tk.Label(self.loading_popup, text="초기화 중...", font=("Helvetica", 10))
        self.loading_status_label.pack(pady=5)
        self.loading_progress_bar = ttk.Progressbar(self.loading_popup, orient='horizontal', length=300,
                                                    mode='determinate')
        self.loading_progress_bar.pack(pady=10)

    def close_loading_popup(self):
        """로딩 팝업을 닫고 메인 애플리케이션 창을 보여줍니다."""
        if hasattr(self, 'loading_popup') and self.loading_popup:
            self.loading_popup.grab_release()
            self.loading_popup.destroy()
        self.deiconify()  # 숨겨뒀던 메인 창을 표시
        self.lift()
        self.focus_force()

    def show_company_details_from_result(self, company_name):
        """
        [신규] 결과 페이지에서 클릭된 기업의 상세 정보를 기업 검색 페이지에 표시합니다.
        """
        print(f"--- '{company_name}'의 상세 정보 페이지로 이동합니다. ---")

        # 1. 기업 검색 페이지 프레임을 가져옵니다.
        company_page = self.frames["CompanySearchPage"]

        # 2. 해당 페이지의 콤보박스 변수 값을 클릭된 기업 이름으로 설정합니다.
        company_page.company_var.set(company_name)

        # 3. 기업 검색 페이지를 화면 맨 앞으로 가져옵니다.
        company_page.tkraise()

        # 4. 설정된 기업 이름에 해당하는 리뷰를 표시하도록 수동으로 함수를 호출합니다.
        #    (콤보박스 값을 코드로 바꾸면 자동으로 이벤트가 발생하지 않기 때문입니다.)
        company_page.show_company_review()


    def show_frame(self, page_name):
        frame = self.frames[page_name]
        if page_name == "CompanySearchPage": frame.update_company_list()
        if page_name == "ResultPage": frame.update_results()
        frame.tkraise()

    def load_initial_resources(self):
        threading.Thread(target=self._load_resources_thread, daemon=True).start()

    def _load_resources_thread(self):
        """백그라운드에서 리소스를 로드하고 로딩 팝업의 상태를 업데이트합니다."""
        total_steps = 3  # 1. 관광지 목록, 2. AI 모델, 3. 기업 분류

        def update_popup(progress, message):
            self.loading_progress_bar['value'] = progress
            self.loading_status_label.config(text=message)

        try:
            # 1단계: 관광지 목록 로딩
            self.after(0, update_popup, 20, "자동완성용 관광지 목록 로딩 중...")
            all_spots = self.analyzer.get_tourist_spots_in_busan()
            self.frames["TouristSearchPage"].update_autocomplete_list(all_spots)

            # 2단계: AI 모델 로딩
            self.after(0, update_popup, 50, f"AI 분석 모델 로딩 중... (장치: {self.device})")
            self.sbert_model = SentenceTransformer('jhgan/ko-sroberta-multitask', device=self.device)
            self.category_embeddings = {cat: self.sbert_model.encode(kw, convert_to_tensor=True) for cat, kw in
                                        self.analyzer.CATEGORIES.items()}
            print("--- AI 모델 및 카테고리 임베딩 로딩 완료 ---")

            # 3단계: 기업 정보 AI 기반 분류
            self.after(0, update_popup, 80, "기업 정보 분석 및 분류 중...")
            self.analyzer.classify_all_companies(self.sbert_model, self.category_embeddings)

            self.after(0, update_popup, 100, "준비 완료!")
            self.after(500, self.close_loading_popup)  # 0.5초 후 팝업 닫기

        except Exception as e:
            self.after(0, self.close_loading_popup)  # 오류 발생 시에도 팝업은 닫기
            messagebox.showerror("초기화 오류", f"프로그램 준비 중 오류가 발생했습니다.\n\n오류: {e}")
            self.destroy()  # 치명적 오류 시 프로그램 종료

    def start_full_analysis(self, spot_name, review_count):
        if not self.sbert_model:
            messagebox.showerror("준비 안됨", "AI 모델이 로딩되지 않았습니다.")
            return
        # [수정] 백그라운드 스레드에 review_count를 전달합니다.
        threading.Thread(target=self._analysis_thread, args=(spot_name, review_count), daemon=True).start()

    def _analysis_thread(self, spot_name, review_count):
        page = self.frames["TouristSearchPage"]
        try:
            self.after(0, page.analysis_start_ui, spot_name)
            steps, total_steps = 0, 3

            def update(msg):
                nonlocal steps
                steps += 1
                self.after(0, page.update_progress_ui, (steps / total_steps) * 100, msg)

            update("1/3: 리뷰 수집 중...")
            # [수정] 구글 리뷰 수집 함수에 review_count를 전달합니다.
            all_reviews = self.analyzer.get_tripadvisor_reviews(
                self.analyzer.get_location_id_from_tripadvisor(spot_name)) + \
                          self.analyzer.get_google_reviews_via_serpapi(
                              self.analyzer.get_google_place_id_via_serpapi(spot_name),
                              review_count
                          )
            if not all_reviews:
                self.after(0, page.analysis_fail_ui, f"'{spot_name}' 리뷰를 찾을 수 없습니다.")
                return

            # ... (이하 코드는 기존과 동일) ...
            update("2/3: AI 모델로 리뷰 분류 중...")
            classified = self.analyzer.classify_reviews(all_reviews, self.sbert_model, self.category_embeddings)
            if not classified:
                self.after(0, page.analysis_fail_ui, "리뷰 카테고리 분류에 실패했습니다.")
                return

            update("3/3: 분석 결과 처리 및 기업 추천 중...")
            best_cat = Counter(r['category'] for r in classified if r['category'] != '기타').most_common(1)[0][0]
            self.analysis_result = {'spot_name': spot_name, 'best_category': best_cat, 'classified_reviews': classified,
                                    'recommended_companies': self.analyzer.recommend_companies(best_cat)}

            self.after(0, page.analysis_complete_ui)
            self.after(200, lambda: self.show_frame("ResultPage"))

        except Exception as e:
            self.after(0, page.analysis_fail_ui, f"분석 중 오류 발생: {e}")

    def refresh_company_data(self):
        threading.Thread(target=self._refresh_company_thread, daemon=True).start()

    def _refresh_company_thread(self):
        page = self.frames["CompanySearchPage"]
        page.status_label.config(text="상태: 구글 시트 정보 새로고침 중...")
        self.analyzer.company_df, self.analyzer.review_df = self.analyzer.get_company_data_from_sheet()
        self.after(0, page.refresh_display)
        self.after(0, page.status_label.config, {"text": ""})


# ------------------- 프로그램 시작점 -------------------
if __name__ == "__main__":
    try:
        config = configparser.ConfigParser()
        config.read(resource_path('config.ini'), encoding='utf-8')
        api_keys = dict(config.items('API_KEYS'))
        paths = dict(config.items('PATHS'))
    except Exception as e:
        messagebox.showerror("초기화 오류", f"config.ini 파일 로드에 실패했습니다.\n\n오류: {e}")
        sys.exit()

    app = TouristApp(api_keys, paths)
    app.mainloop()

