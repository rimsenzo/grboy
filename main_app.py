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
from urllib.parse import urlparse, parse_qs

# AI 모델 관련 라이브러리
from sentence_transformers import SentenceTransformer, util
import torch

# serpapi 라이브러리
from serpapi import GoogleSearch

# Google Sheets 연동 라이브러리
import gspread
import pandas as pd
from oauth2client.service_account import ServiceAccountCredentials

# Googletrans 라이브러리
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

    def __init__(self, api_keys, paths):
        # --- API 키와 경로 초기화 ---
        self.KOREA_TOUR_API_KEY = api_keys['korea_tour_api_key']
        self.TRIPADVISOR_API_KEY = api_keys['tripadvisor_api_key']
        self.SERPAPI_API_KEY = api_keys['serpapi_api_key']

        self.KOREA_TOUR_API_URL = "http://apis.data.go.kr/B551011/KorService2/areaBasedList2"
        self.TRIPADVISOR_API_URL = "https://api.content.tripadvisor.com/api/v1"

        self.paths = paths
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
            'K-문화': ['K팝', 'K드라마', '영화 촬영지', '한류', '부산국제영화제', 'BIFF', '아이돌', '팬미팅', 'SNS', '인스타그램', '핫플레이스', '슬램덩크'],
            '해양': ['바다', '해변', '해수욕장', '해안', '항구', '섬', '등대', '요트', '해상케이블카', '스카이캡슐', '해변열차', '파도', '수족관', '서핑',
                   '스카이워크'],
            '웰니스': ['힐링', '휴식', '스파', '사우나', '온천', '족욕', '마사지', '산책', '자연', '평화', '평온', '치유', '고요함', '명상', '건강'],
            '뷰티': ['미용', '헤어', '피부', '메이크업', '네일', '에스테틱', '피부관리', '뷰티서비스', '마사지', '미용실', '헤어샵', '네일샵', '살롱', '화장품',
                   'K-뷰티', '퍼스널컬러', '스타일링', '시술', '페이셜'],
            'e스포츠': ['e스포츠', '게임', 'PC방', '대회', '경기장', '프로게이머', '리그오브레전드', 'LCK', '스타크래프트', '페이커', '이스포츠'],
            '미식': ['맛집', '음식', '레스토랑', '카페', '해산물', '길거리 음식', '시장', '회', '조개구이', '돼지국밥', '디저트', '식도락']
        }

    def translate_reviews_to_korean(self, reviews):
        print(f"--- [번역 시작] {len(reviews)}개의 리뷰를 한국어로 번역합니다. ---")
        if not reviews:
            return []

        valid_reviews = [review for review in reviews if review and isinstance(review, str)]
        if not valid_reviews:
            print("   ... 번역할 유효한 텍스트 리뷰가 없습니다.")
            return []

        print(f"   ... {len(valid_reviews)}개의 유효한 리뷰를 번역 대상으로 합니다.")
        translator = Translator()
        translated_reviews = []
        try:
            translations = translator.translate(valid_reviews, dest='ko')
            for t in translations:
                translated_reviews.append(t.text)
            print(f"--- [번역 완료] 성공적으로 {len(translated_reviews)}개를 번역했습니다. ---")
            return translated_reviews
        except Exception as e:
            print(f"오류: 리뷰 번역 중 오류 발생 - {e}")
            return valid_reviews

    def get_company_data_from_sheet(self):
        print("\n--- Google Sheets 데이터 로딩 시작 ---")
        spreadsheet_id = self.paths.get('spreadsheet_id')
        spreadsheet_name = self.paths.get('spreadsheet_name')
        df = pd.DataFrame()

        try:
            key_full_path = resource_path(self.GOOGLE_SHEET_KEY_FILENAME)
            print(f"[1/5] 인증 키 파일 경로 확인: {key_full_path}")

            print("[2/5] Google API 인증 시도...")
            creds = ServiceAccountCredentials.from_json_keyfile_name(key_full_path, self.scopes)
            gc = gspread.authorize(creds)
            print("  - 인증 성공.")

            print("[3/5] 스프레드시트 열기 시도...")
            if spreadsheet_id:
                spreadsheet = gc.open_by_key(spreadsheet_id)
            elif spreadsheet_name:
                spreadsheet = gc.open(spreadsheet_name)
            else:
                messagebox.showerror("설정 오류", "config.ini에 spreadsheet_id 또는 spreadsheet_name이 없습니다.")
                return df
            print("  - 스프레드시트 열기 성공.")

            print(f"[4/5] '{self.WORKSHEET_NAME}' 워크시트 열기 시도...")
            worksheet = spreadsheet.worksheet(self.WORKSHEET_NAME)
            print("  - 워크시트 열기 성공.")

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
            data = response.json().get('data', [])
            return data[0]['location_id'] if data else None
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

    def get_google_place_id(self, place_name):
        print(f"--- Google에서 '{place_name}'의 Place ID 검색 시작 ---")
        search_params = {
            "engine": "google_maps",
            "q": place_name,
            "api_key": self.SERPAPI_API_KEY
        }
        try:
            response = requests.get("https://serpapi.com/search.json", params=search_params, timeout=10)
            response.raise_for_status()
            search_data = response.json()
            place_results = search_data.get("place_results", {})
            place_id = place_results.get("place_id")

            if place_id:
                print(f"   ... Place ID를 찾았습니다: {place_id}")
                return place_id
            else:
                print("   ... Place ID를 찾지 못했습니다.")
                return None
        except requests.exceptions.RequestException as e:
            print(f"!!! 오류: 장소 검색 API 요청에 실패했습니다. -> {e}")
            return None

    def get_google_reviews_via_serpapi(self, place_id, max_reviews):
        print(f"\n--- 구글 리뷰 가져오기 시작 (최대 {max_reviews}개 목표) ---")
        if not place_id:
            return []

        all_review_texts = []
        params = {
            "engine": "google_maps_reviews",
            "place_id": place_id,
            "hl": "ko",
            "api_key": self.SERPAPI_API_KEY
        }

        try:
            while True:
                print(f"   ... API 요청 중... (현재 수집된 리뷰: {len(all_review_texts)}개)")
                search = GoogleSearch(params)
                results = search.get_dict()

                reviews_data = results.get("reviews", [])
                if not reviews_data:
                    print("   ... 더 이상 리뷰 데이터가 없어 중단합니다.")
                    break

                new_reviews = [r.get('snippet', '') for r in reviews_data if r.get('snippet')]
                all_review_texts.extend(new_reviews)
                print(f"   ... 리뷰 {len(new_reviews)}개를 새로 추가했습니다.")

                pagination = results.get("serpapi_pagination")
                if not pagination or "next" not in pagination:
                    print("--- 다음 페이지가 없어 리뷰 수집을 완료합니다. ---")
                    break

                if len(all_review_texts) >= max_reviews:
                    print(f"--- 목표 리뷰 수({max_reviews}개)에 도달하여 수집을 중단합니다. ---")
                    break

                next_url = pagination["next"]
                parsed_url = urlparse(next_url)
                query_params = parse_qs(parsed_url.query)
                next_page_token = query_params.get('next_page_token', [None])[0]

                if not next_page_token:
                    print("--- 다음 페이지 URL에 토큰이 없어 수집을 완료합니다. ---")
                    break

                params["next_page_token"] = next_page_token
                time.sleep(1)

            return all_review_texts[:max_reviews]

        except Exception as e:
            print(f"오류: SerpApi로 리뷰 수집 중 심각한 오류 발생 - {e}")
            return all_review_texts[:max_reviews]

    def classify_reviews(self, all_reviews, model, category_embeddings, threshold):
        print(f"\n--- AI 모델로 리뷰 분류 시작 ---")
        classified_results = []
        for review in all_reviews:
            if not review or not review.strip():
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
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        header_frame = tk.Frame(self)
        header_frame.pack(fill='x', pady=10, padx=10)
        tk.Button(header_frame, text="< 시작 화면으로", command=lambda: controller.show_frame("StartPage")).pack(side='left')
        tk.Button(header_frame, text="목록 새로고침 🔃", command=self.refresh_list).pack(side='right')
        tk.Label(self, text="기업을 선택하여 평가를 확인하세요", font=("AppleGothic", 18, "bold")).pack(pady=20)
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

    def refresh_list(self):
        self.controller.refresh_company_data()

    def update_company_list(self):
        company_df = self.controller.analyzer.company_df
        if not company_df.empty and '기업명' in company_df.columns:
            self.company_combo['values'] = company_df['기업명'].tolist()
        else:
            self.company_combo['values'] = []
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
            review_text = company_df[company_df['기업명'] == selected_company]['평가'].iloc[0]
            if pd.isna(review_text) or str(review_text).strip() == '':
                self.text_area.insert('end', "✅ 등록된 평가 정보가 없습니다.")
            else:
                self.text_area.insert('end', review_text)
        except IndexError:
            self.text_area.insert('end', f"⚠️ '{selected_company}'에 대한 정보를 찾을 수 없습니다.")
        self.text_area.config(state='disabled')


class TouristSearchPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.all_spot_details = []
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
        self.max_var = tk.StringVar(value='50')
        tk.Entry(review_frame, textvariable=self.max_var, width=10).pack(side='left')
        tk.Button(self, text="분석 시작!", font=("AppleGothic", 14, "bold"), command=self.start_analysis).pack(pady=20)
        self.status_label = tk.Label(self, text="상태: 대기 중")
        self.status_label.pack(side='bottom', pady=10)

    def update_autocomplete(self, all_spot_details):
        self.all_spot_details = all_spot_details
        self.spot_names = [spot['title'] for spot in all_spot_details]
        self.entry['values'] = self.spot_names

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
        self.sbert_model = None
        self.category_embeddings = None
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
        status_label.config(text="상태: 자동완성용 관광지 목록 로딩 중...")
        self.all_tourist_spots = self.analyzer.get_all_tourist_spots()
        self.frames["TouristSearchPage"].update_autocomplete(self.all_tourist_spots)

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

            main_page.status_label.config(text="상태: 트립어드바이저 리뷰 수집 중...")
            ta_id = self.analyzer.search_tripadvisor_location_id(spot_name)
            ta_reviews = self.analyzer.get_tripadvisor_reviews(ta_id) if ta_id else []

            main_page.status_label.config(text="상태: 구글맵 리뷰 수집 중...")
            # [핵심 오류 수정] 딕셔너리가 아닌 'spot_name' 문자열을 전달하도록 변경
            google_place_id = self.analyzer.get_google_place_id(spot_name)
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
            classified_reviews = self.analyzer.classify_reviews(all_reviews, self.sbert_model, self.category_embeddings,
                                                                0.4)

            if not classified_reviews:
                messagebox.showinfo("분석 불가", "리뷰의 카테고리를 분류할 수 없습니다.")
                main_page.status_label.config(text="상태: 대기 중")
                return

            main_category = \
            Counter(result['category'] for result in classified_reviews if result['category'] != '기타').most_common(1)[
                0][0]
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
        threading.Thread(target=self._refresh_company_thread, daemon=True).start()

    def _refresh_company_thread(self):
        company_page = self.frames["CompanySearchPage"]
        company_page.status_label.config(text="상태: 구글 시트에서 최신 기업 정보를 가져옵니다...")
        new_company_df = self.analyzer.get_company_data_from_sheet()

        if not new_company_df.empty:
            self.analyzer.company_df = new_company_df
            self.after(0, company_page.update_company_list)

        company_page.status_label.config(text="")


# ------------------- 프로그램 시작점 -------------------
if __name__ == "__main__":
    try:
        config_file_path = resource_path('config.ini')
        config = configparser.ConfigParser()
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
        messagebox.showerror("설정 오류", f"config.ini 파일에 필요한 섹션이나 키가 없습니다.\n오류: {e}")
        sys.exit()
    except Exception as e:
        messagebox.showerror("초기화 오류", f"프로그램 시작 중 오류가 발생했습니다.\n오류: {e}")
        sys.exit()

    app = TouristApp(api_keys, paths)
    app.mainloop()
