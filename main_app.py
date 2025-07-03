import tkinter as tk
from tkinter import ttk, messagebox, font
import threading
import requests
import warnings
import json
import time
import configparser
from collections import Counter

from sentence_transformers import SentenceTransformer, util
import torch
from serpapi import GoogleSearch

warnings.filterwarnings('ignore', message='Unverified HTTPS request')


# ------------------- 백엔드 로직: ReviewAnalyzer 클래스 -------------------
# 이 클래스의 코드는 변경할 필요가 없습니다. 이전과 동일합니다.
class ReviewAnalyzer:
    def __init__(self, api_keys):
        self.KOREA_TOUR_API_KEY = api_keys['korea_tour_api_key']
        self.TRIPADVISOR_API_KEY = api_keys['tripadvisor_api_key']
        self.SERPAPI_API_KEY = api_keys['serpapi_api_key']

        self.KOREA_TOUR_API_URL = "http://apis.data.go.kr/B551011/KorService2/areaBasedList2"
        self.TRIPADVISOR_API_URL = "https://api.content.tripadvisor.com/api/v1"

    def get_all_tourist_spots(self):
        print("--- 자동완성 목록 생성: 모든 관광지 정보 가져오는 중 ---")
        all_spots = []
        page_no = 1

        params = {
            'serviceKey': self.KOREA_TOUR_API_KEY,
            'numOfRows': 100,
            'pageNo': page_no,
            'MobileOS': 'ETC',
            'MobileApp': 'TouristAnalyzerApp',
            '_type': 'json',
            'arrange': 'A',
            'areaCode': '6',
            'contentTypeId': '12'
        }

        try:
            while True:
                params['pageNo'] = page_no
                response = requests.get(self.KOREA_TOUR_API_URL, params=params, timeout=10)
                response.raise_for_status()
                data = response.json()

                items = data.get('response', {}).get('body', {}).get('items', {}).get('item', [])
                if not items:
                    total_count = data.get('response', {}).get('body', {}).get('totalCount', 0)
                    if total_count == 0 and page_no == 1:
                        print(f"--- API가 반환한 전체 결과 수가 0개입니다. 키 또는 파라미터를 확인하세요. ---")
                    else:
                        print(f"--- 페이지 {page_no}에서 더 이상 아이템을 찾지 못했습니다. 목록 생성을 종료합니다. ---")
                    break

                for item in items:
                    all_spots.append({'title': item.get('title'), 'addr1': item.get('addr1', '')})

                total_count = data.get('response', {}).get('body', {}).get('totalCount', 0)
                if len(all_spots) >= total_count:
                    print("--- 모든 관광지 정보를 가져왔습니다. ---")
                    break

                page_no += 1
                print(f"   ... 다음 페이지({page_no})를 가져옵니다 (현재까지 {len(all_spots)}개 / 전체 {total_count}개)")
                time.sleep(0.5)
        except Exception as e:
            print(f"오류: 국문관광정보 API 호출 중 에러 발생 - {e}")

        print(f"--- 최종적으로 {len(all_spots)}개의 관광지 목록을 생성했습니다. ---")
        return all_spots

    # ... 이하 나머지 백엔드 함수들은 이전과 동일 ...
    def search_tripadvisor_location_id(self, location_name):
        print(f"\n--- 2단계: 트립어드바이저에서 '{location_name}'의 Location ID 검색 시작 ---")
        url = f"{self.TRIPADVISOR_API_URL}/location/search"
        params = {'key': self.TRIPADVISOR_API_KEY, 'searchQuery': location_name, 'language': 'ko'}
        try:
            response = requests.get(url, params=params, headers={'accept': 'application/json'}, timeout=5)
            response.raise_for_status()
            data = response.json().get('data', [])
            return data[0]['location_id'] if data else None
        except Exception as e:
            print(f"오류: 트립어드바이저 Location 검색 API 호출 중 - {e}");
            return None

    def get_tripadvisor_reviews(self, location_id):
        print(f"\n--- 3단계: 트립어드바이저 리뷰 가져오기 시작 ---")
        if not location_id: return []
        url = f"{self.TRIPADVISOR_API_URL}/location/{location_id}/reviews"
        params = {'key': self.TRIPADVISOR_API_KEY, 'language': 'ko'}
        try:
            response = requests.get(url, params=params, headers={'accept': 'application/json'}, timeout=10)
            response.raise_for_status()
            reviews = response.json().get('data', [])
            return [review['text'] for review in reviews if 'text' in review]
        except Exception as e:
            print(f"오류: 트립어드바이저 리뷰 API 호출 중 - {e}");
            return []

    def get_google_reviews_via_serpapi_pro(self, location_info, max_reviews):
        print(f"\n--- 4단계: 구글 리뷰 가져오기 시작 (최대 {max_reviews}개 목표) ---")
        try:
            params = {"engine": "google_maps", "q": f"{location_info['title']}, {location_info['addr1']}",
                      "type": "search", "hl": "ko", "api_key": self.SERPAPI_API_KEY}
            search = GoogleSearch(params)
            results = search.get_dict()
            place_id = results.get("local_results", [{}])[0].get("place_id")
            if not place_id: return []
            all_review_texts, params = [], {"engine": "google_maps_reviews", "place_id": place_id, "hl": "ko",
                                            "api_key": self.SERPAPI_API_KEY}
            while True:
                search = GoogleSearch(params)
                results = search.get_dict()
                reviews_data = results.get("reviews", [])
                if not reviews_data: break
                all_review_texts.extend([review.get('snippet', '') for review in reviews_data if review.get('snippet')])
                if len(all_review_texts) >= max_reviews or "next_page_token" not in results.get("serpapi_pagination",
                                                                                                {}): break
                params["next_page_token"] = results["serpapi_pagination"]["next_page_token"]
                time.sleep(1)
            return all_review_texts[:max_reviews]
        except Exception as e:
            print(f"오류: SerpApi 호출 중 - {e}");
            return []

    def classify_reviews(self, all_reviews, model, category_embeddings, threshold):
        print(f"\n--- 5단계: AI 모델로 리뷰 분류 시작 ---")
        classified_results = []
        for review in all_reviews:
            if not review.strip(): continue
            review_embedding = model.encode(review, convert_to_tensor=True)
            best_category, highest_score = '기타', 0.0
            for category, cat_embedding in category_embeddings.items():
                cosine_scores = util.cos_sim(review_embedding, cat_embedding)
                max_score_in_category = torch.max(cosine_scores).item()
                if max_score_in_category > highest_score:
                    highest_score, best_category = max_score_in_category, category
            if highest_score < threshold: best_category = '기타'
            classified_results.append({'review': review, 'category': best_category})
        return classified_results


# ------------------- 프론트엔드 UI: Tkinter 애플리케이션 -------------------
# 이 부분의 코드도 변경할 필요가 없습니다. 이전과 동일합니다.
class TouristApp(tk.Tk):
    def __init__(self, api_keys):
        super().__init__();
        self.title("관광지 리뷰 분석기");
        self.geometry("800x600")
        self.analyzer = ReviewAnalyzer(api_keys);
        self.all_tourist_spots = [];
        self.analysis_result = {}
        self.default_font = font.nametofont("TkDefaultFont");
        self.default_font.configure(family="AppleGothic", size=12)
        container = tk.Frame(self);
        container.pack(side="top", fill="both", expand=True)
        container.grid_rowconfigure(0, weight=1);
        container.grid_columnconfigure(0, weight=1)
        self.frames = {}
        for F in (MainPage, ResultPage, DetailPage):
            page_name = F.__name__;
            frame = F(parent=container, controller=self)
            self.frames[page_name] = frame;
            frame.grid(row=0, column=0, sticky="nsew")
        self.show_frame("MainPage");
        self.load_tourist_spots()

    def show_frame(self, page_name):
        self.frames[page_name].tkraise()

    def load_tourist_spots(self):
        threading.Thread(target=self._load_spots_thread, daemon=True).start()

    def _load_spots_thread(self):
        self.frames["MainPage"].status_label.config(text="상태: 자동완성용 관광지 목록 로딩 중...")
        self.all_tourist_spots = self.analyzer.get_all_tourist_spots()
        spot_names = [spot['title'] for spot in self.all_tourist_spots]
        self.frames["MainPage"].update_autocomplete(spot_names);
        self.frames["MainPage"].status_label.config(text="상태: 대기 중")

    def start_full_analysis(self, spot_name, max_reviews):
        threading.Thread(target=self._analysis_thread, args=(spot_name, max_reviews), daemon=True).start()

    def _analysis_thread(self, spot_name, max_reviews):
        try:
            self.frames["MainPage"].status_label.config(text=f"상태: '{spot_name}' 분석 시작...")
            selected_spot_info = next((spot for spot in self.all_tourist_spots if spot['title'] == spot_name), None)
            if not selected_spot_info: messagebox.showerror("오류", "선택된 관광지 정보를 찾을 수 없습니다."); self.frames[
                "MainPage"].status_label.config(text="상태: 오류 발생"); return
            self.frames["MainPage"].status_label.config(text="상태: 트립어드바이저 리뷰 수집 중...")
            ta_id = self.analyzer.search_tripadvisor_location_id(spot_name);
            ta_reviews = self.analyzer.get_tripadvisor_reviews(ta_id)
            self.frames["MainPage"].status_label.config(text="상태: 구글 리뷰 수집 중...")
            google_reviews = self.analyzer.get_google_reviews_via_serpapi_pro(selected_spot_info, max_reviews)
            all_reviews = ta_reviews + google_reviews
            if not all_reviews: messagebox.showinfo("결과 없음", "분석할 리뷰를 찾지 못했습니다."); self.frames[
                "MainPage"].status_label.config(text="상태: 대기 중"); return
            self.frames["MainPage"].status_label.config(text="상태: AI 모델로 리뷰 분류 중...")
            model = SentenceTransformer('jhgan/ko-sroberta-multitask')
            categories = {'웰니스관광': ['건강', '힐링', '스파'], '미식관광': ['맛집', '음식', '카페'], '해양관광': ['바다', '해변', '요트']}
            category_embeddings = {cat: model.encode(kw, convert_to_tensor=True) for cat, kw in categories.items()}
            classified_reviews = self.analyzer.classify_reviews(all_reviews, model, category_embeddings, 0.4)
            self.analysis_result = {'spot_name': spot_name, 'classified_reviews': classified_reviews}
            self.frames["ResultPage"].update_results();
            self.show_frame("ResultPage");
            self.frames["MainPage"].status_label.config(text="상태: 대기 중")
        except Exception as e:
            messagebox.showerror("분석 오류", f"분석 중 오류가 발생했습니다: {e}"); self.frames["MainPage"].status_label.config(
                text="상태: 오류 발생")


class MainPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent);
        self.controller = controller;
        self.spot_names = []
        tk.Label(self, text="분석할 관광지를 선택하세요", font=("AppleGothic", 18, "bold")).pack(pady=20)
        self.entry_var = tk.StringVar();
        self.entry_var.trace("w", self.on_entry_change)
        self.entry = ttk.Combobox(self, textvariable=self.entry_var, font=("AppleGothic", 14));
        self.entry.pack(pady=10, padx=20, fill='x')
        self.listbox = tk.Listbox(self, font=("AppleGothic", 12));
        self.listbox.pack(pady=5, padx=20, fill='x');
        self.listbox.bind("<<ListboxSelect>>", self.on_listbox_select)
        review_frame = tk.Frame(self);
        review_frame.pack(pady=10);
        tk.Label(review_frame, text="최대 구글 리뷰 수:").pack(side='left', padx=5)
        self.max_var = tk.StringVar(value='100');
        tk.Entry(review_frame, textvariable=self.max_var, width=10).pack(side='left')
        tk.Button(self, text="분석 시작!", font=("AppleGothic", 14, "bold"), command=self.start_analysis).pack(pady=20)
        self.status_label = tk.Label(self, text="상태: 대기 중");
        self.status_label.pack(side='bottom', pady=10)

    def update_autocomplete(self, spot_names):
        self.entry['values'] = spot_names; self.spot_names = spot_names

    def on_entry_change(self, *args):
        search_term = self.entry_var.get().lower();
        self.listbox.delete(0, 'end')
        if search_term:
            filtered_spots = [spot for spot in self.spot_names if search_term in spot.lower()]
            for spot in filtered_spots: self.listbox.insert('end', spot)

    def on_listbox_select(self, event):
        if selected_indices := self.listbox.curselection():
            selected_spot = self.listbox.get(selected_indices[0]);
            self.entry_var.set(selected_spot);
            self.listbox.delete(0, 'end')

    def start_analysis(self):
        spot_name = self.entry_var.get()
        if not spot_name: messagebox.showwarning("입력 오류", "관광지를 선택해주세요."); return
        try:
            max_reviews = int(self.max_var.get());
        except ValueError:
            messagebox.showwarning("입력 오류", "최대 리뷰 수는 양의 정수로 입력해주세요."); return
        self.controller.start_full_analysis(spot_name, max_reviews)


class ResultPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent);
        self.controller = controller
        header_frame = tk.Frame(self);
        header_frame.pack(fill='x', pady=10)
        tk.Button(header_frame, text="< 뒤로가기", command=lambda: controller.show_frame("MainPage")).pack(side='left',
                                                                                                       padx=10)
        self.title_label = tk.Label(header_frame, text="", font=("AppleGothic", 18, "bold"));
        self.title_label.pack(side='left')
        self.results_frame = tk.Frame(self);
        self.results_frame.pack(pady=10, padx=20, fill='both', expand=True)

    def update_results(self):
        for widget in self.results_frame.winfo_children(): widget.destroy()
        spot_name = self.controller.analysis_result['spot_name'];
        reviews = self.controller.analysis_result['classified_reviews']
        self.title_label.config(text=f"'{spot_name}' 분석 결과")
        category_counts = Counter(result['category'] for result in reviews)
        for category, count in category_counts.most_common():
            cat_frame = tk.Frame(self.results_frame);
            cat_frame.pack(fill='x', pady=5)
            tk.Label(cat_frame, text=f"- {category}: {count}개", font=("AppleGothic", 14)).pack(side='left')
            tk.Button(cat_frame, text="리뷰 보기", command=lambda c=category: self.show_details(c)).pack(side='right')

    def show_details(self, category):
        self.controller.frames["DetailPage"].update_details(category); self.controller.show_frame("DetailPage")


class DetailPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent);
        self.controller = controller
        header_frame = tk.Frame(self);
        header_frame.pack(fill='x', pady=10)
        tk.Button(header_frame, text="< 뒤로가기", command=lambda: controller.show_frame("ResultPage")).pack(side='left',
                                                                                                         padx=10)
        self.title_label = tk.Label(header_frame, text="", font=("AppleGothic", 16, "bold"));
        self.title_label.pack(side='left')
        text_frame = tk.Frame(self);
        text_frame.pack(pady=10, padx=20, fill='both', expand=True)
        self.text_area = tk.Text(text_frame, wrap='word', font=("AppleGothic", 12))
        self.scrollbar = tk.Scrollbar(text_frame, command=self.text_area.yview);
        self.text_area.config(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side='right', fill='y');
        self.text_area.pack(side='left', fill='both', expand=True)

    def update_details(self, category):
        spot_name = self.controller.analysis_result['spot_name'];
        reviews = self.controller.analysis_result['classified_reviews']
        self.title_label.config(text=f"'{spot_name}' - [{category}] 리뷰 목록");
        self.text_area.config(state='normal');
        self.text_area.delete(1.0, 'end')
        filtered_reviews = [r['review'] for r in reviews if r['category'] == category]
        for i, review in enumerate(filtered_reviews, 1): self.text_area.insert('end', f"--- 리뷰 {i} ---\n{review}\n\n")
        self.text_area.config(state='disabled')


# --- 프로그램 시작점 ---
import os  # 파일 경로를 다루기 위해 os 모듈을 추가합니다.

# ... (파일의 윗부분, 모든 클래스 정의는 그대로 둡니다) ...

# --- 프로그램 시작점 ---
if __name__ == "__main__":

    # --- 최종 해결책: 실행 파일의 위치를 기준으로 config.ini 경로를 찾습니다 ---
    try:
        # 현재 스크립트 파일이 있는 디렉토리의 절대 경로를 가져옵니다.
        # 이 방법을 사용하면 어디서 프로그램을 실행하든 항상 정확한 경로를 찾을 수 있습니다.
        current_dir = os.path.dirname(os.path.abspath(__file__))
        # config.ini 파일의 전체 경로를 만듭니다.
        config_file_path = os.path.join(current_dir, 'config.ini')

        print(f"디버그: config.ini 파일 경로를 찾습니다 -> {config_file_path}")

        config = configparser.ConfigParser()
        # 찾은 절대 경로에서 파일을 읽습니다.
        read_files = config.read(config_file_path, encoding='utf-8')

        # 파일을 성공적으로 읽었는지 확인합니다.
        if not read_files:
            raise FileNotFoundError(f"지정된 경로에 config.ini 파일이 없습니다: {config_file_path}")

        # 이제 안전하게 키를 읽어올 수 있습니다.
        api_keys = {
            'korea_tour_api_key': config.get('API_KEYS', 'KOREA_TOUR_API_KEY'),
            'tripadvisor_api_key': config.get('API_KEYS', 'TRIPADVISOR_API_KEY'),
            'serpapi_api_key': config.get('API_KEYS', 'SERPAPI_API_KEY'),
        }
    except Exception as e:
        messagebox.showerror("설정 오류", f"config.ini 파일을 읽는 중 오류가 발생했습니다.\n파일이 존재하고, 경로와 키 이름이 올바른지 확인하세요.\n\n오류: {e}")
        exit()

    app = TouristApp(api_keys)
    app.mainloop()
