import tkinter as tk
from tkinter import ttk, messagebox, font
import threading
import requests
import warnings
import configparser
import os
import time
from collections import Counter
import sys

# AI 모델 관련 라이브러리
from sentence_transformers import SentenceTransformer, util
import torch

# serpapi 라이브러리
from serpapi import GoogleSearch

# Google Sheets 연동 라이브러리
import gspread
import pandas as pd
from oauth2client.service_account import ServiceAccountCredentials
from googletrans import Translator


# --- [핵심] .exe 환경을 위한 절대 경로 변환 함수 ---
def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller가 생성한 임시 폴더
        base_path = sys._MEIPASS
    except Exception:
        # 일반 개발 환경
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


# 경고 메시지 무시
warnings.filterwarnings("ignore", category=UserWarning, message=".*pkg_resources is deprecated.*")
warnings.filterwarnings('ignore', message='Unverified HTTPS request')


# ------------------- 백엔드 로직: ReviewAnalyzer 클래스 -------------------
class ReviewAnalyzer:
    from googletrans import Translator

    def translate_reviews_to_korean(self, reviews):
        print(f"--- [번역 시작] {len(reviews)}개의 리뷰를 한국어로 번역합니다. ---")
        if not reviews:
            return []

        # [핵심 개선] 번역 전, 비어있거나(None) 텍스트가 아닌 항목을 완벽히 제거합니다.
        valid_reviews = [review for review in reviews if review and isinstance(review, str)]

        if not valid_reviews:
            print("   ... 번역할 유효한 텍스트 리뷰가 없습니다.")
            return []

        print(f"   ... {len(valid_reviews)}개의 유효한 리뷰를 번역 대상으로 합니다.")

        translator = Translator()
        translated_reviews = []
        try:
            # 여러 리뷰를 한 번에 번역하여 효율성을 높입니다.
            translations = translator.translate(valid_reviews, dest='ko')
            for t in translations:
                translated_reviews.append(t.text)
            print(f"--- [번역 완료] 성공적으로 {len(translated_reviews)}개를 번역했습니다. ---")
            return translated_reviews
        except Exception as e:
            print(f"오류: 리뷰 번역 중 오류 발생 - {e}")
            # 번역 실패 시, 번역 가능한 원본 리뷰라도 반환하여 분석이 멈추지 않게 합니다.
            return valid_reviews

    def __init__(self, api_keys, paths):
        # --- API 키와 경로 초기화 ---
        self.KOREA_TOUR_API_KEY = api_keys['korea_tour_api_key']
        self.TRIPADVISOR_API_KEY = api_keys['tripadvisor_api_key']
        self.SERPAPI_API_KEY = api_keys['serpapi_api_key']

        self.KOREA_TOUR_API_URL = "http://apis.data.go.kr/B551011/KorService2/areaBasedList2"
        self.TRIPADVISOR_API_URL = "https://api.content.tripadvisor.com/api/v1"

        self.paths = paths
        # [핵심 수정] google_sheet_key_path는 이제 파일 '이름'만 담게 됩니다.
        self.GOOGLE_SHEET_KEY_FILENAME = self.paths['google_sheet_key_path']
        self.WORKSHEET_NAME = self.paths['worksheet_name']
        self.scopes = [
            'https://spreadsheets.google.com/feeds',
            'https://www.googleapis.com/auth/drive'
        ]

        # --- 프로그램 시작 시 Google Sheet 데이터 로드 ---
        self.company_df = self.get_company_data_from_sheet()

        # --- 카테고리 정의 ---
        self.CATEGORIES = {
            '웰니스': ['힐링', '휴식', '스파', '사우나', '온천', '족욕', '마사지', '산책', '자연', '평화', '평온', '치유', '고요함', '명상', '건강'],
            '뷰티': ['아름다운', '예쁜', '경치', '풍경', '뷰', '야경', '일몰', '노을', '포토존', '인생샷', '건축', '감성', '벚꽃', '파노라마'],
            '교육': ['박물관', '미술관', '역사', '문화', '예술', '유물', '전시', '체험', '학습', '전통', '보존', '기념관', '건축', '템플스테이'],
            '미식': ['맛집', '음식', '레스토랑', '카페', '해산물', '길거리 음식', '시장', '회', '조개구이', '돼지국밥', '씨앗호떡', '만두', '디저트'],
            '역사': ['역사', '유적', '전통', '박물관', '사찰', '기념관', '고분', '삼국시대', '조선시대', '근현대사', 'APEC', '국제시장(영화)', '피난민'],
            '한류': ['SNS', '인스타그램', '틱톡', '핫플레이스', '인기 명소', '부산국제영화제(BIFF)', 'K드라마', '영화 촬영지', '슬램덩크(애니메이션)'],
            '해양': ['바다', '해변', '해수욕장', '해안', '항구', '섬', '등대', '요트', '해상케이블카', '스카이캡슐', '해변열차', '파도', '수족관', '스카이워크'],
            '레포츠': ['레포츠', '액티비티', '스포츠', '루지', '하이킹', '산책', '둘레길', '조깅', '자전거', '요트', '서핑', '비치발리볼', '스카이스윙']
        }

    # [핵심 수정] 중복 선언된 함수를 하나로 합치고, 경로 문제를 완벽히 해결한 최종 버전입니다.
    def get_company_data_from_sheet(self):
        print("\n--- Google Sheets 데이터 로딩 시작 ---")
        spreadsheet_id = self.paths.get('spreadsheet_id')
        spreadsheet_name = self.paths.get('spreadsheet_name')
        df = pd.DataFrame()  # 오류 발생 시 반환할 빈 데이터프레임

        try:
            # 1. resource_path()를 사용해 .json 파일의 실제 절대 경로를 찾습니다. (가장 중요!)
            key_full_path = resource_path(self.GOOGLE_SHEET_KEY_FILENAME)
            print(f"[1/5] 인증 키 파일 경로 확인: {key_full_path}")

            # 2. 찾은 절대 경로를 사용해 인증 정보를 생성합니다.
            print("[2/5] Google API 인증 시도...")
            creds = ServiceAccountCredentials.from_json_keyfile_name(key_full_path, self.scopes)
            gc = gspread.authorize(creds)
            print("  - 인증 성공.")

            # 3. 스프레드시트를 엽니다.
            print("[3/5] 스프레드시트 열기 시도...")
            if spreadsheet_id:
                spreadsheet = gc.open_by_key(spreadsheet_id)
            elif spreadsheet_name:
                spreadsheet = gc.open(spreadsheet_name)
            else:
                messagebox.showerror("설정 오류", "config.ini에 spreadsheet_id 또는 spreadsheet_name이 없습니다.")
                return df
            print("  - 스프레드시트 열기 성공.")

            # 4. 워크시트를 엽니다.
            print(f"[4/5] '{self.WORKSHEET_NAME}' 워크시트 열기 시도...")
            worksheet = spreadsheet.worksheet(self.WORKSHEET_NAME)
            print("  - 워크시트 열기 성공.")

            # 5. 모든 데이터를 가져와 DataFrame으로 변환합니다.
            print("[5/5] 워크시트 데이터 가져오는 중...")
            all_values = worksheet.get_all_values()
            print("  - 데이터 가져오기 성공.")

            if not all_values or len(all_values) < 2:
                messagebox.showerror("데이터 없음", f"'{self.WORKSHEET_NAME}' 시트에 헤더를 포함한 데이터가 없습니다.")
                return df

            headers = all_values[0]
            data_rows = all_values[1:]
            df = pd.DataFrame(data_rows, columns=headers)
            print(f"--- 데이터 로딩 완료: {len(df)}개 기업 데이터 로드 성공 ---")
            return df

        except FileNotFoundError:
            error_msg = f"인증 키 파일을 찾을 수 없습니다.\n\n파일 이름: '{self.GOOGLE_SHEET_KEY_FILENAME}'\n.exe 파일과 함께 패키징되었는지 확인하세요."
            messagebox.showerror("파일 없음 오류 (JSON)", error_msg)
            return df
        except gspread.exceptions.SpreadsheetNotFound:
            error_msg = f"스프레드시트를 찾을 수 없습니다.\n\nID: '{spreadsheet_id}' 또는 이름: '{spreadsheet_name}'\n\n- ID/이름이 정확한지 확인하세요.\n- 서비스 계정이 해당 시트에 '편집자'로 공유되었는지 확인하세요."
            messagebox.showerror("스프레드시트 없음 오류", error_msg)
            return df
        except Exception as e:
            error_msg = f"데이터 로드 중 예상치 못한 오류가 발생했습니다.\n\n오류 유형: {type(e).__name__}\n오류 내용: {e}"
            messagebox.showerror("알 수 없는 오류", error_msg)
            return df

    def recommend_companies(self, category):
        # ... (이하 다른 메서드들은 수정할 필요가 없으므로 그대로 유지합니다) ...
        print(f"\n--- '{category}' 카테고리와 연관된 기업 추천 시작 ---")
        if self.company_df.empty or '사업내용' not in self.company_df.columns:
            return []
        recommended = self.company_df[self.company_df['사업내용'].str.contains(category, na=False)]
        company_names = recommended['기업명'].tolist()
        print(f"   ... 추천 기업: {company_names}")
        return company_names

    def get_all_tourist_spots(self):
        print("--- 자동완성 목록 생성: 모든 관광지 정보 가져오는 중 ---")
        all_spots, page_no = [], 1
        params = {'serviceKey': self.KOREA_TOUR_API_KEY, 'numOfRows': 100, 'pageNo': 1, 'MobileOS': 'ETC',
                  'MobileApp': 'TouristAnalyzerApp', '_type': 'json', 'arrange': 'A', 'areaCode': '6',
                  'contentTypeId': '12'}
        try:
            while True:
                params['pageNo'] = page_no
                response = requests.get(self.KOREA_TOUR_API_URL, params=params, timeout=10)
                response.raise_for_status()
                items = response.json().get('response', {}).get('body', {}).get('items', {}).get('item', [])
                if not items:
                    break
                for item in items:
                    all_spots.append({'title': item.get('title'), 'addr1': item.get('addr1', '')})
                if len(all_spots) >= response.json().get('response', {}).get('body', {}).get('totalCount', 0):
                    break
                page_no += 1
                time.sleep(0.5)
        except Exception as e:
            print(f"오류: 국문관광정보 API 호출 중 에러 발생 - {e}")
        print(f"--- 최종적으로 {len(all_spots)}개의 관광지 목록을 생성했습니다. ---")
        return all_spots

    def search_tripadvisor_location_id(self, location_name):
        print(f"\n--- 트립어드바이저에서 '{location_name}'의 Location ID 검색 시작 ---")
        url = f"{self.TRIPADVISOR_API_URL}/location/search"
        params = {'key': self.TRIPADVISOR_API_KEY, 'searchQuery': location_name, 'language': 'ko'}
        try:
            response = requests.get(url, params=params, headers={'accept': 'application/json'}, timeout=5)
            response.raise_for_status()
            return response.json().get('data', [])[0]['location_id'] if response.json().get('data') else None
        except Exception as e:
            print(f"오류: 트립어드바이저 Location 검색 API 호출 중 - {e}")
            return None

    def get_tripadvisor_reviews(self, location_id):
        print(f"\n--- 트립어드바이저 리뷰 가져오기 시작 ---")
        if not location_id:
            return []
        url = f"{self.TRIPADVISOR_API_URL}/location/{location_id}/reviews"
        params = {'key': self.TRIPADVISOR_API_KEY, 'language': 'ko'}
        try:
            response = requests.get(url, params=params, headers={'accept': 'application/json'}, timeout=10)
            response.raise_for_status()
            return [r['text'] for r in response.json().get('data', []) if 'text' in r and r['text']]
        except Exception as e:
            print(f"오류: 트립어드바이저 리뷰 API 호출 중 - {e}")
            return []

    def get_google_place_id(self, location_info):
        print(f"\n--- Google에서 '{location_info['title']}'의 Place ID 검색 시작 ---")
        try:
            cleaned_title = location_info['title'].split('(')[0].strip()
            params = {"engine": "google_maps", "q": f"{cleaned_title}, {location_info['addr1']}", "type": "search",
                      "hl": "ko", "api_key": self.SERPAPI_API_KEY}
            search = GoogleSearch(params)
            results = search.get_dict()
            place_id = results.get("local_results", [{}])[0].get("place_id")
            if place_id:
                print(f"   ... Place ID 찾음: {place_id}")
                return place_id
            else:
                print("   ... Place ID를 찾지 못했습니다.")
                return None
        except Exception as e:
            print(f"오류: SerpApi로 Place ID 검색 중 - {e}")
            return None

    def get_google_reviews_via_serpapi(self, place_id, max_reviews):
        print(f"\n--- 구글 리뷰 가져오기 시작 (최대 {max_reviews}개 목표) ---")
        if not place_id:
            return []
        try:
            all_review_texts = []
            params = {"engine": "google_maps_reviews", "place_id": place_id, "hl": "ko",
                      "api_key": self.SERPAPI_API_KEY}
            while True:
                search = GoogleSearch(params)
                results = search.get_dict()
                reviews_data = results.get("reviews", [])
                if not reviews_data:
                    break
                all_review_texts.extend([r.get('snippet', '') for r in reviews_data if r.get('snippet')])
                if len(all_review_texts) >= max_reviews or "next_page_token" not in results.get("serpapi_pagination",
                                                                                                {}):
                    break
                params["next_page_token"] = results["serpapi_pagination"]["next_page_token"]
                time.sleep(1)
            return all_review_texts[:max_reviews]
        except Exception as e:
            print(f"오류: SerpApi로 리뷰 수집 중 - {e}")
            return []

    def classify_reviews(self, all_reviews, model, category_embeddings, threshold):
        print(f"\n--- AI 모델로 리뷰 분류 시작 ---")
        classified_results = []
        for review in all_reviews:
            if not review.strip():
                continue
            review_embedding = model.encode(review, convert_to_tensor=True)
            best_category, highest_score = '기타', 0.0
            for category, cat_embedding in category_embeddings.items():
                cosine_scores = util.cos_sim(review_embedding, cat_embedding)
                max_score = torch.max(cosine_scores).item()
                if max_score > highest_score:
                    highest_score, best_category = max_score, category
            if highest_score < threshold:
                best_category = '기타'
            classified_results.append({'review': review, 'category': best_category})
        return classified_results



# ------------------- 프론트엔드 UI 페이지들 -------------------
class StartPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        tk.Label(self, text="리뷰 기반 관광-기업 분석기", font=("AppleGothic", 22, "bold")).pack(pady=50)
        btn_frame = tk.Frame(self)
        btn_frame.pack(pady=20)
        tk.Button(btn_frame, text="기업 검색", font=("AppleGothic", 16), width=20, height=3,
                  command=lambda: controller.show_frame("CompanySearchPage")).pack(pady=15)
        tk.Button(btn_frame, text="관광지 검색", font=("AppleGothic", 16), width=20, height=3,
                  command=lambda: controller.show_frame("TouristSearchPage")).pack(pady=15)


class CompanySearchPage(tk.Frame):

    def refresh_list(self):
        # 컨트롤러의 데이터 새로고침 함수를 호출합니다.
        self.controller.refresh_company_data()

    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller  # <- controller는 여기에 있어야 합니다.

        header_frame = tk.Frame(self)
        header_frame.pack(fill='x', pady=10, padx=10)
        tk.Button(header_frame, text="< 시작 화면으로", command=lambda: controller.show_frame("StartPage")).pack(side='left')

        # [추가] 새로고침 버튼을 헤더 오른쪽에 추가합니다.
        tk.Button(header_frame, text="목록 새로고침 🔃", command=self.refresh_list).pack(side='right')

        tk.Label(self, text="기업을 선택하여 평가를 확인하세요", font=("AppleGothic", 18, "bold")).pack(pady=20)

        # [추가] 새로고침 상태를 보여줄 라벨을 추가합니다.
        self.status_label = tk.Label(self, text="")
        self.status_label.pack(pady=2)

        self.company_var = tk.StringVar()
        self.company_combo = ttk.Combobox(self, textvariable=self.company_var, font=("AppleGothic", 14),
                                          state="readonly")
        self.company_combo.pack(pady=10, padx=20, fill='x')
        self.company_combo.bind("<<ComboboxSelected>>", self.show_company_review)

        text_frame = tk.Frame(self)
        text_frame.pack(pady=10, padx=20, fill='both', expand=True)
        self.text_area = tk.Text(text_frame, wrap='word', font=("AppleGothic", 12), bg="#f0f0f0", fg='black')
        self.scrollbar = tk.Scrollbar(text_frame, command=self.text_area.yview)
        self.text_area.config(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side='right', fill='y')
        self.text_area.pack(side='left', fill='both', expand=True)

    def update_company_list(self):
        """컨트롤러의 데이터를 기반으로 콤보박스 목록을 업데이트합니다."""
        company_df = self.controller.analyzer.company_df
        if not company_df.empty and '기업명' in company_df.columns:
            company_list = company_df['기업명'].tolist()
            self.company_combo['values'] = company_list
        else:
            self.company_combo['values'] = []
            # 목록이 비었을 경우 안내 문구를 추가할 수 있습니다.
            self.text_area.config(state='normal')
            self.text_area.delete(1.0, 'end')
            self.text_area.insert('end', "불러올 기업 목록이 없습니다.")
            self.text_area.config(state='disabled')

    def show_company_review(self, event=None):
        selected_company = self.company_var.get()
        company_df = self.controller.analyzer.company_df

        self.text_area.config(state='normal')
        self.text_area.delete(1.0, 'end')

        try:
            # 필터링된 데이터에서 '평가' 내용을 가져옵니다.
            review_text = company_df[company_df['기업명'] == selected_company]['평가'].iloc[0]

            # 만약 데이터가 비어있다면(None, NaN) 안내 문구를 표시합니다.
            if pd.isna(review_text) or str(review_text).strip() == '':
                self.text_area.insert('end', "✅ 등록된 평가 정보가 없습니다.")
            else:
                self.text_area.insert('end', review_text)

        except IndexError:
            # 선택된 기업 정보가 없는 경우에 대한 예외 처리
            self.text_area.insert('end', f"⚠️ '{selected_company}'에 대한 정보를 찾을 수 없습니다.")

        self.text_area.config(state='disabled')



class TouristSearchPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.spot_names = []
        header_frame = tk.Frame(self)
        header_frame.pack(fill='x', pady=10, padx=10)
        tk.Button(header_frame, text="< 시작 화면으로", command=lambda: controller.show_frame("StartPage")).pack(side='left')
        tk.Label(self, text="분석할 관광지를 선택하세요", font=("AppleGothic", 18, "bold")).pack(pady=20)
        self.entry_var = tk.StringVar()
        self.entry_var.trace_add("write", self.on_entry_change)
        self.entry = ttk.Combobox(self, textvariable=self.entry_var, font=("AppleGothic", 14))
        self.entry.pack(pady=10, padx=20, fill='x')
        self.listbox = tk.Listbox(self, font=("AppleGothic", 12))
        self.listbox.pack(pady=5, padx=20, fill='x')
        self.listbox.bind("<<ListboxSelect>>", self.on_listbox_select)
        review_frame = tk.Frame(self)
        review_frame.pack(pady=10)
        tk.Label(review_frame, text="최대 구글 리뷰 수:").pack(side='left', padx=5)
        self.max_var = tk.StringVar(value='100')
        tk.Entry(review_frame, textvariable=self.max_var, width=10).pack(side='left')
        tk.Button(self, text="분석 시작!", font=("AppleGothic", 14, "bold"), command=self.start_analysis).pack(pady=20)
        self.status_label = tk.Label(self, text="상태: 대기 중")
        self.status_label.pack(side='bottom', pady=10)

    def update_autocomplete(self, spot_names):
        self.entry['values'] = spot_names
        self.spot_names = spot_names

    def on_entry_change(self, *args):
        search_term = self.entry_var.get().lower()
        self.listbox.delete(0, 'end')
        if search_term:
            filtered_spots = [spot for spot in self.spot_names if search_term in spot.lower()]
            for spot in filtered_spots:
                self.listbox.insert('end', spot)

    def on_listbox_select(self, event):
        selected_indices = self.listbox.curselection()
        if selected_indices:
            self.entry_var.set(self.listbox.get(selected_indices[0]))
            self.listbox.delete(0, 'end')

    def start_analysis(self):
        spot_name = self.entry_var.get()
        if not spot_name or spot_name not in self.spot_names:
            messagebox.showwarning("입력 오류", "목록에 있는 관광지를 선택해주세요.")
            return
        try:
            max_reviews = int(self.max_var.get())
            if max_reviews <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("입력 오류", "최대 리뷰 수는 0보다 큰 정수로 입력해주세요.")
            return
        self.controller.start_full_analysis(spot_name, max_reviews)


class ResultPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        header_frame = tk.Frame(self)
        header_frame.pack(fill='x', pady=10, padx=10)
        tk.Button(header_frame, text="< 관광지 검색으로", command=lambda: controller.show_frame("TouristSearchPage")).pack(
            side='left')
        self.title_label = tk.Label(header_frame, text="", font=("AppleGothic", 18, "bold"))
        self.title_label.pack(side='left', padx=20)
        canvas = tk.Canvas(self)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.scrollable_frame = ttk.Frame(canvas)
        self.scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        scrollbar.pack(side="right", fill="y")

    def update_results(self):
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        result_data = self.controller.analysis_result
        spot_name = result_data['spot_name']
        reviews = result_data['classified_reviews']
        self.title_label.config(text=f"'{spot_name}' 분석 결과")

        recommended_companies = result_data.get('recommended_companies', [])
        main_category = result_data.get('main_category', '없음')
        if recommended_companies:
            reco_frame = ttk.LabelFrame(self.scrollable_frame, text=f" 🏫'{main_category}' 연관 기업 추천", padding=10)
            reco_frame.pack(fill='x', padx=10, pady=10, anchor='n')
            reco_text = ", ".join(recommended_companies)
            tk.Label(reco_frame, text=reco_text, wraplength=550, justify='left').pack(anchor='w')

        category_frame = ttk.LabelFrame(self.scrollable_frame, text=" 💬관광지 리뷰 카테고리 분류 결과", padding=10)
        category_frame.pack(fill='x', padx=10, pady=10, anchor='n')
        category_counts = Counter(result['category'] for result in reviews)
        total_reviews = len(reviews)
        for category, count in category_counts.most_common():
            cat_frame = tk.Frame(category_frame)
            cat_frame.pack(fill='x', pady=5)
            percentage = (count / total_reviews) * 100 if total_reviews > 0 else 0
            label_text = f"● {category}: {count}개 ({percentage:.1f}%)"
            tk.Label(cat_frame, text=label_text, font=("AppleGothic", 14)).pack(side='left')
            tk.Button(cat_frame, text="상세 리뷰 보기", command=lambda c=category: self.show_details(c)).pack(side='right')

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
        self.title_label = tk.Label(header_frame, text="", font=("AppleGothic", 16, "bold"))
        self.title_label.pack(side='left')
        text_frame = tk.Frame(self)
        text_frame.pack(pady=10, padx=20, fill='both', expand=True)
        self.text_area = tk.Text(text_frame, wrap='word', font=("AppleGothic", 12))
        self.scrollbar = tk.Scrollbar(text_frame, command=self.text_area.yview)
        self.text_area.config(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side='right', fill='y')
        self.text_area.pack(side='left', fill='both', expand=True)

    def update_details(self, category):
        spot_name = self.controller.analysis_result['spot_name']
        reviews = self.controller.analysis_result['classified_reviews']
        self.title_label.config(text=f"'{spot_name}' - [{category}] 리뷰 목록")
        self.text_area.config(state='normal')
        self.text_area.delete(1.0, 'end')
        filtered_reviews = [r['review'] for r in reviews if r['category'] == category]
        for i, review in enumerate(filtered_reviews, 1):
            self.text_area.insert('end', f"--- 리뷰 {i} ---\n{review}\n\n")
        self.text_area.config(state='disabled')


# ------------------- 메인 애플리케이션 클래스 (컨트롤러) -------------------
class TouristApp(tk.Tk):
    def __init__(self, api_keys, paths):
        super().__init__()
        self.title("관광-기업 연계 분석기")
        self.geometry("800x650")

        self.paths = paths
        self.analyzer = ReviewAnalyzer(api_keys, self.paths)

        self.all_tourist_spots = []
        self.analysis_result = {}

        self.default_font = font.nametofont("TkDefaultFont")
        self.default_font.configure(family="AppleGothic", size=12)

        container = tk.Frame(self)
        container.pack(side="top", fill="both", expand=True)
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        self.frames = {}
        for F in (StartPage, CompanySearchPage, TouristSearchPage, ResultPage, DetailPage):
            page_name = F.__name__
            frame = F(parent=container, controller=self)
            self.frames[page_name] = frame
            frame.grid(row=0, column=0, sticky="nsew")

        self.show_frame("StartPage")
        self.load_initial_resources()

    def show_frame(self, page_name):
        if page_name == "CompanySearchPage":
            self.frames[page_name].update_company_list()
        if page_name == "ResultPage":
            self.frames[page_name].update_results()
        frame = self.frames[page_name]
        frame.tkraise()

    def load_initial_resources(self):
        threading.Thread(target=self._load_resources_thread, daemon=True).start()

    def _load_resources_thread(self):
        status_label = self.frames["TouristSearchPage"].status_label

        # 1. 관광지 목록 로딩
        status_label.config(text="상태: 자동완성용 관광지 목록 로딩 중...")
        self.all_tourist_spots = self.analyzer.get_all_tourist_spots()
        spot_names = [spot['title'] for spot in self.all_tourist_spots]
        self.frames["TouristSearchPage"].update_autocomplete(spot_names)

        # 2. AI 모델 및 임베딩 로딩
        status_label.config(text="상태: AI 분석 모델 로딩 중...")
        try:
            self.sbert_model = SentenceTransformer('jhgan/ko-sroberta-multitask')
            self.category_embeddings = {cat: self.sbert_model.encode(kw, convert_to_tensor=True)
                                        for cat, kw in self.analyzer.CATEGORIES.items()}
            print("--- AI 모델 및 카테고리 임베딩 로딩 완료 ---")
            status_label.config(text="상태: 대기 중")
        except Exception as e:
            print(f"AI 모델 로딩 실패: {e}")
            messagebox.showerror("모델 로딩 오류", f"AI 모델을 로딩하는 데 실패했습니다.\n인터넷 연결을 확인하세요.\n\n오류: {e}")
            status_label.config(text="상태: AI 모델 로딩 실패")

    def start_full_analysis(self, spot_name, max_reviews):
        if not self.sbert_model:
            messagebox.showerror("준비 안됨", "아직 AI 모델이 로딩되지 않았습니다. 잠시 후 다시 시도해주세요.")
            return
        threading.Thread(target=self._analysis_thread, args=(spot_name, max_reviews), daemon=True).start()

    def _analysis_thread(self, spot_name, max_reviews):
        try:
            main_page = self.frames["TouristSearchPage"]
            main_page.status_label.config(text=f"상태: '{spot_name}' 분석 시작...")
            selected_spot_info = next((spot for spot in self.all_tourist_spots if spot['title'] == spot_name), None)

            if not selected_spot_info:
                messagebox.showerror("오류", "선택된 관광지 정보를 찾을 수 없습니다.")
                main_page.status_label.config(text="상태: 오류 발생")
                return

            main_page.status_label.config(text="상태: 트립어드바이저 리뷰 수집 중...")
            ta_id = self.analyzer.search_tripadvisor_location_id(spot_name)
            ta_reviews = self.analyzer.get_tripadvisor_reviews(ta_id)

            main_page.status_label.config(text="상태: 구글맵 리뷰 수집 중...")
            google_place_id = self.analyzer.get_google_place_id(selected_spot_info)
            google_reviews = self.analyzer.get_google_reviews_via_serpapi(google_place_id,
                                                                          max_reviews) if google_place_id else []

            all_reviews = ta_reviews + google_reviews
            if not all_reviews:
                messagebox.showinfo("결과 없음", "분석할 리뷰를 찾지 못했습니다.")
                main_page.status_label.config(text="상태: 대기 중")
                return

            main_page.status_label.config(text="상태: 외국어 리뷰 번역 중...")
            all_reviews = self.analyzer.translate_reviews_to_korean(all_reviews)

            main_page.status_label.config(text="상태: AI 모델로 리뷰 분류 중...")
            classified_reviews = self.analyzer.classify_reviews(
                all_reviews,
                self.sbert_model,
                self.category_embeddings,
                0.4
            )

            if not classified_reviews:
                messagebox.showinfo("분석 불가", "리뷰의 카테고리를 분류할 수 없습니다.")
                main_page.status_label.config(text="상태: 대기 중")
                return

            main_category = Counter(result['category'] for result in classified_reviews).most_common(1)[0][0]
            print(f"\n--- 대표 카테고리 선정: {main_category} ---")
            recommended_companies = self.analyzer.recommend_companies(main_category)

            self.analysis_result = {
                'spot_name': spot_name,
                'classified_reviews': classified_reviews,
                'main_category': main_category,
                'recommended_companies': recommended_companies
            }
            self.show_frame("ResultPage")
            main_page.status_label.config(text="상태: 대기 중")

        except Exception as e:
            messagebox.showerror("분석 오류", f"분석 중 오류가 발생했습니다: {e}")
            self.frames["TouristSearchPage"].status_label.config(text="상태: 오류 발생")

    def refresh_company_data(self):
        """새로고침 기능을 별도 스레드에서 실행하도록 호출합니다."""
        threading.Thread(target=self._refresh_company_thread, daemon=True).start()

    def _refresh_company_thread(self):
        company_page = self.frames["CompanySearchPage"]
        currently_selected_company = company_page.company_var.get()

        print(f"\n[진단] 새로고침 시작. 현재 선택된 기업: '{currently_selected_company}'")

        new_company_df = self.analyzer.get_company_data_from_sheet()

        if not new_company_df.empty:
            self.analyzer.company_df = new_company_df
            self.after(0, company_page.update_company_list)

            print(f"[진단] UI 업데이트 시도. '{currently_selected_company}'를 다시 선택합니다.")
            if currently_selected_company and currently_selected_company in new_company_df['기업명'].tolist():
                self.after(0, lambda: company_page.company_var.set(currently_selected_company))
                self.after(0, company_page.show_company_review)
                print("[진단] UI 업데이트 명령 완료.")
            else:
                print("[진단] 이전에 선택된 기업이 없거나, 새 목록에 없어 평가를 업데이트하지 않습니다.")
        else:
            print("[진단] 새로 가져온 데이터가 비어있어 UI를 업데이트하지 않습니다.")

# ------------------- 프로그램 시작점 -------------------
if __name__ == "__main__":
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        config_file_path = os.path.join(current_dir, 'config.ini')

        config = configparser.ConfigParser()
        if not config.read(config_file_path, encoding='utf-8'):
            raise FileNotFoundError(f"지정된 경로에 config.ini 파일이 없습니다: {config_file_path}")

        api_keys = {
            'korea_tour_api_key': config.get('API_KEYS', 'KOREA_TOUR_API_KEY'),
            'tripadvisor_api_key': config.get('API_KEYS', 'TRIPADVISOR_API_KEY'),
            'serpapi_api_key': config.get('API_KEYS', 'SERPAPI_API_KEY')
        }

        # [핵심 수정] 딕셔너리 형식을 완벽하게 수정하고,
        # ID가 없어도 오류나지 않도록 fallback을 추가했습니다.
        paths = {
            'google_sheet_key_path': config.get('PATHS', 'GOOGLE_SHEET_KEY_PATH'),
            'spreadsheet_name': config.get('PATHS', 'SPREADSHEET_NAME'),
            'worksheet_name': config.get('PATHS', 'WORKSHEET_NAME'),
            'spreadsheet_id': config.get('PATHS', 'spreadsheet_id', fallback=None)
        }

    except (configparser.NoSectionError, configparser.NoOptionError) as e:
        messagebox.showerror("설정 오류",
                             f"config.ini 파일에 필요한 섹션이나 키가 없습니다.\n[API_KEYS]와 [PATHS] 섹션 및 모든 키가 올바르게 설정되었는지 확인하세요.\n\n오류: {e}")
        exit()
    except Exception as e:
        messagebox.showerror("설정 오류", f"config.ini 파일을 읽는 중 오류가 발생했습니다.\n파일 경로와 키 이름을 확인하세요.\n\n오류: {e}")
        exit()

    app = TouristApp(api_keys, paths)
    app.mainloop()

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller가 임시 폴더를 만들고 그 경로를 _MEIPASS에 저장합니다.
        base_path = sys._MEIPASS
    except Exception:
        # PyInstaller로 실행되지 않았을 경우, 현재 작업 디렉터리를 사용합니다.
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

# AI 모델 관련 라이브러리
from sentence_transformers import SentenceTransformer, util
import torch

import sys

# serpapi 라이브러리
from serpapi import GoogleSearch

# Google Sheets 연동 라이브러리
import gspread
import pandas as pd

from oauth2client.service_account import ServiceAccountCredentials

credentials_path = resource_path('serene-exchange-438319-r7-1dc9aac8b9cf.json')

scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_name(credentials_path, scope)


# 경고 메시지 무시
warnings.filterwarnings("ignore", category=UserWarning, message=".*pkg_resources is deprecated.*")
warnings.filterwarnings('ignore', message='Unverified HTTPS request')


# ------------------- 백엔드 로직: ReviewAnalyzer 클래스 -------------------
class ReviewAnalyzer:
    def __init__(self, api_keys, paths):
        # --- API 키와 경로 초기화 ---
        self.KOREA_TOUR_API_KEY = api_keys['korea_tour_api_key']
        self.TRIPADVISOR_API_KEY = api_keys['tripadvisor_api_key']
        self.SERPAPI_API_KEY = api_keys['serpapi_api_key']

        self.KOREA_TOUR_API_URL = "http://apis.data.go.kr/B551011/KorService2/areaBasedList2"
        self.TRIPADVISOR_API_URL = "https://api.content.tripadvisor.com/api/v1"

        self.paths = paths
        self.GOOGLE_SHEET_KEY_PATH = self.paths['google_sheet_key_path']
        self.WORKSHEET_NAME = self.paths['worksheet_name']
        self.scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive.file'
        ]

        self.company_df = self.get_company_data_from_sheet()

        # --- 프로그램 시작 시 Google Sheet 데이터 로드 ---
        self.company_df = self.get_company_data_from_sheet()

        # --- 카테고리 정의 ---
        self.CATEGORIES = {
            '웰니스': ['힐링', '휴식', '스파', '사우나', '온천', '족욕', '마사지', '산책', '자연', '평화', '평온', '치유', '고요함', '명상', '건강'],
            '뷰티': ['아름다운', '예쁜', '경치', '풍경', '뷰', '야경', '일몰', '노을', '포토존', '인생샷', '건축', '감성', '벚꽃', '파노라마'],
            '교육': ['박물관', '미술관', '역사', '문화', '예술', '유물', '전시', '체험', '학습', '전통', '보존', '기념관', '건축', '템플스테이'],
            '미식': ['맛집', '음식', '레스토랑', '카페', '해산물', '길거리 음식', '시장', '회', '조개구이', '돼지국밥', '씨앗호떡', '만두', '디저트'],
            '역사': ['역사', '유적', '전통', '박물관', '사찰', '기념관', '고분', '삼국시대', '조선시대', '근현대사', 'APEC', '국제시장(영화)', '피난민'],
            '한류': ['SNS', '인스타그램', '틱톡', '핫플레이스', '인기 명소', '부산국제영화제(BIFF)', 'K드라마', '영화 촬영지', '슬램덩크(애니메이션)'],
            '해양': ['바다', '해변', '해수욕장', '해안', '항구', '섬', '등대', '요트', '해상케이블카', '스카이캡슐', '해변열차', '파도', '수족관', '스카이워크'],
            '레포츠': ['레포츠', '액티비티', '스포츠', '루지', '하이킹', '산책', '둘레길', '조깅', '자전거', '요트', '서핑', '비치발리볼', '스카이스윙']
        }

    # --- 나머지 ReviewAnalyzer 메서드들 (get_company_data_from_sheet, recommend_companies 등)은 그대로 둡니다. ---
    def get_company_data_from_sheet(self):
        print("\n--- [진단] get_company_data_from_sheet 함수 실행 시작 ---")

        # 1. 모든 변수를 미리 안전하게 초기화하여 NameError를 원천 차단합니다.
        key_path = self.paths.get('google_sheet_key_path')
        final_key_path = resource_path(key_filename)
        creds = ServiceAccountCredentials.from_service_account_file(final_key_path, scopes=self.scopes)
        spreadsheet_id = self.paths.get('spreadsheet_id')
        spreadsheet_name = self.paths.get('spreadsheet_name')
        worksheet_name = self.paths.get('worksheet_name')
        df = pd.DataFrame()  # 기본값으로 빈 데이터프레임 설정

        try:
            # 2. 인증 정보를 생성합니다. (가장 흔한 오류 지점: FileNotFoundError)
            print("[1/5] Google API 인증을 시도합니다...")
            creds = ServiceAccountCredentials.from_service_account_file(key_path, scopes=self.scopes)
            gc = gspread.authorize(creds)
            print("  - 인증 성공.")

            # 3. 스프레드시트를 엽니다. (두 번째 흔한 오류 지점: SpreadsheetNotFound)
            print("[2/5] 스프레드시트 열기를 시도합니다...")
            if spreadsheet_id:
                spreadsheet = gc.open_by_key(spreadsheet_id)
            elif spreadsheet_name:
                spreadsheet = gc.open(spreadsheet_name)
            else:
                messagebox.showerror("설정 오류", "config.ini에 spreadsheet_id 또는 spreadsheet_name이 없습니다.")
                return df
            print("  - 스프레드시트 열기 성공.")

            # 4. 워크시트를 엽니다.
            print(f"[3/5] '{worksheet_name}' 워크시트 열기를 시도합니다...")
            worksheet = spreadsheet.worksheet(worksheet_name)
            print("  - 워크시트 열기 성공.")

            # 5. 모든 데이터를 가져옵니다.
            print("[4/5] 워크시트의 모든 데이터를 가져옵니다...")
            all_values = worksheet.get_all_values()
            print("  - 데이터 가져오기 성공.")

            if not all_values or len(all_values) < 2:
                messagebox.showerror("데이터 없음", f"'{worksheet_name}' 시트에 헤더를 포함한 데이터가 없습니다.")
                return df

            headers = all_values[0]
            data_rows = all_values[1:]
            df = pd.DataFrame(data_rows, columns=headers)

            print(f"[5/5] 성공적으로 {len(df)}개의 기업 데이터를 DataFrame으로 변환했습니다.")
            print("\n--- [진단 완료] 데이터 로딩에 성공했습니다. ---")
            return df

        except FileNotFoundError:
            error_msg = f"인증 키 파일을 찾을 수 없습니다.\n\nconfig.ini에 설정된 경로가 올바른지 확인해주세요:\n'{key_path}'"
            messagebox.showerror("파일 없음 오류", error_msg)
            return df

        except gspread.exceptions.SpreadsheetNotFound:
            error_msg = f"스프레드시트를 찾을 수 없습니다.\n\nID: '{spreadsheet_id}' 또는 이름: '{spreadsheet_name}'\n\n- ID/이름이 정확한지 확인하세요.\n- 서비스 계정이 해당 시트에 '편집자'로 공유되었는지 확인하세요."
            messagebox.showerror("스프레드시트 없음 오류", error_msg)
            return df

        except Exception as e:
            error_msg = f"예상치 못한 오류가 발생했습니다.\n\n오류 유형: {type(e).__name__}\n오류 내용: {e}"
            messagebox.showerror("알 수 없는 오류", error_msg)
            return df

    def get_company_data_from_sheet(self):
        spreadsheet_id = self.paths.get('spreadsheet_id')
        spreadsheet_name = self.paths.get('spreadsheet_name')

        try:
            creds = ServiceAccountCredentials.from_service_account_file(self.GOOGLE_SHEET_KEY_PATH, scopes=self.scopes)
            gc = gspread.authorize(creds)

            if spreadsheet_id:
                spreadsheet = gc.open_by_key(spreadsheet_id)
            elif spreadsheet_name:
                spreadsheet = gc.open(spreadsheet_name)
            else:
                messagebox.showerror("설정 오류", "config.ini에 spreadsheet_id 또는 spreadsheet_name이 없습니다.")
                return pd.DataFrame()

            worksheet = spreadsheet.worksheet(self.WORKSHEET_NAME)

            print("\n[진단 시작] Google Sheets에서 최신 데이터를 강제로 로딩합니다.")
            all_values = worksheet.get_all_values()

            if not all_values or len(all_values) < 2:
                return pd.DataFrame()

            headers = all_values[0]
            data_rows = all_values[1:]
            df = pd.DataFrame(data_rows, columns=headers)

            print(f"[진단 결과] 성공! {len(df)}개의 최신 데이터를 가져왔습니다.")

            return df

        except Exception as e:
            print(f"[진단 중 오류 발생] get_company_data_from_sheet: {e}")
            messagebox.showerror("스프레드시트 오류", f"데이터 로드 중 오류가 발생했습니다:\n{e}")
            return pd.DataFrame()


    def recommend_companies(self, category):
        print(f"\n--- '{category}' 카테고리와 연관된 기업 추천 시작 ---")
        if self.company_df.empty or '사업내용' not in self.company_df.columns:
            return []
        recommended = self.company_df[self.company_df['사업내용'].str.contains(category, na=False)]
        company_names = recommended['기업명'].tolist()
        print(f"   ... 추천 기업: {company_names}")
        return company_names

    def get_all_tourist_spots(self):
        print("--- 자동완성 목록 생성: 모든 관광지 정보 가져오는 중 ---")
        all_spots, page_no = [], 1
        params = {'serviceKey': self.KOREA_TOUR_API_KEY, 'numOfRows': 100, 'pageNo': 1, 'MobileOS': 'ETC',
                  'MobileApp': 'TouristAnalyzerApp', '_type': 'json', 'arrange': 'A', 'areaCode': '6',
                  'contentTypeId': '12'}
        try:
            while True:
                params['pageNo'] = page_no
                response = requests.get(self.KOREA_TOUR_API_URL, params=params, timeout=10)
                response.raise_for_status()
                items = response.json().get('response', {}).get('body', {}).get('items', {}).get('item', [])
                if not items:
                    break
                for item in items:
                    all_spots.append({'title': item.get('title'), 'addr1': item.get('addr1', '')})
                if len(all_spots) >= response.json().get('response', {}).get('body', {}).get('totalCount', 0):
                    break
                page_no += 1
                time.sleep(0.5)
        except Exception as e:
            print(f"오류: 국문관광정보 API 호출 중 에러 발생 - {e}")
        print(f"--- 최종적으로 {len(all_spots)}개의 관광지 목록을 생성했습니다. ---")
        return all_spots

    def search_tripadvisor_location_id(self, location_name):
        print(f"\n--- 트립어드바이저에서 '{location_name}'의 Location ID 검색 시작 ---")
        url = f"{self.TRIPADVISOR_API_URL}/location/search"
        params = {'key': self.TRIPADVISOR_API_KEY, 'searchQuery': location_name, 'language': 'ko'}
        try:
            response = requests.get(url, params=params, headers={'accept': 'application/json'}, timeout=5)
            response.raise_for_status()
            return response.json().get('data', [])[0]['location_id'] if response.json().get('data') else None
        except Exception as e:
            print(f"오류: 트립어드바이저 Location 검색 API 호출 중 - {e}")
            return None

    def get_tripadvisor_reviews(self, location_id):
        print(f"\n--- 트립어드바이저 리뷰 가져오기 시작 ---")
        if not location_id:
            return []
        url = f"{self.TRIPADVISOR_API_URL}/location/{location_id}/reviews"
        params = {'key': self.TRIPADVISOR_API_KEY, 'language': 'ko'}
        try:
            response = requests.get(url, params=params, headers={'accept': 'application/json'}, timeout=10)
            response.raise_for_status()
            return [r['text'] for r in response.json().get('data', []) if 'text' in r]
        except Exception as e:
            print(f"오류: 트립어드바이저 리뷰 API 호출 중 - {e}")
            return []

    def get_google_place_id(self, location_info):
        print(f"\n--- Google에서 '{location_info['title']}'의 Place ID 검색 시작 ---")
        try:
            cleaned_title = location_info['title'].split('(')[0].strip()
            print(f"🕵️  [최종 검색어 확인] q: \"{cleaned_title}, {location_info['addr1']}\"")
            params = {"engine": "google_maps", "q": f"{cleaned_title}, {location_info['addr1']}", "type": "search",
                      "hl": "ko", "api_key": self.SERPAPI_API_KEY}
            search = GoogleSearch(params)
            results = search.get_dict()
            place_id = results.get("local_results", [{}])[0].get("place_id")
            if place_id:
                print(f"   ... Place ID 찾음: {place_id}")
                return place_id
            else:
                print("   ... Place ID를 찾지 못했습니다.")
                return None
        except Exception as e:
            print(f"오류: SerpApi로 Place ID 검색 중 - {e}")
            return None

    def get_google_reviews_via_serpapi(self, place_id, max_reviews):
        print(f"\n--- 구글 리뷰 가져오기 시작 (최대 {max_reviews}개 목표) ---")
        if not place_id:
            return []
        try:
            all_review_texts = []
            params = {"engine": "google_maps_reviews", "place_id": place_id, "hl": "ko",
                      "api_key": self.SERPAPI_API_KEY}
            while True:
                search = GoogleSearch(params)
                results = search.get_dict()
                reviews_data = results.get("reviews", [])
                if not reviews_data:
                    break
                all_review_texts.extend([r.get('snippet', '') for r in reviews_data if r.get('snippet')])
                if len(all_review_texts) >= max_reviews or "next_page_token" not in results.get("serpapi_pagination",
                                                                                                {}):
                    break
                params["next_page_token"] = results["serpapi_pagination"]["next_page_token"]
                time.sleep(1)
            return all_review_texts[:max_reviews]
        except Exception as e:
            print(f"오류: SerpApi로 리뷰 수집 중 - {e}")
            return []

    def classify_reviews(self, all_reviews, model, category_embeddings, threshold):
        print(f"\n--- AI 모델로 리뷰 분류 시작 ---")
        classified_results = []
        for review in all_reviews:
            if not review.strip():
                continue
            review_embedding = model.encode(review, convert_to_tensor=True)
            best_category, highest_score = '기타', 0.0
            for category, cat_embedding in category_embeddings.items():
                cosine_scores = util.cos_sim(review_embedding, cat_embedding)
                max_score = torch.max(cosine_scores).item()
                if max_score > highest_score:
                    highest_score, best_category = max_score, category
            if highest_score < threshold:
                best_category = '기타'
            classified_results.append({'review': review, 'category': best_category})
        return classified_results


# ------------------- 프론트엔드 UI 페이지들 -------------------
class StartPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        tk.Label(self, text="리뷰 기반 관광-기업 분석기", font=("AppleGothic", 22, "bold")).pack(pady=50)
        btn_frame = tk.Frame(self)
        btn_frame.pack(pady=20)
        tk.Button(btn_frame, text="기업 검색", font=("AppleGothic", 16), width=20, height=3,
                  command=lambda: controller.show_frame("CompanySearchPage")).pack(pady=15)
        tk.Button(btn_frame, text="관광지 검색", font=("AppleGothic", 16), width=20, height=3,
                  command=lambda: controller.show_frame("TouristSearchPage")).pack(pady=15)


class CompanySearchPage(tk.Frame):

    def refresh_list(self):
        # 컨트롤러의 데이터 새로고침 함수를 호출합니다.
        self.controller.refresh_company_data()

    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller  # <- controller는 여기에 있어야 합니다.

        header_frame = tk.Frame(self)
        header_frame.pack(fill='x', pady=10, padx=10)
        tk.Button(header_frame, text="< 시작 화면으로", command=lambda: controller.show_frame("StartPage")).pack(side='left')

        # [추가] 새로고침 버튼을 헤더 오른쪽에 추가합니다.
        tk.Button(header_frame, text="목록 새로고침 🔃", command=self.refresh_list).pack(side='right')

        tk.Label(self, text="기업을 선택하여 평가를 확인하세요", font=("AppleGothic", 18, "bold")).pack(pady=20)

        # [추가] 새로고침 상태를 보여줄 라벨을 추가합니다.
        self.status_label = tk.Label(self, text="")
        self.status_label.pack(pady=2)

        self.company_var = tk.StringVar()
        self.company_combo = ttk.Combobox(self, textvariable=self.company_var, font=("AppleGothic", 14),
                                          state="readonly")
        self.company_combo.pack(pady=10, padx=20, fill='x')
        self.company_combo.bind("<<ComboboxSelected>>", self.show_company_review)

        text_frame = tk.Frame(self)
        text_frame.pack(pady=10, padx=20, fill='both', expand=True)
        self.text_area = tk.Text(text_frame, wrap='word', font=("AppleGothic", 12), bg="#f0f0f0", fg='black')
        self.scrollbar = tk.Scrollbar(text_frame, command=self.text_area.yview)
        self.text_area.config(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side='right', fill='y')
        self.text_area.pack(side='left', fill='both', expand=True)

    def update_company_list(self):
        """컨트롤러의 데이터를 기반으로 콤보박스 목록을 업데이트합니다."""
        company_df = self.controller.analyzer.company_df
        if not company_df.empty and '기업명' in company_df.columns:
            company_list = company_df['기업명'].tolist()
            self.company_combo['values'] = company_list
        else:
            self.company_combo['values'] = []
            # 목록이 비었을 경우 안내 문구를 추가할 수 있습니다.
            self.text_area.config(state='normal')
            self.text_area.delete(1.0, 'end')
            self.text_area.insert('end', "불러올 기업 목록이 없습니다.")
            self.text_area.config(state='disabled')

    def show_company_review(self, event=None):
        selected_company = self.company_var.get()
        company_df = self.controller.analyzer.company_df

        self.text_area.config(state='normal')
        self.text_area.delete(1.0, 'end')

        try:
            # 필터링된 데이터에서 '평가' 내용을 가져옵니다.
            review_text = company_df[company_df['기업명'] == selected_company]['평가'].iloc[0]

            # 만약 데이터가 비어있다면(None, NaN) 안내 문구를 표시합니다.
            if pd.isna(review_text) or str(review_text).strip() == '':
                self.text_area.insert('end', "✅ 등록된 평가 정보가 없습니다.")
            else:
                self.text_area.insert('end', review_text)

        except IndexError:
            # 선택된 기업 정보가 없는 경우에 대한 예외 처리
            self.text_area.insert('end', f"⚠️ '{selected_company}'에 대한 정보를 찾을 수 없습니다.")

        self.text_area.config(state='disabled')



class TouristSearchPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.spot_names = []
        header_frame = tk.Frame(self)
        header_frame.pack(fill='x', pady=10, padx=10)
        tk.Button(header_frame, text="< 시작 화면으로", command=lambda: controller.show_frame("StartPage")).pack(side='left')
        tk.Label(self, text="분석할 관광지를 선택하세요", font=("AppleGothic", 18, "bold")).pack(pady=20)
        self.entry_var = tk.StringVar()
        self.entry_var.trace_add("write", self.on_entry_change)
        self.entry = ttk.Combobox(self, textvariable=self.entry_var, font=("AppleGothic", 14))
        self.entry.pack(pady=10, padx=20, fill='x')
        self.listbox = tk.Listbox(self, font=("AppleGothic", 12))
        self.listbox.pack(pady=5, padx=20, fill='x')
        self.listbox.bind("<<ListboxSelect>>", self.on_listbox_select)
        review_frame = tk.Frame(self)
        review_frame.pack(pady=10)
        tk.Label(review_frame, text="최대 구글 리뷰 수:").pack(side='left', padx=5)
        self.max_var = tk.StringVar(value='100')
        tk.Entry(review_frame, textvariable=self.max_var, width=10).pack(side='left')
        tk.Button(self, text="분석 시작!", font=("AppleGothic", 14, "bold"), command=self.start_analysis).pack(pady=20)
        self.status_label = tk.Label(self, text="상태: 대기 중")
        self.status_label.pack(side='bottom', pady=10)

    def update_autocomplete(self, spot_names):
        self.entry['values'] = spot_names
        self.spot_names = spot_names

    def on_entry_change(self, *args):
        search_term = self.entry_var.get().lower()
        self.listbox.delete(0, 'end')
        if search_term:
            filtered_spots = [spot for spot in self.spot_names if search_term in spot.lower()]
            for spot in filtered_spots:
                self.listbox.insert('end', spot)

    def on_listbox_select(self, event):
        selected_indices = self.listbox.curselection()
        if selected_indices:
            self.entry_var.set(self.listbox.get(selected_indices[0]))
            self.listbox.delete(0, 'end')

    def start_analysis(self):
        spot_name = self.entry_var.get()
        if not spot_name or spot_name not in self.spot_names:
            messagebox.showwarning("입력 오류", "목록에 있는 관광지를 선택해주세요.")
            return
        try:
            max_reviews = int(self.max_var.get())
            if max_reviews <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("입력 오류", "최대 리뷰 수는 0보다 큰 정수로 입력해주세요.")
            return
        self.controller.start_full_analysis(spot_name, max_reviews)


class ResultPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        header_frame = tk.Frame(self)
        header_frame.pack(fill='x', pady=10, padx=10)
        tk.Button(header_frame, text="< 관광지 검색으로", command=lambda: controller.show_frame("TouristSearchPage")).pack(
            side='left')
        self.title_label = tk.Label(header_frame, text="", font=("AppleGothic", 18, "bold"))
        self.title_label.pack(side='left', padx=20)
        canvas = tk.Canvas(self)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.scrollable_frame = ttk.Frame(canvas)
        self.scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        scrollbar.pack(side="right", fill="y")

    def update_results(self):
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        result_data = self.controller.analysis_result
        spot_name = result_data['spot_name']
        reviews = result_data['classified_reviews']
        self.title_label.config(text=f"'{spot_name}' 분석 결과")

        recommended_companies = result_data.get('recommended_companies', [])
        main_category = result_data.get('main_category', '없음')
        if recommended_companies:
            reco_frame = ttk.LabelFrame(self.scrollable_frame, text=f" 🏫'{main_category}' 연관 기업 추천", padding=10)
            reco_frame.pack(fill='x', padx=10, pady=10, anchor='n')
            reco_text = ", ".join(recommended_companies)
            tk.Label(reco_frame, text=reco_text, wraplength=550, justify='left').pack(anchor='w')

        category_frame = ttk.LabelFrame(self.scrollable_frame, text=" 💬관광지 리뷰 카테고리 분류 결과", padding=10)
        category_frame.pack(fill='x', padx=10, pady=10, anchor='n')
        category_counts = Counter(result['category'] for result in reviews)
        total_reviews = len(reviews)
        for category, count in category_counts.most_common():
            cat_frame = tk.Frame(category_frame)
            cat_frame.pack(fill='x', pady=5)
            percentage = (count / total_reviews) * 100 if total_reviews > 0 else 0
            label_text = f"● {category}: {count}개 ({percentage:.1f}%)"
            tk.Label(cat_frame, text=label_text, font=("AppleGothic", 14)).pack(side='left')
            tk.Button(cat_frame, text="상세 리뷰 보기", command=lambda c=category: self.show_details(c)).pack(side='right')

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
        self.title_label = tk.Label(header_frame, text="", font=("AppleGothic", 16, "bold"))
        self.title_label.pack(side='left')
        text_frame = tk.Frame(self)
        text_frame.pack(pady=10, padx=20, fill='both', expand=True)
        self.text_area = tk.Text(text_frame, wrap='word', font=("AppleGothic", 12))
        self.scrollbar = tk.Scrollbar(text_frame, command=self.text_area.yview)
        self.text_area.config(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side='right', fill='y')
        self.text_area.pack(side='left', fill='both', expand=True)

    def update_details(self, category):
        spot_name = self.controller.analysis_result['spot_name']
        reviews = self.controller.analysis_result['classified_reviews']
        self.title_label.config(text=f"'{spot_name}' - [{category}] 리뷰 목록")
        self.text_area.config(state='normal')
        self.text_area.delete(1.0, 'end')
        filtered_reviews = [r['review'] for r in reviews if r['category'] == category]
        for i, review in enumerate(filtered_reviews, 1):
            self.text_area.insert('end', f"--- 리뷰 {i} ---\n{review}\n\n")
        self.text_area.config(state='disabled')


# ------------------- 메인 애플리케이션 클래스 (컨트롤러) -------------------
class TouristApp(tk.Tk):
    def __init__(self, api_keys, paths):
        super().__init__()
        self.title("관광-기업 연계 분석기")
        self.geometry("800x650")

        self.paths = paths
        self.analyzer = ReviewAnalyzer(api_keys, self.paths)

        self.all_tourist_spots = []
        self.analysis_result = {}

        self.default_font = font.nametofont("TkDefaultFont")
        self.default_font.configure(family="AppleGothic", size=12)

        container = tk.Frame(self)
        container.pack(side="top", fill="both", expand=True)
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        self.frames = {}
        for F in (StartPage, CompanySearchPage, TouristSearchPage, ResultPage, DetailPage):
            page_name = F.__name__
            frame = F(parent=container, controller=self)
            self.frames[page_name] = frame
            frame.grid(row=0, column=0, sticky="nsew")

        self.show_frame("StartPage")
        self.load_initial_resources()

    def show_frame(self, page_name):
        if page_name == "CompanySearchPage":
            self.frames[page_name].update_company_list()
        if page_name == "ResultPage":
            self.frames[page_name].update_results()
        frame = self.frames[page_name]
        frame.tkraise()

    def load_initial_resources(self):
        self.sbert_model = None  # AI 모델 변수 미리 초기화
        threading.Thread(target=self._load_resources_thread, daemon=True).start()

    def _load_resources_thread(self):
        status_label = self.frames["TouristSearchPage"].status_label

        # 1. 관광지 목록 로딩
        status_label.config(text="상태: 자동완성용 관광지 목록 로딩 중...")
        self.all_tourist_spots = self.analyzer.get_all_tourist_spots()
        spot_names = [spot['title'] for spot in self.all_tourist_spots]
        self.frames["TouristSearchPage"].update_autocomplete(spot_names)

        # 2. AI 모델 및 임베딩 로딩
        status_label.config(text="상태: AI 분석 모델 로딩 중...")
        try:
            self.sbert_model = SentenceTransformer('jhgan/ko-sroberta-multitask')
            self.category_embeddings = {cat: self.sbert_model.encode(kw, convert_to_tensor=True)
                                        for cat, kw in self.analyzer.CATEGORIES.items()}
            print("--- AI 모델 및 카테고리 임베딩 로딩 완료 ---")
            status_label.config(text="상태: 대기 중")
        except Exception as e:
            print(f"AI 모델 로딩 실패: {e}")
            messagebox.showerror("모델 로딩 오류", f"AI 모델을 로딩하는 데 실패했습니다.\n인터넷 연결을 확인하세요.\n\n오류: {e}")
            status_label.config(text="상태: AI 모델 로딩 실패")

    def start_full_analysis(self, spot_name, max_reviews):
        if not self.sbert_model:
            messagebox.showerror("준비 안됨", "아직 AI 모델이 로딩되지 않았습니다. 잠시 후 다시 시도해주세요.")
            return
        threading.Thread(target=self._analysis_thread, args=(spot_name, max_reviews), daemon=True).start()

    def _analysis_thread(self, spot_name, max_reviews):
        try:
            main_page = self.frames["TouristSearchPage"]
            main_page.status_label.config(text=f"상태: '{spot_name}' 분석 시작...")
            selected_spot_info = next((spot for spot in self.all_tourist_spots if spot['title'] == spot_name), None)

            if not selected_spot_info:
                messagebox.showerror("오류", "선택된 관광지 정보를 찾을 수 없습니다.")
                main_page.status_label.config(text="상태: 오류 발생")
                return

            main_page.status_label.config(text="상태: 트립어드바이저 리뷰 수집 중...")
            ta_id = self.analyzer.search_tripadvisor_location_id(spot_name)
            ta_reviews = self.analyzer.get_tripadvisor_reviews(ta_id)

            main_page.status_label.config(text="상태: 구글맵 리뷰 수집 중...")
            google_place_id = self.analyzer.get_google_place_id(selected_spot_info)
            google_reviews = self.analyzer.get_google_reviews_via_serpapi(google_place_id,
                                                                          max_reviews) if google_place_id else []

            all_reviews = ta_reviews + google_reviews
            if not all_reviews:
                messagebox.showinfo("결과 없음", "분석할 리뷰를 찾지 못했습니다.")
                main_page.status_label.config(text="상태: 대기 중")
                return

            main_page.status_label.config(text="상태: AI 모델로 리뷰 분류 중...")
            classified_reviews = self.analyzer.classify_reviews(
                all_reviews,
                self.sbert_model,
                self.category_embeddings,
                0.4
            )

            if not classified_reviews:
                messagebox.showinfo("분석 불가", "리뷰의 카테고리를 분류할 수 없습니다.")
                main_page.status_label.config(text="상태: 대기 중")
                return

            main_category = Counter(result['category'] for result in classified_reviews).most_common(1)[0][0]
            print(f"\n--- 대표 카테고리 선정: {main_category} ---")
            recommended_companies = self.analyzer.recommend_companies(main_category)

            self.analysis_result = {
                'spot_name': spot_name,
                'classified_reviews': classified_reviews,
                'main_category': main_category,
                'recommended_companies': recommended_companies
            }
            self.show_frame("ResultPage")
            main_page.status_label.config(text="상태: 대기 중")

        except Exception as e:
            messagebox.showerror("분석 오류", f"분석 중 오류가 발생했습니다: {e}")
            self.frames["TouristSearchPage"].status_label.config(text="상태: 오류 발생")

    def refresh_company_data(self):
        """새로고침 기능을 별도 스레드에서 실행하도록 호출합니다."""
        threading.Thread(target=self._refresh_company_thread, daemon=True).start()

    def _refresh_company_thread(self):
        company_page = self.frames["CompanySearchPage"]
        currently_selected_company = company_page.company_var.get()

        print(f"\n[진단] 새로고침 시작. 현재 선택된 기업: '{currently_selected_company}'")

        new_company_df = self.analyzer.get_company_data_from_sheet()

        if not new_company_df.empty:
            self.analyzer.company_df = new_company_df
            self.after(0, company_page.update_company_list)

            print(f"[진단] UI 업데이트 시도. '{currently_selected_company}'를 다시 선택합니다.")
            if currently_selected_company and currently_selected_company in new_company_df['기업명'].tolist():
                self.after(0, lambda: company_page.company_var.set(currently_selected_company))
                self.after(0, company_page.show_company_review)
                print("[진단] UI 업데이트 명령 완료.")
            else:
                print("[진단] 이전에 선택된 기업이 없거나, 새 목록에 없어 평가를 업데이트하지 않습니다.")
        else:
            print("[진단] 새로 가져온 데이터가 비어있어 UI를 업데이트하지 않습니다.")

# ------------------- 프로그램 시작점 -------------------
if __name__ == "__main__":
    try:
        # [핵심 수정] resource_path()를 사용하여 .exe 내부의 config.ini 파일을 찾습니다.
        config_file_path = resource_path('config.ini')

        config = configparser.ConfigParser()
        # config.read()는 파일이 없을 경우 빈 리스트를 반환하므로, 이를 확인합니다.
        if not config.read(config_file_path, encoding='utf-8'):
            raise FileNotFoundError(f"config.ini 파일을 찾을 수 없습니다: {config_file_path}")

        api_keys = {
            'korea_tour_api_key': config.get('API_KEYS', 'KOREA_TOUR_API_KEY'),
            'tripadvisor_api_key': config.get('API_KEYS', 'TRIPADVISOR_API_KEY'),
            'serpapi_api_key': config.get('API_KEYS', 'SERPAPI_API_KEY')
        }

        paths = {
            'google_sheet_key_path': config.get('PATHS', 'GOOGLE_SHEET_KEY_PATH'),
            'spreadsheet_name': config.get('PATHS', 'SPREADSHEET_NAME'),
            'worksheet_name': config.get('PATHS', 'WORKSHEET_NAME'),
            'spreadsheet_id': config.get('PATHS', 'spreadsheet_id', fallback=None)
        }

    except FileNotFoundError as e:
        messagebox.showerror("설정 파일 없음", str(e))
        sys.exit()
    except (configparser.NoSectionError, configparser.NoOptionError) as e:
        messagebox.showerror("설정 오류",
                             f"config.ini 파일에 필요한 섹션이나 키가 없습니다.\n[API_KEYS]와 [PATHS] 섹션 및 모든 키가 올바르게 설정되었는지 확인하세요.\n\n오류: {e}")
        sys.exit()
    except Exception as e:
        messagebox.showerror("초기화 오류", f"프로그램 시작 중 오류가 발생했습니다.\n\n오류: {e}")
        sys.exit()

    app = TouristApp(api_keys, paths)
    app.mainloop()
