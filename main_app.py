# ===================================================================
# 1. Imports and Global Setup
# ===================================================================

# --- 1. Python Standard Libraries ---
import sys
import os
import configparser
import threading
import warnings
from collections import Counter

# --- 2. GUI (Tkinter) Libraries ---
import tkinter as tk
from tkinter import ttk, messagebox, font, filedialog

# --- 3. Third-Party Data & Web Libraries ---
try:
    import pandas as pd
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
    from serpapi import GoogleSearch
    import matplotlib
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    import requests

    matplotlib.use('TkAgg')
except ImportError as e:
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror("라이브러리 오류", f"필수 라이브러리가 설치되지 않았습니다: {e.name}\n'pip install {e.name}' 명령으로 설치해주세요.")
    sys.exit(1)


# --- 4. Global Configurations & Utility Functions ---
def setup_fonts():
    """OS 환경에 맞춰 Matplotlib의 기본 한글 폰트를 설정합니다."""
    if sys.platform == "win32":
        font_family = "Malgun Gothic"
    elif sys.platform == "darwin":
        font_family = "AppleGothic"
    else:
        font_family = "NanumGothic"
    try:
        plt.rc('font', family=font_family)
        plt.rc('axes', unicode_minus=False)
    except Exception:
        print(f"경고: '{font_family}' 폰트를 설정할 수 없습니다. 그래프의 한글이 깨질 수 있습니다.")


def setup_warnings():
    """불필요한 경고 메시지를 숨겨 콘솔을 깨끗하게 유지합니다."""
    warnings.filterwarnings("ignore", category=UserWarning)
    warnings.filterwarnings('ignore', message='Unverified HTTPS request')


def resource_path(relative_path):
    """ 개발 환경과 PyInstaller 배포 환경 모두에서 리소스 파일 경로를 올바르게 찾습니다. """
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


# --- 5. Initial Setup Execution ---
setup_fonts()
setup_warnings()


# ===================================================================
# 2. Backend Logic: ReviewAnalyzer Class
# ===================================================================
class ReviewAnalyzer:
    """ API 호출, 데이터 가공, AI 분석 등 핵심 비즈니스 로직을 담당합니다. """

    ENTERPRISE_CATEGORIES = ["관광인프라", "MICE", "해양·레저", "여행서비스업", "테마·콘텐츠관광", "관광플랫폼", "지역특화콘텐츠", "관광딥테크", "관광기념품·캐릭터", "미디어마케팅"]
    CATEGORY_WEIGHT_1ST = 0.5  # 1순위 일치 시 가산점
    CATEGORY_WEIGHT_2ND = 0.3  # 2순위 일치 시 가산점

    TOURIST_SPOT_CATEGORIES = {'K-문화': ['K팝', 'K드라마', '영화 촬영지'], '해양': ['바다', '해변', '요트'], '웰니스': ['힐링', '휴식', '스파'],
                               '뷰티': ['미용', '헤어', '피부'], 'e스포츠': ['e스포츠', '게임', 'PC방'], '미식': ['맛집', '음식', '레스토랑']}

    def __init__(self, api_keys, paths):
        self.KOREA_TOUR_API_KEY = api_keys.get('korea_tour_api_key')
        self.TRIPADVISOR_API_KEY = api_keys.get('tripadvisor_api_key')
        self.SERPAPI_API_KEY = api_keys.get('serpapi_api_key')
        self.KOREA_TOUR_API_URL = "http://apis.data.go.kr/B551011/KorService2/areaBasedList2"
        self.TRIPADVISOR_API_URL = "https://api.content.tripadvisor.com/api/v1"
        self.paths = paths
        self.unified_profiles, self.company_review_df, self.preference_df = {}, pd.DataFrame(), pd.DataFrame()
        self.sbert_model, self.tourist_category_embeddings, self.enterprise_category_embeddings = None, None, None

    def _load_sbert_model(self):
        """AI SBERT 모델과 카테고리 임베딩을 로드합니다."""
        try:
            from sentence_transformers import SentenceTransformer
            import torch
            model_path = resource_path('jhgan/ko-sroberta-multitask')
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
            self.sbert_model = SentenceTransformer('jhgan/ko-sroberta-multitask', device=device)
            self.enterprise_category_embeddings = {cat: self.sbert_model.encode(cat, convert_to_tensor=True) for cat in self.ENTERPRISE_CATEGORIES}
            self.tourist_category_embeddings = {cat: self.sbert_model.encode(kw, convert_to_tensor=True) for cat, kw in self.TOURIST_SPOT_CATEGORIES.items()}
        except Exception as e:
            raise RuntimeError(f"AI 모델 로딩 실패: {e}")

    def load_and_unify_data_sources(self):
        """각 시트의 데이터를 먼저 정제한 후 통합하여 'Reindexing' 오류를 방지합니다."""
        def robust_get_dataframe(worksheet):
            """시트의 헤더가 비정상적이거나 중복되어도 안전하게 DataFrame을 생성합니다."""
            try:
                all_values = worksheet.get_all_values()
                if not all_values: return pd.DataFrame()
                header_row_idx = 0
                for i, row in enumerate(all_values):
                    if any(field.strip() for field in row):
                        header_row_idx = i
                        break
                header = all_values[header_row_idx]
                if len(header) != len(set(header)):
                    cols = pd.Series(header)
                    for dup in cols[cols.duplicated()].unique():
                        cols[cols[cols == dup].index.values.tolist()] = [f"{dup}.{i}" if i != 0 else dup for i in range(sum(cols == dup))]
                    header = list(cols)
                data = all_values[header_row_idx + 1:]
                if not data: return pd.DataFrame(columns=header)
                df = pd.DataFrame(data, columns=header)
                df = df.loc[:, ~df.columns.str.contains('^Unnamed')]
                if '' in df.columns: df = df.drop(columns=[''])
                return df.dropna(how='all')
            except Exception as e:
                print(f"경고: '{worksheet.title}' 시트 처리 중 오류: {e}")
                return pd.DataFrame()

        try:
            creds = ServiceAccountCredentials.from_json_keyfile_name(resource_path(self.paths['google_sheet_key_path']), ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive'])
            gc = gspread.authorize(creds)
            spreadsheet = gc.open(self.paths['spreadsheet_name'])
            self.company_review_df = robust_get_dataframe(spreadsheet.worksheet("기업리뷰_데이터"))
            if not self.company_review_df.empty and '타임스탬프' in self.company_review_df.columns:
                series = self.company_review_df['타임스탬프'].astype(str).str.replace('오전', 'AM').str.replace('오후', 'PM')
                self.company_review_df['year'] = pd.to_datetime(series, errors='coerce').dt.year
                self.company_review_df.dropna(subset=['year'], inplace=True)
                self.company_review_df['year'] = self.company_review_df['year'].astype(int)

            base_df = robust_get_dataframe(spreadsheet.worksheet("기업목록"))
            new_df = robust_get_dataframe(spreadsheet.worksheet("기업목록_데이터"))
            processed_dfs = []
            if not base_df.empty and '기업ID' in base_df.columns:
                base_df.dropna(subset=['기업ID'], inplace=True)
                base_df = base_df[base_df['기업ID'].astype(str).str.strip() != '']
                base_df['기업ID'] = base_df['기업ID'].astype(str).str.strip()
                base_df['year'] = 2025
                processed_dfs.append(base_df)
            if not new_df.empty and '기업ID' in new_df.columns:
                new_df.dropna(subset=['기업ID'], inplace=True)
                new_df = new_df[new_df['기업ID'].astype(str).str.strip() != '']
                new_df['기업ID'] = new_df['기업ID'].astype(str).str.strip()
                if '타임스탬프' in new_df.columns:
                    new_df['year'] = pd.to_datetime(new_df['타임스탬프'], errors='coerce').dt.year
                    new_df.dropna(subset=['year'], inplace=True)
                    new_df['year'] = new_df['year'].astype(int)
                    processed_dfs.append(new_df)
            if not processed_dfs: raise ValueError("유효한 기업 정보 시트를 찾을 수 없습니다.")

            final_df = pd.concat(processed_dfs, ignore_index=True)
            if '기업ID' in final_df.columns and 'year' in final_df.columns:
                final_df.drop_duplicates(subset=['기업ID', 'year'], keep='last', inplace=True)
            elif '기업ID' in final_df.columns:
                final_df.drop_duplicates(subset=['기업ID'], keep='last', inplace=True)

            self.unified_profiles = {}
            if not final_df.empty and '기업명' in final_df.columns:
                final_df.dropna(subset=['기업명'], inplace=True)
                if 'year' in final_df.columns:
                    yearly_data = final_df.dropna(subset=['year'])
                    base_info_source = base_df.copy()
                    if not base_info_source.empty:
                        base_info_source.drop_duplicates(subset=['기업ID'], keep='last', inplace=True)
                        base_info_columns = ['기업ID', '사업내용'] if '사업내용' in base_info_source.columns else ['기업ID']
                        base_info_df = base_info_source[base_info_columns]
                    else:
                        base_info_df = pd.DataFrame(columns=['기업ID', '사업내용'])

                    for year, group in yearly_data.groupby('year'):
                        group_deduped = group.drop_duplicates(subset=['기업명'], keep='last')
                        if not base_info_df.empty and '사업내용' in base_info_df.columns:
                            group_deduped['기업ID'] = group_deduped['기업ID'].astype(str)
                            merged_group = pd.merge(group_deduped, base_info_df, on='기업ID', how='left', suffixes=('', '_base'))
                            if '사업내용_base' in merged_group.columns:
                                merged_group['사업내용'] = merged_group['사업내용'].fillna(merged_group['사업내용_base'])
                                merged_group.drop(columns=['사업내용_base'], inplace=True)
                            self.unified_profiles[str(int(year))] = merged_group.set_index('기업명')
                        else:
                            self.unified_profiles[str(int(year))] = group_deduped.set_index('기업명')

            self.preference_df = robust_get_dataframe(spreadsheet.worksheet("선호분야"))
        except Exception as e:
            import traceback
            traceback.print_exc()
            raise RuntimeError(f"Google Sheets 데이터 처리 실패: {e}")

    def get_yearly_category_distribution(self, company_name):
        from sentence_transformers import util
        if not self.sbert_model: return {}
        yearly_distribution = {}
        profile_keys = sorted([k for k in self.unified_profiles.keys() if k.isdigit()], key=int)
        for year_key in profile_keys:
            profile_df = self.unified_profiles.get(year_key)
            if profile_df is None or company_name not in profile_df.index: continue
            company_profile = profile_df.loc[company_name]
            base_scores = {cat: 0.0 for cat in self.ENTERPRISE_CATEGORIES}
            weights = {1: 50, 2: 30, 3: 20}
            for rank, weight in weights.items():
                cat_name = company_profile.get(f'{rank}순위 분류')
                if cat_name and isinstance(cat_name, str) and cat_name in base_scores:
                    base_scores[cat_name] += weight
            adjustment_scores = {cat: 0.0 for cat in self.ENTERPRISE_CATEGORIES}
            if not self.company_review_df.empty and '대상기업' in self.company_review_df.columns:
                year_to_filter = int(year_key)
                reviews_df = self.company_review_df[(self.company_review_df['대상기업'] == company_name) & (self.company_review_df['year'] == year_to_filter)]
                reviews_text = ' '.join(reviews_df['평가내용'].dropna().astype(str))
                if reviews_text.strip():
                    corpus_embedding = self.sbert_model.encode(reviews_text, convert_to_tensor=True)
                    for cat, cat_emb in self.enterprise_category_embeddings.items():
                        adjustment_scores[cat] += util.cos_sim(corpus_embedding, cat_emb).item() * 10
            final_scores = {cat: base_scores[cat] + adjustment_scores[cat] for cat in self.ENTERPRISE_CATEGORIES}
            total_score = sum(final_scores.values())
            if total_score > 0:
                yearly_distribution[year_key] = {cat: score / total_score for cat, score in final_scores.items()}
        return yearly_distribution

    def get_all_company_names(self):
        all_names = set()
        for profile in self.unified_profiles.values():
            all_names.update(profile.index.tolist())
        return sorted(list(all_names))

    def get_business_description(self, company_name):
        if '2025' in self.unified_profiles:
            profile_2025 = self.unified_profiles['2025']
            if company_name in profile_2025.index and '사업내용' in profile_2025.columns:
                description = profile_2025.loc[company_name, '사업내용']
                if pd.notna(description) and str(description).strip():
                    return str(description)
        for year, profile_df in self.unified_profiles.items():
            if company_name in profile_df.index and '사업내용' in profile_df.columns:
                description = profile_df.loc[company_name, '사업내용']
                if pd.notna(description) and str(description).strip():
                    return str(description)
        return "등록된 사업 내용이 없습니다."

    def get_reviews_for_display(self, company_name):
        if self.company_review_df.empty: return []
        reviews = self.company_review_df[self.company_review_df['대상기업'] == company_name].copy()
        if reviews.empty: return []
        all_companies = self.get_all_company_names()
        peer_map = {name: f"동료기업 {i + 1}" for i, name in enumerate(reviews[reviews['평가기관'].isin(all_companies)]['평가기관'].unique())}
        display_list = []
        for _, row in reviews.iterrows():
            source = peer_map.get(row.get('평가기관'), f"외부: {row.get('평가기관', '정보 없음')}")
            rating = pd.to_numeric(row.get('평점'), errors='coerce')
            display_list.append({'year': str(row.get('year', '미상')).replace('.0', ''), 'source': source, 'rating': f"{rating:.1f}" if pd.notna(rating) else "N/A", 'sentiment': self.judge_sentiment_by_rating(rating), 'review': row.get('평가내용', '')})
        return sorted(display_list, key=lambda x: (x['year'].isdigit() and int(x['year']), x['year']), reverse=True)

    def get_review_statistics(self, company_name):
        if self.company_review_df.empty: return [], []
        reviews = self.company_review_df[self.company_review_df['대상기업'] == company_name].copy()
        reviews['평점'] = pd.to_numeric(reviews['평점'], errors='coerce')
        all_companies = self.get_all_company_names()
        ext_reviews = reviews[~reviews['평가기관'].isin(all_companies)]
        peer_reviews = reviews[reviews['평가기관'].isin(all_companies)]
        def summarize(df, r_type):
            if df.empty: return []
            summary_lines = []
            if r_type == '외부':
                for evaluator, group in df.groupby('평가기관'):
                    pos, total = len(group[group['평점'] >= 4]), len(group)
                    ratio = (pos / total * 100) if total > 0 else 0
                    summary_lines.append(f"• '{evaluator}': {ratio:.0f}% 긍정 (평균 {group['평점'].mean():.1f}점)")
            else:
                pos, total = len(df[df['평점'] >= 4]), len(df)
                ratio = (pos / total * 100) if total > 0 else 0
                summary_lines.append(f"• 동료 기업 전체: {ratio:.0f}% 긍정 (평균 {df['평점'].mean():.1f}점)")
            return summary_lines
        return summarize(ext_reviews, '외부'), summarize(peer_reviews, '동료')

    def get_preference_summary(self, company_name):
        if self.preference_df.empty: return ["협업 선호도 데이터 없음"]
        prefs = self.preference_df[self.preference_df['평가기업명'] == company_name]
        if prefs.empty: return ["협업 선호도 평가 기록 없음"]
        summary = []
        for target, group in prefs.groupby('평가대상기관'):
            ratings = pd.to_numeric(group['평점'], errors='coerce').dropna()
            ratio = (len(ratings[ratings >= 4]) / len(ratings) * 100) if not ratings.empty else 0
            summary.append(f"• '{target}'과(와)의 협업 선호도: {ratio:.0f}% 긍정")
        return summary

    def get_keyword_summary_from_reviews(self, company_name, top_n=5):
        if self.company_review_df.empty: return "리뷰 데이터 없음"
        reviews = self.company_review_df[self.company_review_df['대상기업'] == company_name]
        text = ' '.join(reviews['평가내용'].dropna().astype(str))
        if not text.strip(): return "리뷰 내용 없음"
        words = [word for word in text.split() if len(word) >= 2]
        if not words: return "키워드 추출 불가"
        return "자주 언급된 키워드: " + ", ".join([f"{k}({c}회)" for k, c in Counter(words).most_common(top_n)])

    def judge_sentiment_by_rating(self, rating):
        if pd.isna(rating): return "N/A"
        try:
            return "😊 긍정" if float(rating) >= 4 else "😐 중립" if float(rating) >= 3 else "😠 부정"
        except (ValueError, TypeError):
            return "N/A"

    def search_companies_by_keyword(self, keyword, category=None, top_n=10):
        from sentence_transformers import util
        if not self.sbert_model: return []

        profile_df = self.unified_profiles.get('2025', pd.DataFrame()).reset_index()
        if profile_df.empty: return []

        profile_df['corpus'] = profile_df['사업내용'].fillna('') + ' ' + profile_df['키워드'].fillna('')

        keyword_embedding = self.sbert_model.encode(keyword, convert_to_tensor=True)
        corpus_embeddings = self.sbert_model.encode(profile_df['corpus'].tolist(), convert_to_tensor=True)

        # 1. AI 모델이 계산한 기본 유사도 점수
        base_scores = util.cos_sim(keyword_embedding, corpus_embeddings)[0].cpu().tolist()

        final_results = []
        for i, base_score in enumerate(base_scores):
            company_data = profile_df.iloc[i]
            final_score = base_score

            # 2. 사용자가 선택한 카테고리에 따라 가중치 부여
            if category and category != "전체":
                if '1순위 분류' in company_data and company_data['1순위 분류'] == category:
                    final_score += self.CATEGORY_WEIGHT_1ST
                elif '2순위 분류' in company_data and company_data['2순위 분류'] == category:
                    final_score += self.CATEGORY_WEIGHT_2ND

            final_results.append({
                "company": company_data['기업명'],
                "score": final_score
            })

        # 3. 최종 점수를 기준으로 정렬하여 반환
        return sorted(final_results, key=lambda x: x['score'], reverse=True)[:top_n]

    def get_tourist_spots_in_busan(self):
        all_spots, seen_titles = [], set()
        for ctype in ['12', '14', '28']:
            try:
                params = {'serviceKey': self.KOREA_TOUR_API_KEY, 'numOfRows': 500, 'MobileOS': 'ETC', 'MobileApp': 'AppTest', '_type': 'json', 'areaCode': 6, 'contentTypeId': ctype}
                res = requests.get(self.KOREA_TOUR_API_URL, params=params, timeout=10)
                items = res.json().get('response', {}).get('body', {}).get('items', {}).get('item', [])
                for item in items:
                    if item.get('title') and item['title'] not in seen_titles:
                        seen_titles.add(item['title'])
                        all_spots.append(item)
            except Exception:
                continue
        return all_spots

    def get_location_id_from_tripadvisor(self, spot_name):
        if not spot_name or not self.TRIPADVISOR_API_KEY: return None
        try:
            params = {'key': self.TRIPADVISOR_API_KEY, 'searchQuery': spot_name, 'language': 'ko'}
            res = requests.get(f"{self.TRIPADVISOR_API_URL}/location/search", params=params, headers={'accept': 'application/json'}, timeout=10)
            if res.ok and res.json().get('data'): return res.json()['data'][0].get('location_id')
        except requests.exceptions.RequestException:
            return None
        return None

    def get_google_place_id_via_serpapi(self, spot_name):
        try:
            params = {"engine": "google", "q": f"{spot_name}, 부산", "api_key": self.SERPAPI_API_KEY, "hl": "ko"}
            results = GoogleSearch(params).get_dict()
            if "knowledge_graph" in results and "place_id" in results.get("knowledge_graph", {}):
                return results["knowledge_graph"]["place_id"]
        except Exception:
            pass
        return None

    def get_google_reviews_via_serpapi(self, place_id, review_count=50):
        if not place_id: return []
        all_reviews = []
        params = {"engine": "google_maps_reviews", "place_id": place_id, "hl": "ko", "api_key": self.SERPAPI_API_KEY}
        search = GoogleSearch(params)
        while True:
            try:
                results = search.get_dict()
                if "error" in results or not (reviews := results.get("reviews")): break
                all_reviews.extend(reviews)
                if len(all_reviews) >= review_count or "next_page_token" not in results.get("serpapi_pagination", {}): break
                search.params_dict['next_page_token'] = results["serpapi_pagination"]["next_page_token"]
            except Exception:
                break
        return [{'source': 'Google', 'text': r.get('snippet', '')} for r in all_reviews[:review_count] if r.get('snippet')]

    def get_tripadvisor_reviews(self, location_id):
        if not location_id or not self.TRIPADVISOR_API_KEY: return []
        try:
            params = {'key': self.TRIPADVISOR_API_KEY, 'language': 'ko'}
            res = requests.get(f"{self.TRIPADVISOR_API_URL}/location/{location_id}/reviews", params=params, headers={'accept': 'application/json'}, timeout=10)
            if res.ok and res.json().get('data'):
                return [{'source': 'TripAdvisor', 'text': r.get('text', '')} for r in res.json()['data'] if r.get('text')]
        except requests.exceptions.RequestException:
            return []
        return []

    def classify_tourist_reviews(self, all_reviews):
        from sentence_transformers import util
        if not self.sbert_model or not self.tourist_category_embeddings: return []
        review_texts = [r.get('text', '') for r in all_reviews if r.get('text', '').strip()]
        if not review_texts: return []
        review_embeddings = self.sbert_model.encode(review_texts, convert_to_tensor=True)
        classified = []
        for i, review_data in enumerate(filter(lambda r: r.get('text', '').strip(), all_reviews)):
            scores = {cat: util.cos_sim(review_embeddings[i], emb).max().item() for cat, emb in self.tourist_category_embeddings.items()}
            best_cat = max(scores, key=scores.get) if scores and max(scores.values()) >= 0.4 else '기타'
            classified.append({'review': review_data['text'], 'source': review_data['source'], 'category': best_cat})
        return classified

    def recommend_companies_for_tourist_spot(self, category, top_n=5):
        return self.search_companies_by_keyword(category, top_n)


# ===================================================================
# 3. Frontend UI Pages
# ===================================================================
class AutocompleteEntry(tk.Frame):
    def __init__(self, parent, controller, **kwargs):
        self.on_select_callback = kwargs.pop('on_select_callback', None)
        self.completion_list = kwargs.pop('completion_list', [])
        super().__init__(parent)
        self.controller = controller
        self.var = tk.StringVar()
        self.entry = ttk.Entry(self, textvariable=self.var, **kwargs)
        self.entry.pack(side='left', expand=True, fill='x')
        ttk.Button(self, text="▼", width=3, command=self._toggle_list).pack(side='right')

        self.popup = tk.Toplevel(controller)
        self.popup.overrideredirect(True)
        self.popup.withdraw()
        self.listbox = tk.Listbox(self.popup, exportselection=False, highlightthickness=0)
        self.listbox.pack(expand=True, fill='both')

        self.var.trace_add('write', self._on_type)
        self.entry.bind("<FocusOut>", lambda e: self.after(150, self.popup.withdraw))
        self.entry.bind("<Down>", self._move_selection)
        self.entry.bind("<Up>", self._move_selection)
        self.entry.bind("<Return>", self._select_item)
        self.listbox.bind("<ButtonRelease-1>", self._select_item)

    def get(self): return self.var.get()
    def set(self, text): self.var.set(text)
    def set_completion_list(self, new_list): self.completion_list = new_list

    def _on_type(self, *args):
        typed = self.var.get().lower()
        if not typed: self.popup.withdraw(); return
        filtered = [item for item in self.completion_list if typed in item.lower()]
        self._update_popup(filtered)

    def _toggle_list(self):
        if self.popup.winfo_viewable():
            self.popup.withdraw()
        else:
            self._update_popup(self.completion_list)

    def _update_popup(self, items):
        if not items: self.popup.withdraw(); return
        self.listbox.delete(0, tk.END)
        for item in items: self.listbox.insert(tk.END, item)
        x, y, w = self.entry.winfo_rootx(), self.entry.winfo_rooty() + self.entry.winfo_height(), self.entry.winfo_width()
        h = self.listbox.size() * 24 if self.listbox.size() <= 10 else 240
        self.popup.geometry(f"{w}x{h}+{x}+{y}")
        self.popup.deiconify()
        self.listbox.selection_set(0)

    def _select_item(self, event=None):
        indices = self.listbox.curselection()
        if indices:
            self.var.set(self.listbox.get(indices[0]))
            self.popup.withdraw()
            if self.on_select_callback: self.on_select_callback()
        return "break"

    def _move_selection(self, event):
        indices = self.listbox.curselection()
        next_idx = (indices[0] + (1 if event.keysym == "Down" else -1)) if indices else -1
        if 0 <= next_idx < self.listbox.size():
            self.listbox.selection_clear(0, tk.END)
            self.listbox.selection_set(next_idx)
            self.listbox.see(next_idx)
        return "break"


class MainPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.main_content_frame = tk.Frame(self)
        tk.Label(self.main_content_frame, text="관광-기업 연계 분석 시스템", font=("Helvetica", 22, "bold")).pack(pady=50)
        tk.Button(self.main_content_frame, text="기업 분석", font=("Helvetica", 16), width=20, height=3, command=lambda: controller.show_frame("CompanySearchPage")).pack(pady=15)
        tk.Button(self.main_content_frame, text="관광지 분석", font=("Helvetica", 16), width=20, height=3, command=lambda: controller.show_frame("TouristSearchPage")).pack(pady=15)
        tk.Button(self.main_content_frame, text="키워드 검색", font=("Helvetica", 16), width=20, height=3, command=lambda: controller.show_frame("KeywordSearchPage")).pack(pady=15)

    def show_main_content(self):
        self.main_content_frame.pack(expand=True, fill='both')


class CompanySearchPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        top_frame = tk.Frame(self)
        top_frame.pack(pady=10, padx=20, fill='x')
        tk.Button(top_frame, text="< 시작", command=lambda: controller.show_frame("MainPage")).pack(side='left')
        self.result_back_button = tk.Button(top_frame, text="< 결과 페이지로", command=lambda: controller.show_frame("ResultPage"))
        tk.Label(top_frame, text="기업:", font=("Helvetica", 12)).pack(side='left', padx=(10, 5))
        self.company_entry = AutocompleteEntry(top_frame, controller, font=("Helvetica", 12), on_select_callback=self.start_analysis)
        self.company_entry.pack(side='left', expand=True, fill='x')
        ttk.Button(top_frame, text="새로고침", command=self.refresh_data).pack(side='left', padx=5)

        pane = ttk.PanedWindow(self, orient=tk.VERTICAL)
        pane.pack(expand=True, fill='both', padx=20, pady=5)

        graph_frame = ttk.LabelFrame(pane, text="연도별 카테고리 변화", padding=5)
        pane.add(graph_frame, weight=3)
        self.fig = plt.Figure(figsize=(5, 3), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=graph_frame)
        self.canvas.get_tk_widget().pack(fill='both', expand=True)

        middle_container = tk.Frame(pane)
        pane.add(middle_container, weight=2)

        desc_frame = ttk.LabelFrame(middle_container, text="주요 사업 내용", padding=5)
        desc_frame.pack(fill='both', expand=True, pady=(0, 5))
        desc_scroll = tk.Scrollbar(desc_frame)
        desc_scroll.pack(side='right', fill='y')
        self.desc_text = tk.Text(desc_frame, wrap='word', height=4, yscrollcommand=desc_scroll.set, state='disabled', relief='flat', bg=self.cget('bg'))
        self.desc_text.pack(fill='both', expand=True)
        desc_scroll.config(command=self.desc_text.yview)

        summary_pane = ttk.PanedWindow(middle_container, orient=tk.HORIZONTAL)
        summary_pane.pack(fill='both', expand=True)

        stats_frame = ttk.LabelFrame(summary_pane, text="통계 요약", padding=5)
        summary_pane.add(stats_frame, weight=1)
        stats_scroll = tk.Scrollbar(stats_frame)
        stats_scroll.pack(side='right', fill='y')
        self.stats_text = tk.Text(stats_frame, wrap='word', yscrollcommand=stats_scroll.set, state='disabled', relief='flat', bg=self.cget('bg'))
        self.stats_text.pack(fill='both', expand=True)
        stats_scroll.config(command=self.stats_text.yview)

        keyword_frame = ttk.LabelFrame(summary_pane, text="키워드/선호도", padding=5)
        summary_pane.add(keyword_frame, weight=1)
        keyword_scroll = tk.Scrollbar(keyword_frame)
        keyword_scroll.pack(side='right', fill='y')
        self.keyword_text = tk.Text(keyword_frame, wrap='word', yscrollcommand=keyword_scroll.set, state='disabled', relief='flat', bg=self.cget('bg'))
        self.keyword_text.pack(fill='both', expand=True)
        keyword_scroll.config(command=self.keyword_text.yview)

        review_frame = ttk.LabelFrame(pane, text="상세 리뷰", padding=5)
        pane.add(review_frame, weight=6)

        cols = ('year', 'source', 'rating', 'sentiment', 'review')
        self.tree = ttk.Treeview(review_frame, columns=cols, show='headings')
        for col, w in [('year', 50), ('source', 120), ('rating', 60), ('sentiment', 80), ('review', 300)]:
            self.tree.heading(col, text=col.capitalize())
            self.tree.column(col, width=w, stretch=(col == 'review'))
        scroll = ttk.Scrollbar(review_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')

    def toggle_back_button(self, show):
        if show: self.result_back_button.pack(side='left', padx=(5, 0))
        else: self.result_back_button.pack_forget()

    def refresh_data(self):
        self.controller.show_loading_popup_and_start_work()

    def update_company_list(self):
        self.company_entry.set_completion_list(self.controller.analyzer.get_all_company_names())

    def start_analysis(self, event=None):
        company = self.company_entry.get()
        if not company: return
        threading.Thread(target=self._analysis_thread, args=(company,), daemon=True).start()

    def _analysis_thread(self, company):
        try:
            analyzer = self.controller.analyzer
            graph_data = analyzer.get_yearly_category_distribution(company)
            description = analyzer.get_business_description(company)
            reviews = analyzer.get_reviews_for_display(company)
            ext_summary, peer_summary = analyzer.get_review_statistics(company)
            pref_summary = analyzer.get_preference_summary(company)
            keyword_summary = analyzer.get_keyword_summary_from_reviews(company)
            self.after(0, self._update_ui, company, graph_data, description, reviews, ext_summary, peer_summary, pref_summary, keyword_summary)
        except Exception as e:
            import traceback
            traceback.print_exc()
            messagebox.showerror("분석 오류", f"'{company}' 기업 정보 분석 중 오류가 발생했습니다.\n\n오류: {e}")

    def _update_text_widget(self, widget, content):
        widget.config(state='normal')
        widget.delete('1.0', 'end')
        widget.insert('1.0', content.strip())
        widget.config(state='disabled')

    def _update_ui(self, company, graph_data, description, reviews, ext_summary, peer_summary, pref_summary, keyword_summary):
        self._update_graph(company, graph_data)
        self._update_text_widget(self.desc_text, description)
        stats_content = "외부 평가:\n" + "\n".join(ext_summary) + "\n\n동료 평가:\n" + "\n".join(peer_summary)
        keyword_content = "협업 선호도:\n" + "\n".join(pref_summary) + f"\n\n{keyword_summary}"
        self._update_text_widget(self.stats_text, stats_content)
        self._update_text_widget(self.keyword_text, keyword_content)
        self.tree.delete(*self.tree.get_children())
        for r in reviews: self.tree.insert('', 'end', values=[r.get(c, '') for c in self.tree['columns']])

    def _update_graph(self, company_name, yearly_data):
        self.ax.clear()
        if not yearly_data:
            self.ax.text(0.5, 0.5, "표시할 연도별 데이터가 없습니다.", ha='center', va='center')
        else:
            df = pd.DataFrame(yearly_data).T.fillna(0)
            top_categories = df.sum().nlargest(4).index.tolist()
            other_cols = [c for c in df.columns if c not in top_categories]
            if other_cols:
                df['기타'] = df[other_cols].sum(axis=1)
                df = df[top_categories + ['기타']]
            df = df.loc[(df != 0).any(axis=1)]
            df.plot(kind='barh', stacked=True, ax=self.ax, colormap='viridis', width=0.8)
            self.ax.set_title(f"'{company_name}' 연도별 주요 활동", fontsize=10)
            self.ax.set_xlabel("비중 (%)")
            self.ax.set_ylabel("연도")
            self.ax.legend(title='Category', bbox_to_anchor=(1.02, 1), loc='upper left', fontsize='small')
            self.ax.invert_yaxis()
            for container in self.ax.containers:
                for bar in container:
                    width = bar.get_width()
                    if width > 0.03:
                        x, y = bar.get_x() + width / 2, bar.get_y() + bar.get_height() / 2
                        self.ax.text(x, y, f'{width:.0%}'.replace('%', ''), ha='center', va='center', color='white', fontsize=8, weight='bold')
        self.fig.tight_layout(rect=[0, 0, 0.85, 1])
        self.canvas.draw()


class KeywordSearchPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        top_frame = tk.Frame(self)
        top_frame.pack(pady=10, padx=20, fill='x')

        tk.Button(top_frame, text="< 시작", command=lambda: controller.show_frame("MainPage")).pack(side='left')

        tk.Label(top_frame, text="키워드:", font=("Helvetica", 12)).pack(side='left', padx=(15, 5))
        self.entry = ttk.Entry(top_frame, font=("Helvetica", 12))
        self.entry.pack(side='left', expand=True, fill='x')
        self.entry.bind("<Return>", lambda e: self.start_search())

        # [UI 추가] 카테고리 선택 드롭다운 메뉴
        tk.Label(top_frame, text="카테고리:", font=("Helvetica", 12)).pack(side='left', padx=(10, 5))
        self.category_var = tk.StringVar()
        self.category_combo = ttk.Combobox(top_frame, textvariable=self.category_var, state="readonly", width=15,
                                           font=("Helvetica", 11))
        self.category_combo.pack(side='left', padx=(0, 10))

        ttk.Button(top_frame, text="검색", command=self.start_search).pack(side='left')

        cols = ("company", "score")
        self.tree = ttk.Treeview(self, columns=cols, show="headings")
        self.tree.heading("company", text="기업명")
        # [수정 1] 결과 테이블의 헤더를 '유사도'에서 '점수'로 변경
        self.tree.heading("score", text="점수")
        self.tree.column("score", width=100, anchor='center')
        self.tree.pack(expand=True, fill='both', padx=20, pady=10)
        self.tree.bind("<Double-1>", self.go_to_details)

    # [기능 추가] 외부(컨트롤러)에서 카테고리 목록을 받아 드롭다운을 채우는 함수
    def update_category_list(self, categories):
        """컨트롤러가 카테고리 목록을 전달하면 드롭다운 메뉴를 채웁니다."""
        self.category_combo['values'] = ["전체"] + categories
        self.category_var.set("전체")  # 기본값으로 '전체'를 선택

    # [기능 수정] 검색 시 선택된 카테고리 값을 가져오도록 수정
    def start_search(self):
        keyword = self.entry.get().strip()
        category = self.category_var.get()  # 선택된 카테고리 값 가져오기
        if not keyword: return
        # 검색 스레드에 카테고리 값 전달
        threading.Thread(target=self._search_thread, args=(keyword, category), daemon=True).start()

    # [기능 수정] 분석 함수 호출 시 카테고리 값을 함께 전달
    def _search_thread(self, keyword, category):
        self.after(0, lambda: self.tree.delete(*self.tree.get_children()))
        results = self.controller.analyzer.search_companies_by_keyword(keyword, category=category)
        self.after(0, self._update_results, results)

    # [수정 2] 점수 표시 형식을 '0.678' -> '67.8점'으로 변경
    def _update_results(self, results):
        for res in results:
            score_val = res.get('score', 0.0)
            score_text = f"{(score_val * 100):.1f}점"
            self.tree.insert("", "end", values=(res['company'], score_text))

    def go_to_details(self, event):
        if item := self.tree.focus():
            self.controller.navigate_to_company_page(self.tree.item(item, 'values')[0])


class TouristSearchPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        tk.Button(self, text="< 시작", command=lambda: controller.show_frame("MainPage")).pack(anchor='nw', padx=10, pady=10)
        tk.Label(self, text="분석할 관광지 이름을 입력하세요.", font=("Helvetica", 14)).pack(pady=10)
        input_frame = tk.Frame(self)
        input_frame.pack(pady=5, padx=20, fill='x')
        self.spot_entry = AutocompleteEntry(input_frame, controller, font=("Helvetica", 12))
        self.spot_entry.pack(expand=True, fill='x')
        ctrl_frame = tk.Frame(self)
        ctrl_frame.pack(pady=10)
        tk.Label(ctrl_frame, text="Google 리뷰 수:", font=("Helvetica", 11)).pack(side='left')
        self.review_count_var = tk.StringVar(value='50')
        ttk.Combobox(ctrl_frame, textvariable=self.review_count_var, values=[10, 20, 50, 100], width=5, state="readonly").pack(side='left', padx=5)
        self.analyze_button = tk.Button(ctrl_frame, text="분석 시작", font=("Helvetica", 14, "bold"), command=self.start_analysis)
        self.analyze_button.pack(side='left', padx=10)
        status_frame = tk.Frame(self)
        status_frame.pack(fill='x', padx=20, pady=(5, 10), side='bottom')
        self.status_label = tk.Label(status_frame, text="대기 중", font=("Helvetica", 10))
        self.status_label.pack()
        self.progress_bar = ttk.Progressbar(status_frame, orient='horizontal', mode='determinate')

    def update_autocomplete_list(self, spot_list):
        self.spot_entry.set_completion_list(sorted([spot['title'] for spot in spot_list if 'title' in spot]))

    def start_analysis(self):
        spot = self.spot_entry.get()
        if not spot: messagebox.showwarning("입력 오류", "분석할 관광지 이름을 입력해주세요."); return
        self.controller.start_full_analysis(spot, int(self.review_count_var.get()))

    def analysis_start_ui(self, spot_name):
        self.status_label.config(text=f"'{spot_name}' 분석을 시작합니다...")
        self.progress_bar.pack(fill='x', pady=5)
        self.analyze_button.config(state='disabled')

    def update_progress_ui(self, value, message):
        self.progress_bar['value'] = value
        self.status_label.config(text=message)

    def analysis_complete_ui(self):
        self.progress_bar.pack_forget()
        self.analyze_button.config(state='normal')
        self.status_label.config(text="분석 완료! 결과 페이지로 이동합니다.")
        self.spot_entry.set("")

    def analysis_fail_ui(self, error_message):
        messagebox.showerror("분석 오류", error_message)
        self.progress_bar.pack_forget()
        self.analyze_button.config(state='normal')
        self.status_label.config(text="분석 실패")


class ResultPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        header_frame = tk.Frame(self)
        header_frame.pack(fill='x', pady=10, padx=10)
        tk.Button(header_frame, text="< 관광지 검색으로", command=lambda: controller.show_frame("TouristSearchPage")).pack(side='left')
        self.title_label = tk.Label(header_frame, text="", font=("Helvetica", 18, "bold"))
        self.title_label.pack(side='left', padx=20)
        tk.Button(header_frame, text="리뷰 텍스트로 내보내기 💾", command=self.export_reviews_to_txt).pack(side='right')

        canvas = tk.Canvas(self)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.scrollable_frame = ttk.Frame(canvas)
        self.scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True, padx=10)
        scrollbar.pack(side="right", fill="y")

    def export_reviews_to_txt(self):
        result = self.controller.analysis_result
        if not result or 'classified_reviews' not in result:
            messagebox.showwarning("내보내기 오류", "내보낼 분석 결과가 없습니다.")
            return
        spot_name = result.get('spot_name', 'untitled_reviews')
        safe_name = "".join(c for c in spot_name if c.isalnum() or c in ' _-').rstrip()
        filepath = filedialog.asksaveasfilename(defaultextension=".txt", initialfile=f"{safe_name}_리뷰.txt", title="리뷰 저장")
        if not filepath: return
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(f"--- '{spot_name}' 관광지 리뷰 데이터 ---\n\n")
                for review_data in result['classified_reviews']:
                    text = review_data.get('review', '').strip().replace('\n', ' ')
                    if text: f.write(f"{text}\n")
            messagebox.showinfo("저장 완료", f"리뷰를 성공적으로 저장했습니다.")
        except Exception as e:
            messagebox.showerror("파일 저장 오류", f"파일을 저장하는 중 오류가 발생했습니다:\n{e}")

    def update_results(self):
        for widget in self.scrollable_frame.winfo_children(): widget.destroy()
        result = self.controller.analysis_result
        if not result: return
        self.title_label.config(text=f"'{result.get('spot_name', '')}' 분석 결과")
        if result.get('recommended_companies'):
            frame = ttk.LabelFrame(self.scrollable_frame, text=f"'{result.get('best_category')}' 연관 기업 추천", padding=10)
            frame.pack(fill='x', padx=10, pady=10)
            for item in result['recommended_companies']:
                name = item['company']
                link = tk.Label(frame, text=f"• {name} (유사도: {item['score']:.1%})", font=("Helvetica", 12, "underline"), fg="blue", cursor="hand2")
                link.pack(anchor='w', pady=2)
                link.bind("<Button-1>", lambda e, n=name: self.controller.navigate_to_company_page(n, from_result_page=True))
        cat_frame = ttk.LabelFrame(self.scrollable_frame, text="리뷰 카테고리 분류 결과", padding=10)
        cat_frame.pack(fill='x', padx=10, pady=10)
        for cat, count in Counter(r['category'] for r in result.get('classified_reviews', [])).most_common():
            f = tk.Frame(cat_frame)
            f.pack(fill='x', pady=5)
            tk.Label(f, text=f"● {cat}: {count}개", font=("Helvetica", 14)).pack(side='left')
            tk.Button(f, text="상세 보기", command=lambda c=cat: self.controller.navigate_to_details_page(c)).pack(side='right')


class DetailPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        header_frame = tk.Frame(self)
        header_frame.pack(fill='x', pady=10, padx=10)
        tk.Button(header_frame, text="< 분석 결과로", command=lambda: controller.show_frame("ResultPage")).pack(side='left')
        self.title_label = tk.Label(header_frame, text="", font=("Helvetica", 16, "bold"))
        self.title_label.pack(side='left', padx=20)
        text_frame = tk.Frame(self)
        text_frame.pack(pady=10, padx=20, fill='both', expand=True)
        self.text_area = tk.Text(text_frame, wrap='word', font=("Helvetica", 12))
        scrollbar = tk.Scrollbar(text_frame, command=self.text_area.yview)
        self.text_area.config(yscrollcommand=scrollbar.set, state='disabled')
        scrollbar.pack(side='right', fill='y')
        self.text_area.pack(side='left', fill='both', expand=True)
        self.text_area.tag_config("source_tag", foreground="gray", font=("Helvetica", 10))

    def update_details(self, category):
        result = self.controller.analysis_result
        self.title_label.config(text=f"[{category}] 상세 리뷰 목록")
        self.text_area.config(state='normal')
        self.text_area.delete(1.0, 'end')
        filtered_reviews = [r for r in result.get('classified_reviews', []) if r.get('category') == category]
        if not filtered_reviews:
            self.text_area.insert('end', "표시할 리뷰가 없습니다.")
        else:
            for i, r in enumerate(filtered_reviews, 1):
                self.text_area.insert('end', f"--- 리뷰 {i} (출처: {r.get('source', 'N/A')}) ---\n", "source_tag")
                self.text_area.insert('end', f"{r.get('review', '').strip()}\n\n")
        self.text_area.config(state='disabled')


# ===================================================================
# 4. Main Application Controller
# ===================================================================
class TouristApp(tk.Tk):
    def __init__(self, api_keys, paths):
        super().__init__()
        self.withdraw()
        self.title("관광-기업 연계 분석기")
        self.geometry("1200x900")
        self.analyzer = ReviewAnalyzer(api_keys, paths)
        self.analysis_result = {}
        container = tk.Frame(self)
        container.pack(fill="both", expand=True)
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)
        self.frames = {F.__name__: F(container, self) for F in (MainPage, CompanySearchPage, TouristSearchPage, KeywordSearchPage, ResultPage, DetailPage)}
        for frame in self.frames.values():
            frame.grid(row=0, column=0, sticky="nsew")
        self.show_frame("MainPage")
        self.after(100, self.show_loading_popup_and_start_work)

    def show_frame(self, page_name):
        frame = self.frames[page_name]
        frame.tkraise()
        if page_name == "ResultPage":
            frame.update_results()

    def show_loading_popup_and_start_work(self):
        self.create_loading_popup()
        threading.Thread(target=self._load_resources_thread, daemon=True).start()

    def create_loading_popup(self):
        self.loading_popup = tk.Toplevel(self)
        self.loading_popup.title("로딩 중")
        self.loading_popup.resizable(False, False)
        self.loading_popup.protocol("WM_DELETE_WINDOW", lambda: None)
        self.loading_popup.transient(self)
        self.loading_popup.grab_set()
        w, h = 400, 150
        x, y = (self.winfo_screenwidth() // 2) - (w // 2), (self.winfo_screenheight() // 2) - (h // 2)
        self.loading_popup.geometry(f'{w}x{h}+{x}+{y}')
        tk.Label(self.loading_popup, text="프로그램을 준비하고 있습니다...", font=("Helvetica", 14, "bold")).pack(pady=20)
        self.loading_status_label = tk.Label(self.loading_popup, text="초기화 중...", font=("Helvetica", 10))
        self.loading_status_label.pack(pady=5)
        self.loading_progress = ttk.Progressbar(self.loading_popup, length=300, mode='determinate')
        self.loading_progress.pack(pady=10)
        self.loading_popup.update_idletasks()

    def _load_resources_thread(self):
        def update_status(value, message):
            self.loading_progress['value'] = value
            self.loading_status_label.config(text=message)

        try:
            self.after(0, update_status, 20, "AI 분석 모델 로딩 중...")
            self.analyzer._load_sbert_model()
            self.after(0, update_status, 50, "Google Sheets 데이터 로딩 및 통합 중...")
            self.analyzer.load_and_unify_data_sources()
            self.after(0, update_status, 80, "자동완성용 관광지 목록 로딩 중...")
            spots = self.analyzer.get_tourist_spots_in_busan()

            # [수정] 로딩 완료 함수 호출 시, 기업 카테고리 목록을 함께 전달합니다.
            self.after(0, self._on_load_complete, spots, self.analyzer.ENTERPRISE_CATEGORIES)

            self.after(0, update_status, 100, "준비 완료!")
            self.after(500, self.close_loading_popup_and_show_main)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.after(0, self.show_error_and_exit, f"초기화 오류 발생:\n\n{e}")

    def _on_load_complete(self, spots, enterprise_categories):
        # [수정] enterprise_categories 인자를 받도록 변경합니다.

        # 기존 UI 업데이트
        self.frames["CompanySearchPage"].update_company_list()
        self.frames["TouristSearchPage"].update_autocomplete_list(spots)

        # [추가] KeywordSearchPage의 드롭다운 목록을 채우도록 함수를 호출합니다.
        self.frames["KeywordSearchPage"].update_category_list(enterprise_categories)

        self.frames["MainPage"].show_main_content()

    def close_loading_popup_and_show_main(self):
        if hasattr(self, 'loading_popup') and self.loading_popup.winfo_exists():
            self.loading_popup.grab_release()
            self.loading_popup.destroy()
        self.deiconify()
        self.lift()
        self.focus_force()

    def show_error_and_exit(self, message):
        if hasattr(self, 'loading_popup') and self.loading_popup.winfo_exists():
            self.loading_popup.destroy()
        self.deiconify()
        messagebox.showerror("심각한 오류", message)
        self.destroy()

    def navigate_to_company_page(self, company_name, from_result_page=False):
        page = self.frames["CompanySearchPage"]
        page.toggle_back_button(show=from_result_page)
        self.show_frame("CompanySearchPage")
        page.company_entry.set(company_name)
        page.start_analysis()

    def navigate_to_details_page(self, category):
        page = self.frames["DetailPage"]
        page.update_details(category)
        self.show_frame("DetailPage")

    def start_full_analysis(self, spot_name, review_count):
        threading.Thread(target=self._analysis_thread, args=(spot_name, review_count), daemon=True).start()

    def _analysis_thread(self, spot_name, review_count):
        page = self.frames["TouristSearchPage"]
        try:
            self.after(0, page.analysis_start_ui, spot_name)
            steps = 0
            def update(msg):
                nonlocal steps
                steps += 1
                self.after(0, page.update_progress_ui, (steps / 4) * 100, msg)

            update("ID 탐색 중...")
            trip_id = self.analyzer.get_location_id_from_tripadvisor(spot_name)
            google_id = self.analyzer.get_google_place_id_via_serpapi(spot_name)
            update("리뷰 수집 중...")
            all_reviews = self.analyzer.get_tripadvisor_reviews(trip_id) + self.analyzer.get_google_reviews_via_serpapi(google_id, review_count)
            if not all_reviews: raise ValueError(f"'{spot_name}'에 대한 리뷰를 찾을 수 없음")
            update("AI 모델로 리뷰 분류 중...")
            classified = self.analyzer.classify_tourist_reviews(all_reviews)
            if not classified: raise ValueError("리뷰 카테고리 분류 실패")
            update("결과 처리 및 기업 추천 중...")

            category_counts = Counter(r['category'] for r in classified if r['category'] != '기타')
            best_cat = category_counts.most_common(1)[0][0] if category_counts else "기타"
            self.analysis_result = {'spot_name': spot_name, 'best_category': best_cat, 'classified_reviews': classified, 'recommended_companies': self.analyzer.recommend_companies_for_tourist_spot(best_cat)}
            self.after(0, page.analysis_complete_ui)
            self.after(200, lambda: self.show_frame("ResultPage"))
        except Exception as e:
            self.after(0, page.analysis_fail_ui, str(e))


# ===================================================================
# 5. Program Entry Point
# ===================================================================
if __name__ == "__main__":
    try:
        config = configparser.ConfigParser()
        config.read(resource_path('config.ini'), encoding='utf-8')
        api_keys = dict(config.items('API_KEYS'))
        paths = dict(config.items('PATHS'))
    except Exception as e:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("설정 오류", f"config.ini 파일 로드 실패: {e}")
        sys.exit()

    app = TouristApp(api_keys, paths)
    app.mainloop()

