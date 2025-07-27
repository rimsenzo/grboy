# ===================================================================
# 1. Imports and Global Setup (requests 누락 수정)
# ===================================================================

# --- 1. Python Standard Libraries ---
import sys
import os
import configparser
import threading
import warnings
import json
import time
import io
import csv
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
    import matplotlib.ticker

    # ▼▼▼▼▼ [수정된 부분] ▼▼▼▼▼
    # API 호출에 필수적인 requests 라이브러리를 추가합니다.
    import requests

    # ▲▲▲▲▲ [수정된 부분 끝] ▲▲▲▲▲

    matplotlib.use('TkAgg')

except ImportError as e:
    error_message = f"CRITICAL ERROR: A required library is missing: '{e.name}'.\nPlease install it by running: pip install {e.name}"
    print(error_message)
    sys.exit(1)


# --- 4. Global Configurations & Utility Functions ---

def setup_fonts():
    """OS 환경에 맞춰 Matplotlib의 기본 한글 폰트를 설정합니다."""
    # (이하 함수 내용은 기존과 동일)
    if sys.platform == "win32":
        font_family = "Malgun Gothic"
    elif sys.platform == "darwin":
        font_family = "AppleGothic"
    else:
        font_family = "NanumGothic"
    try:
        matplotlib.rcParams['font.family'] = font_family
        matplotlib.rcParams['axes.unicode_minus'] = False
        print(f"--- Font set to '{font_family}' for this OS. ---")
    except Exception as font_error:
        print(f"--- Font Warning: Could not set font '{font_family}'. Error: {font_error} ---")
        print("--- Charts may display broken characters. Please install a Korean font. ---")


def setup_warnings():
    """프로그램 실행에 불필요한 경고 메시지를 숨겨 콘솔을 깨끗하게 유지합니다."""
    # (이하 함수 내용은 기존과 동일)
    warnings.filterwarnings("ignore", category=UserWarning, message=".*pkg_resources is deprecated.*")
    warnings.filterwarnings('ignore', message='Unverified HTTPS request')
    warnings.filterwarnings('ignore', category=matplotlib.MatplotlibDeprecationWarning)


def resource_path(relative_path):
    """ 개발 환경과 PyInstaller 배포 환경 모두에서 리소스 파일 경로를 올바르게 찾습니다. """
    # (이하 함수 내용은 기존과 동일)
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


# --- 5. Initial Setup Execution ---
setup_fonts()
setup_warnings()


# ===================================================================
# 2. Backend Logic: ReviewAnalyzer Class (재구성 및 최종본)
# ===================================================================
class ReviewAnalyzer:
    """ API 호출, 데이터 가공, AI 분석 등 핵심 비즈니스 로직을 담당합니다. """

    # --- 클래스 변수 (상수) ---
    TOURIST_SPOT_CATEGORIES = {
        'K-문화': ['K팝', 'K드라마', '영화 촬영지', '한류', '부산국제영화제', 'BIFF', '아이돌', '팬미팅', 'SNS', '인스타그램', '핫플레이스', '슬램덩크'],
        '해양': ['바다', '해변', '해수욕장', '해안', '항구', '섬', '등대', '요트', '해상케이블카', '스카이캡슐', '해변열차', '파도', '수족관', '서핑', '스카이워크'],
        '웰니스': ['힐링', '휴식', '스파', '사우나', '온천', '족욕', '마사지', '산책', '자연', '평화', '평온', '치유', '고요함', '명상', '건강'],
        '뷰티': ['미용', '헤어', '피부', '메이크업', '네일', '에스테틱', '피부관리', '뷰티서비스', '마사지', '미용실', '헤어샵', '네일샵', '살롱', '화장품', 'K-뷰티',
               '퍼스널컬러', '스타일링', '시술', '페이셜'],
        'e스포츠': ['e스포츠', '게임', 'PC방', '대회', '경기장', '프로게이머', '리그오브레전드', 'LCK', '스타크래프트', '페이커', '이스포츠'],
        '미식': ['맛집', '음식', '레스토랑', '카페', '해산물', '시장', '회', '조개구이', '돼지국밥', '디저트', '식도락']
    }
    ENTERPRISE_CATEGORIES = [
        "관광인프라", "MICE", "해양·레저", "여행서비스업", "테마·콘텐츠관광", "관광플랫폼",
        "지역특화콘텐츠", "관광딥테크", "관광기념품·캐릭터", "미디어마케팅"
    ]
    SEED_BONUS_MULTIPLIERS = {1: 1.5, 2: 1.2, 3: 1.1}

    def __init__(self, api_keys, paths):
        # --- 인스턴스 변수 초기화 ---
        self.KOREA_TOUR_API_KEY = api_keys.get('korea_tour_api_key')
        self.TRIPADVISOR_API_KEY = api_keys.get('tripadvisor_api_key')
        self.SERPAPI_API_KEY = api_keys.get('serpapi_api_key')
        self.KOREA_TOUR_API_URL = "http://apis.data.go.kr/B551011/KorService2/areaBasedList2"
        self.TRIPADVISOR_API_URL = "https://api.content.tripadvisor.com/api/v1"
        self.paths = paths

        # 데이터프레임 및 AI 모델 변수 선언
        self.unified_profiles = {}
        self.company_review_df = pd.DataFrame()
        self.company_df_for_recommendation = pd.DataFrame()
        self.sbert_model = None
        self.tourist_category_embeddings = None
        self.enterprise_category_embeddings = None

    def _load_sbert_model(self):
        """SBERT 모델과 카테고리 임베딩을 로드합니다."""
        try:
            from sentence_transformers import SentenceTransformer
            import torch

            print("--- AI SBERT 모델 로딩 시작 ---")
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
            print(f"--- 실행 장치(Device)가 '{device}'로 설정되었습니다. ---")

            model_name = 'jhgan/ko-sroberta-multitask'
            self.sbert_model = SentenceTransformer(model_name, device=device)

            print("--- 카테고리 임베딩 생성 시작 ---")
            self.enterprise_category_embeddings = {
                cat: self.sbert_model.encode(cat, convert_to_tensor=True) for cat in self.ENTERPRISE_CATEGORIES
            }
            print("--- AI SBERT 모델 및 모든 카테고리 임베딩 로딩 완료 ---")

        except ImportError:
            messagebox.showerror("라이브러리 오류", "AI 모델 로딩에 필요한 'sentence-transformers' 또는 'torch' 라이브러리가 없습니다.")
            self.sbert_model = None
        except Exception as e:
            messagebox.showerror("모델 로딩 오류", f"AI 모델 로딩 중 오류가 발생했습니다: {e}")
            self.sbert_model = None

    def load_all_resources(self):
        """애플리케이션 시작에 필요한 모든 리소스를 순서대로 로드하는 총괄 함수입니다."""
        print("\n--- 모든 리소스 로딩을 시작합니다. ---")
        self._load_sbert_model()
        self.load_and_unify_data_sources()
        print("--- 모든 리소스 로딩 완료. ---")

    def load_and_unify_data_sources(self):
        """
        [최종 수정본] '기업목록_데이터'와 '기업목록' 시트를 우선순위에 따라 병합하고,
        '기업명'을 인덱스로 설정하여 연도별 프로필을 생성하는 최종 버전입니다.
        """
        MAX_RETRIES = 3
        RETRY_DELAY = 5

        # ... (safe_get_dataframe_legacy 함수는 기존과 동일하게 유지) ...
        def safe_get_dataframe_legacy(worksheet):
            try:
                values = worksheet.get_all_values()
                if not values: return pd.DataFrame()
                output = io.StringIO()
                writer = csv.writer(output)
                writer.writerows(values)
                csv_string = output.getvalue()
                input_csv = io.StringIO(csv_string)
                df = pd.read_csv(input_csv, header='infer', skip_blank_lines=True)
                df = df.loc[:, ~df.columns.str.contains('^Unnamed')]
                df.dropna(how='all', inplace=True)
                return df
            except Exception as e:
                if "No columns to parse from file" in str(e): return pd.DataFrame()
                print(f"  - 경고 (Legacy): '{worksheet.title}' 시트 처리 중 오류: {e}")
                return pd.DataFrame()

        for attempt in range(MAX_RETRIES):
            try:
                # ... (Google Sheets 인증 및 접속 로직은 기존과 동일) ...
                print("--- [진단] 스레드 내에서 Google Sheets 인증 및 접속을 시도합니다... ---")
                scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
                key_path = resource_path(self.paths['google_sheet_key_path'])
                creds = ServiceAccountCredentials.from_json_keyfile_name(key_path, scope)
                thread_local_gs = gspread.authorize(creds)
                spreadsheet_id = self.paths.get('spreadsheet_id')
                if not spreadsheet_id:
                    print("!!! 치명적 오류: config.ini 파일에 'spreadsheet_id'가 없습니다.");
                    return
                spreadsheet = thread_local_gs.open_by_key(spreadsheet_id)
                all_worksheets = spreadsheet.worksheets()
                all_sheet_names = [ws.title for ws in all_worksheets]
                print(f"--- 접근 성공! '{spreadsheet.title}' 시트 목록: {all_sheet_names} ---")

                # 1. 리뷰 데이터 로딩
                review_sheet_name = "기업리뷰_데이터"
                if review_sheet_name in all_sheet_names:
                    worksheet = spreadsheet.worksheet(review_sheet_name)
                    self.company_review_df = safe_get_dataframe_legacy(worksheet)
                    print(f"--- '{review_sheet_name}' 로딩 시도: {len(self.company_review_df)}개 리뷰 로드 ---")

                    # 타임스탬프 후처리
                    if not self.company_review_df.empty and '타임스탬프' in self.company_review_df.columns:
                        timestamps_series = self.company_review_df['타임스탬프'].astype(str).str.replace('오전', 'AM',
                                                                                                    regex=False).str.replace(
                            '오후', 'PM', regex=False)
                        timestamps = pd.to_datetime(timestamps_series, errors='coerce')
                        self.company_review_df['year'] = timestamps.dt.year
                        self.company_review_df.dropna(subset=['year'], inplace=True)
                        if not self.company_review_df.empty:
                            self.company_review_df['year'] = self.company_review_df['year'].astype(int)
                else:
                    self.company_review_df = pd.DataFrame()

                print(f"--- '{review_sheet_name}' 후처리 완료: {len(self.company_review_df)}개 리뷰 ---")

                # 2. 기업 데이터 로딩 및 통합
                print("--- 기업 데이터 통합 시작 ('기업목록_데이터' 우선) ---")
                new_data_sheet = safe_get_dataframe_legacy(spreadsheet.worksheet("기업목록_데이터"))
                base_data_sheet = safe_get_dataframe_legacy(spreadsheet.worksheet("기업목록"))



                # '기업ID'를 문자열로 통일하여 병합 오류 방지
                for df in [new_data_sheet, base_data_sheet]:
                    if '기업ID' in df.columns:
                        df['기업ID'] = df['기업ID'].astype(str)

                # 두 데이터를 기업ID 기준으로 외부 조인(outer join)
                if not new_data_sheet.empty and not base_data_sheet.empty:
                    merged_df = pd.merge(base_data_sheet, new_data_sheet, on="기업ID", how="outer",
                                         suffixes=('_base', '_new'))

                    # '기업목록_데이터'의 값을 우선적으로 사용하여 열 정리
                    for col in ['기업명', '1순위 분류', '2순위 분류', '3순위 분류', '키워드']:
                        new_col, base_col = f"{col}_new", f"{col}_base"
                        if new_col in merged_df:
                            # _new 열이 존재하면, _base 열의 NaN 값을 _new 열 값으로 채움
                            merged_df[col] = merged_df[new_col].combine_first(merged_df.get(base_col))
                        elif base_col in merged_df:
                            merged_df[col] = merged_df[base_col]

                    # 고유 열들 정리
                    if '사업내용' in merged_df.columns and '사업내용_base' in merged_df.columns:
                        merged_df['사업내용'] = merged_df['사업내용_base']

                    # 불필요한 _new, _base 접미사 열 삭제
                    cols_to_drop = [c for c in merged_df.columns if c.endswith('_new') or c.endswith('_base')]
                    merged_df.drop(columns=cols_to_drop, inplace=True)
                    final_company_data = merged_df

                elif not new_data_sheet.empty:
                    final_company_data = new_data_sheet
                else:
                    final_company_data = base_data_sheet

                # 3. 연도별 프로필 생성
                self.unified_profiles = {}
                if '타임스탬프' in final_company_data.columns:
                    final_company_data['year'] = pd.to_datetime(final_company_data['타임스탬프'], errors='coerce').dt.year

                    for year, group in final_company_data.groupby('year'):
                        year_key = str(int(year))
                        profile = group.copy()
                        if '기업명' in profile.columns:
                            profile.drop_duplicates(subset=['기업명'], keep='first', inplace=True)
                            profile.set_index('기업명', inplace=True)
                            self.unified_profiles[year_key] = profile
                            print(f"  - {year_key}년도 프로필 생성 완료: {len(profile)}개 기업")

                # 연도 정보가 없는 나머지 데이터를 'base' 프로필로 생성
                base_profiles = final_company_data[
                    final_company_data['year'].isna()] if 'year' in final_company_data.columns else final_company_data
                if not base_profiles.empty and '기업명' in base_profiles.columns:
                    base_profiles.drop_duplicates(subset=['기업명'], keep='first', inplace=True)
                    base_profiles.set_index('기업명', inplace=True)
                    self.unified_profiles['base'] = base_profiles
                    print(f"  - 'base' 프로필 생성 완료: {len(base_profiles)}개 기업")



                    # ▼▼▼ [신규 추가] 선호분야 데이터 로딩 ▼▼▼
                preference_sheet_name = "선호분야"
                if preference_sheet_name in all_sheet_names:
                    worksheet = spreadsheet.worksheet(preference_sheet_name)
                    self.preference_df = safe_get_dataframe_legacy(worksheet)
                    print(f"--- '{preference_sheet_name}' 로딩 완료: {len(self.preference_df)}개 데이터 ---")
                else:
                    self.preference_df = pd.DataFrame()
                    print(f"--- 경고: '{preference_sheet_name}' 시트를 찾을 수 없습니다. ---")
                    # ▲▲▲ [추가 완료] ▲▲▲


                print("--- 모든 Google Sheets 데이터 로딩 및 통합 완료. ---")
                return

            except Exception as e:
                # ... (예외 처리 로직은 기존과 동일) ...
                print(f"  - 예상치 못한 오류 발생 (시도 {attempt + 1}/{MAX_RETRIES}): {e}")

    def get_reviews_for_company(self, company_name):
        """
        [최종 강화본] 리뷰 출처를 '외부기관'과 고유하게 익명화된 '동료기업'으로
        완벽하게 구분하고 상세 정보를 포함하여 반환합니다.
        """
        if self.company_review_df.empty or '대상기업' not in self.company_review_df.columns:
            print("--- get_reviews_for_company: 리뷰 데이터가 없거나 '대상기업' 컬럼이 없습니다. ---")
            return []

        target_reviews = self.company_review_df[self.company_review_df['대상기업'] == company_name].copy()
        if target_reviews.empty:
            print(f"--- get_reviews_for_company: '{company_name}'에 대한 리뷰가 없습니다. ---")
            return []

        # 전체 기업 목록을 한 번만 생성하여 효율적으로 사용합니다.
        all_enterprise_names = set()
        for profile in self.unified_profiles.values():
            all_enterprise_names.update(profile.index.tolist())

        display_reviews = []

        # ▼▼▼▼▼ [핵심 수정: 동료기업 익명화 로직 추가] ▼▼▼▼▼
        peer_anonymizer = {}  # 동료 기업의 실제 이름을 익명화된 이름에 매핑하는 딕셔너리
        peer_counter = 1  # 익명화 번호 카운터

        for _, row in target_reviews.iterrows():
            # 'nan' 또는 빈 값을 '정보 없음'으로 처리
            reviewer = row.get('평가기관')
            if pd.isna(reviewer) or not str(reviewer).strip():
                reviewer = '정보 없음'

            if reviewer in all_enterprise_names:
                # 동료 기업의 리뷰인 경우, 고유하게 익명화합니다.
                if reviewer not in peer_anonymizer:
                    # 처음 보는 동료 기업이면, 새로운 익명 ID를 부여합니다.
                    peer_anonymizer[reviewer] = f"동료기업 {peer_counter}"
                    peer_counter += 1
                source_text = peer_anonymizer[reviewer]
            else:
                # 외부 기관의 리뷰
                source_text = f"외부기관: {reviewer}"
            # ▲▲▲▲▲ [수정 완료] ▲▲▲▲▲

            review_data = {
                'year': str(row.get('year', '미상')).replace('.0', ''),
                'source': source_text,
                'rating': row.get('평점', '정보 없음'),
                'review': row.get('평가내용', '내용 없음')
            }
            display_reviews.append(review_data)

        print(f"--- get_reviews_for_company: '{company_name}'에 대한 {len(display_reviews)}개 리뷰 처리 완료 ---")
        return display_reviews

    def get_yearly_category_distribution(self, company_name):
        """
        [오류 수정] '대상기업' 열이 없는 경우를 대비하여, 리뷰 분석을
        안전하게 건너뛰도록 수정한 최종 버전입니다.
        """
        from sentence_transformers import util
        import torch

        if not self.sbert_model or not self.enterprise_category_embeddings:
            print("오류: 기업 분석 모델이 로드되지 않았습니다.");
            return {}

        yearly_distribution = {}
        CAT_WEIGHTS = {'1순위 분류': 1.5, '2순위 분류': 1.2, '3순위 분류': 1.0}
        KEYWORD_WEIGHT = 0.5
        REVIEW_WEIGHT = 1.0

        profile_keys = sorted([k for k in self.unified_profiles.keys() if str(k).isdigit()], key=int, reverse=True)
        if 'base' in self.unified_profiles: profile_keys.append('base')

        for year_key in profile_keys:
            profile_df = self.unified_profiles.get(year_key)
            if profile_df is None or company_name not in profile_df.index: continue

            company_profile = profile_df.loc[company_name]
            category_raw_scores = {cat: 0.0 for cat in self.ENTERPRISE_CATEGORIES}
            year_for_display = year_key if year_key != 'base' else '기본'
            print(f"\n--- {year_for_display}년도 '{company_name}' 카테고리 분포 분석 ---")

            # 1. 프로필 기반 점수 (기존과 동일)
            for cat_level, weight in CAT_WEIGHTS.items():
                declared_cat = company_profile.get(cat_level)
                if declared_cat and isinstance(declared_cat, str) and declared_cat in category_raw_scores:
                    category_raw_scores[declared_cat] += weight

            # 2. 키워드 기반 점수 (기존과 동일)
            keywords_text = company_profile.get('키워드', '')
            if keywords_text and isinstance(keywords_text, str):
                for cat in category_raw_scores:
                    if cat in keywords_text: category_raw_scores[cat] += KEYWORD_WEIGHT

            # 3. 리뷰 기반 점수 계산 (오류 수정 적용)
            reviews_for_analysis = pd.DataFrame()

            # ▼▼▼▼▼ [핵심 오류 수정] ▼▼▼▼▼
            # '대상기업' 열이 있는지 먼저 확인하여 KeyError를 원천적으로 방지합니다.
            if '대상기업' in self.company_review_df.columns and '평가내용' in self.company_review_df.columns:
                year_to_filter = int(year_key) if str(year_key).isdigit() else None

                if year_to_filter and 'year' in self.company_review_df.columns:
                    reviews_for_analysis = self.company_review_df[
                        (self.company_review_df['대상기업'] == company_name) &
                        (self.company_review_df['year'] == year_to_filter)
                        ]

                if reviews_for_analysis.empty:
                    print(f"  - '{year_for_display}'년도 특정 리뷰 없음. '{company_name}'의 전체 리뷰로 분석합니다.")
                    reviews_for_analysis = self.company_review_df[self.company_review_df['대상기업'] == company_name]
            else:
                print("  - 경고: '기업리뷰_데이터' 시트에 '대상기업' 또는 '평가내용' 컬럼이 없어 리뷰 분석을 건너뜁니다.")
            # ▲▲▲▲▲ [수정 완료] ▲▲▲▲▲

            review_text_corpus = ' '.join(
                reviews_for_analysis['평가내용'].dropna()) if not reviews_for_analysis.empty else ""
            if review_text_corpus.strip():
                corpus_embedding = self.sbert_model.encode(review_text_corpus, convert_to_tensor=True)
                review_sim_scores = {cat: util.cos_sim(corpus_embedding, cat_emb).item() for cat, cat_emb in
                                     self.enterprise_category_embeddings.items()}
                for cat, sim_score in review_sim_scores.items():
                    if sim_score > 0.1:
                        category_raw_scores[cat] += sim_score * REVIEW_WEIGHT

            # 4. 최종 점수 정규화 (기존과 동일)
            total_raw_score = sum(category_raw_scores.values())
            if total_raw_score > 0:
                yearly_distribution[year_key] = {cat: score / total_raw_score for cat, score in
                                                 category_raw_scores.items()}
                print(f"  - 최종 분포 계산 완료.")
            else:
                print(f"  - 분석할 데이터가 없어 건너뜁니다.")

        return yearly_distribution

    def summarize_reviews(self, company_name, top_n=5):
        """
        [신규 기능] 지정된 기업의 모든 리뷰를 요약하여 핵심 키워드를 반환합니다.
        """
        if self.company_review_df.empty or '대상기업' not in self.company_review_df.columns:
            return "요약할 리뷰 데이터가 없습니다."

        target_reviews = self.company_review_df[self.company_review_df['대상기업'] == company_name]
        if target_reviews.empty:
            return f"'{company_name}'에 대한 리뷰가 없어 요약할 수 없습니다."

        # 리뷰 텍스트를 하나로 합침
        full_text = ' '.join(target_reviews['평가내용'].dropna())
        if not full_text.strip():
            return "리뷰 내용은 있지만, 텍스트가 비어있어 요약할 수 없습니다."

        # 간단한 키워드 추출 (2글자 이상 단어, 빈도수 기반)
        # 실제 사용 시에는 형태소 분석기(e.g., konlpy)를 사용하면 품질이 향상됩니다.
        words = [word for word in full_text.split() if len(word) >= 2]
        if not words:
            return "유의미한 키워드를 찾을 수 없습니다."

        most_common_words = Counter(words).most_common(top_n)
        keywords = [word for word, count in most_common_words]

        if not keywords:
            return "핵심 키워드를 추출하지 못했습니다."

        return f"리뷰에서 자주 언급된 키워드는 '{', '.join(keywords)}' 입니다."

    def search_companies_by_keyword(self, keyword, top_n=10):
        """ [최종 수정본] 키워드와 가장 관련성 높은 기업을 SBERT 유사도 기준으로 검색합니다. """
        from sentence_transformers import util

        if not self.sbert_model: return []

        latest_year = 'base'
        if any(isinstance(k, int) for k in self.unified_profiles.keys()):
            latest_year = max(k for k in self.unified_profiles.keys() if isinstance(k, int))

        if latest_year not in self.unified_profiles:
            print("--- 키워드 검색: 분석할 기업 프로필 데이터가 없습니다. ---")
            return []

        latest_profiles = self.unified_profiles[latest_year].reset_index()
        # ▼▼▼ [수정] 컬럼명을 실제 데이터와 일치시킴 ▼▼▼
        latest_profiles['corpus'] = latest_profiles['사업내용'].fillna('') + ' ' + \
                                    latest_profiles['키워드'].fillna('') + ' ' + \
                                    latest_profiles['1순위 분류'].fillna('') + ' ' + \
                                    latest_profiles['2순위 분류'].fillna('')

        keyword_embedding = self.sbert_model.encode(keyword, convert_to_tensor=True)
        corpus_embeddings = self.sbert_model.encode(latest_profiles['corpus'].tolist(), convert_to_tensor=True)
        cos_scores = util.cos_sim(keyword_embedding, corpus_embeddings)[0]

        results = [{"company": name, "score": score.item()} for name, score in
                   zip(latest_profiles['company_name'], cos_scores)]
        return sorted(results, key=lambda x: x['score'], reverse=True)[:top_n]

    def get_location_id_from_tripadvisor(self, spot_name):
        """ 트립어드바이저 Location ID를 검색합니다. """
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
        """ 트립어드바이저 리뷰를 수집합니다. """
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

    def get_tourist_spots_in_busan(self):
        """ 국문관광정보 API를 호출하여 부산 지역의 고유한 관광지 목록을 수집합니다. """
        all_spots, seen_titles = [], set()
        content_type_ids = ['12', '14', '28']  # 관광지, 문화시설, 레포츠
        print(f"\n--- 부산 관광정보 수집 시작 (타입: {content_type_ids}) ---")

        for content_type_id in content_type_ids:
            try:
                params = {'serviceKey': self.KOREA_TOUR_API_KEY, 'numOfRows': 500, 'pageNo': 1, 'MobileOS': 'ETC',
                          'MobileApp': 'AppTest', '_type': 'json', 'areaCode': 6, 'contentTypeId': content_type_id}
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
        """ SerpApi(Google)를 통해 특정 장소의 리뷰를 목표 개수만큼 수집합니다. """
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
        """ 범용 SBERT 모델로 리뷰와 카테고리 간 유사도를 계산하여 분류합니다. """
        from sentence_transformers import util
        import torch

        if not self.sbert_model or not self.tourist_category_embeddings:
            print("오류: 유사도 분석 모델이 로드되지 않았습니다.")
            return []

        classified_results = []
        review_texts = [review.get('text', '') for review in all_reviews if review.get('text', '').strip()]
        if not review_texts: return []

        review_embeddings = self.sbert_model.encode(review_texts, convert_to_tensor=True)
        for i, review_data in enumerate(filter(lambda r: r.get('text', '').strip(), all_reviews)):
            review_embedding = review_embeddings[i]
            scores = {cat: util.cos_sim(review_embedding, emb).max().item() for cat, emb in
                      self.tourist_category_embeddings.items()}
            best_category = max(scores, key=scores.get) if scores and max(scores.values()) >= threshold else '기타'
            classified_results.append({'review': review_data.get('text'), 'source': review_data.get('source', '알 수 없음'),
                                       'category': best_category})
        return classified_results

    def classify_reviews(self, all_reviews):
        """ 파인튜닝된 AI 모델을 로드하여 리뷰를 분류합니다. """
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

        classified_results, pred_idx = [], 0
        for review_data in all_reviews:
            text = review_data.get('text', '')
            category = '기타'
            if text.strip() and pred_idx < len(predictions):
                category = predictions[pred_idx]['label']
                pred_idx += 1
            classified_results.append(
                {'review': text, 'source': review_data.get('source', '알 수 없음'), 'category': category})
        print("--- AI 기반 리뷰 분류 완료 ---")
        return classified_results

    def classify_all_companies_for_tourist_spots(self):
        """ 모든 기업의 '사업내용'을 *관광지 카테고리*와 비교하여 미리 분류합니다. """
        from sentence_transformers import util

        if self.unified_profiles and max(self.unified_profiles.keys()):
            latest_year = max(self.unified_profiles.keys())
            company_df = self.unified_profiles[latest_year].reset_index()
        else:
            return

        if company_df.empty or 'description' not in company_df.columns: return
        if not self.sbert_model or not self.tourist_category_embeddings:
            print("경고: 기업-관광지 연계 분류에 필요한 AI 모델이 로드되지 않았습니다.");
            return

        print("\n--- 기업-관광지 연계 사전 분류 시작 ---")
        company_df['description'] = company_df['description'].fillna('')
        business_embeddings = self.sbert_model.encode(company_df['description'].tolist(), convert_to_tensor=True)

        categories, scores = [], []
        for emb in business_embeddings:
            sim_scores = {cat: util.cos_sim(emb, cat_emb).max().item() for cat, cat_emb in
                          self.tourist_category_embeddings.items()}
            if not sim_scores:
                best_cat, best_score = '기타', 0
            else:
                best_cat, best_score = max(sim_scores, key=sim_scores.get), sim_scores[
                    max(sim_scores, key=sim_scores.get)]
            categories.append(best_cat)
            scores.append(best_score)

        company_df['best_tourist_category'] = categories
        company_df['tourist_category_score'] = scores
        self.company_df_for_recommendation = company_df
        print(f"--- 기업-관광지 연계 분류 완료: {len(company_df)}개 기업 분류 ---")

    def get_reviews_by_type(self, company_name):
        """
        [신규 기능] 선택된 기업에 대한 리뷰를 '외부기관'과 익명화된 '동료기업'으로 분리합니다.
        """
        if self.company_review_df.empty or '평가기관' not in self.company_review_df.columns:
            return pd.DataFrame(), pd.DataFrame()

        # 'base' 프로필에 모든 기업 목록이 통합되어 있다는 가정
        base_profiles = self.unified_profiles.get('base')
        if base_profiles is None or base_profiles.empty:
            all_internal_companies = []
        else:
            all_internal_companies = base_profiles.index.tolist()

        target_reviews = self.company_review_df[self.company_review_df['대상기업'] == company_name].copy()
        if target_reviews.empty:
            return pd.DataFrame(), pd.DataFrame()

        external_reviews = target_reviews[~target_reviews['평가기관'].isin(all_internal_companies)]
        peer_reviews = target_reviews[target_reviews['평가기관'].isin(all_internal_companies)].copy()

        # 동료기업 익명화
        if not peer_reviews.empty:
            unique_peers = peer_reviews['평가기관'].unique()
            peer_map = {name: f"동료기업 {i + 1}" for i, name in enumerate(unique_peers)}
            peer_reviews['평가기관'] = peer_reviews['평가기관'].map(peer_map)

        return external_reviews, peer_reviews

    def get_preference_summary(self, company_name):
        """
        [신규 기능] 특정 기업이 평가한 외부 기관별 협업 만족도를 문장 리스트로 요약합니다.
        '선호분야' 시트의 데이터가 필요합니다.
        """
        # '선호분야' 시트 로딩은 load_and_unify_data_sources 함수에 추가 필요
        if not hasattr(self, 'preference_df') or self.preference_df.empty:
            return ["협업 선호도 데이터가 없습니다. ('선호분야' 시트 확인)"]

        prefs_df = self.preference_df[self.preference_df['평가기업명'] == company_name]
        if prefs_df.empty:
            return [f"'{company_name}'의 협업 선호도 평가 기록이 없습니다."]

        summary = []
        for target, group in prefs_df.groupby('평가대상기관'):
            total = len(group)
            # '평점' 열이 문자열일 수 있으므로 숫자로 변환
            pos = len(group[pd.to_numeric(group['평점'], errors='coerce') >= 4])
            ratio = (pos / total) * 100 if total > 0 else 0
            summary.append(f"🤝 '{target}'과의 협업을 {ratio:.0f}% 긍정적으로 평가했습니다.")
        return summary

    def summarize_reviews_statistics(self, reviews_df, reviewer_type, target_company):
        """
        [신규 기능] 주어진 리뷰 DF의 통계를 문장 리스트로 요약합니다.
        """
        if reviews_df.empty:
            return []

        summary = []
        # 평점 데이터 처리
        reviews_df['평점'] = pd.to_numeric(reviews_df['평점'], errors='coerce')
        valid_reviews = reviews_df.dropna(subset=['평점'])
        if valid_reviews.empty:
            return [f"'{reviewer_type}'의 유효한 평점 데이터가 없습니다."]

        if reviewer_type == '외부기관':
            for evaluator, group in valid_reviews.groupby('평가기관'):
                total, pos, avg_score = len(group), len(group[group['평점'] >= 4]), group['평점'].mean()
                ratio = (pos / total) * 100 if total > 0 else 0
                summary.append(f"🏢 '{evaluator}'의 {ratio:.0f}%가 긍정 평가 (평균 {avg_score:.1f}점).")
        elif reviewer_type == '동료기업':
            total, pos, avg_score = len(valid_reviews), len(valid_reviews[valid_reviews['평점'] >= 4]), valid_reviews[
                '평점'].mean()
            ratio = (pos / total) * 100 if total > 0 else 0
            summary.append(f"👥 '동료기업'들의 {ratio:.0f}%가 긍정 평가 (평균 {avg_score:.1f}점).")
        return summary

    def judge_sentiment_by_rating(self, rating):
        """
        [신규 기능] 평점을 기반으로 감성(긍정/중립/부정) 이모지를 반환합니다.
        """
        try:
            score = float(rating)
            if score >= 4: return "😊 긍정"
            if score >= 3: return "😐 중립"
            return "😠 부정"
        except (ValueError, TypeError):
            return "정보 없음"

# ===================================================================
# 2.  프론트 ui
# ===================================================================


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


class MainPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        # 로딩 상태를 표시할 레이블
        self.loading_label = tk.Label(self, text="분석 데이터 로딩 중...", font=("Helvetica", 18, "bold"))
        self.loading_label.pack(expand=True)

        # 메인 컨텐츠를 담을 프레임 (초기에는 숨김)
        self.main_content_frame = tk.Frame(self)

        tk.Label(self.main_content_frame, text="리뷰 기반 관광-기업 분석기", font=("Helvetica", 22, "bold")).pack(pady=50)

        # 페이지 이동 버튼들
        tk.Button(self.main_content_frame, text="기업 검색", font=("Helvetica", 16), width=20, height=3,
                  command=lambda: controller.show_company_search_page()).pack(pady=15)

        tk.Button(self.main_content_frame, text="관광지 검색", font=("Helvetica", 16), width=20, height=3,
                  command=lambda: controller.show_tourist_spot_page()).pack(pady=15)

        tk.Button(self.main_content_frame, text="키워드 검색", font=("Helvetica", 16), width=20, height=3,
                  command=lambda: controller.show_frame("KeywordSearchPage")).pack(pady=15)

    def show_loading_screen(self):
        self.loading_label.pack(expand=True)
        self.main_content_frame.pack_forget()

    def show_main_content(self):
        self.loading_label.pack_forget()
        self.main_content_frame.pack(expand=True, fill='both')


class KeywordSearchPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        # --- 상단 컨트롤 프레임 ---
        top_frame = tk.Frame(self)
        top_frame.pack(pady=10, padx=20, fill='x')

        tk.Button(top_frame, text="< 시작 화면으로", command=lambda: controller.show_frame("StartPage")).pack(side='left',
                                                                                                        padx=(0, 15))
        tk.Label(top_frame, text="키워드:", font=("Helvetica", 12, "bold")).pack(side='left')

        self.keyword_entry = ttk.Entry(top_frame, font=("Helvetica", 12))
        self.keyword_entry.pack(side='left', expand=True, fill='x', padx=5)
        self.keyword_entry.bind("<Return>", self.start_keyword_search)

        tk.Label(top_frame, text="결과 수:").pack(side='left')
        self.top_n_var = tk.StringVar(value='10')
        ttk.Combobox(top_frame, textvariable=self.top_n_var, values=[5, 10, 20, 50], width=4, state="readonly").pack(
            side='left', padx=5)

        self.search_button = ttk.Button(top_frame, text="검색", command=self.start_keyword_search)
        self.search_button.pack(side='left')

        # --- 결과 표시 Treeview ---
        result_frame = ttk.Frame(self, padding=10)
        result_frame.pack(expand=True, fill='both', padx=20, pady=10)

        columns = ("company", "score")
        self.tree = ttk.Treeview(result_frame, columns=columns, show="headings")
        self.tree.heading("company", text="기업명")
        self.tree.heading("score", text="유사도")
        self.tree.column("score", width=100, anchor='center')

        # 상세 보기 버튼을 위한 가상 컬럼
        self.tree.heading("#0", text="")  # 숨겨진 컬럼
        self.tree.column("#0", width=0, stretch=tk.NO)

        self.tree.pack(expand=True, fill='both')
        self.tree.bind("<Double-1>", self.go_to_company_details)

    def start_keyword_search(self, event=None):
        keyword = self.keyword_entry.get().strip()
        if not keyword:
            messagebox.showwarning("입력 오류", "검색할 키워드를 입력해주세요.")
            return

        self.search_button.config(state='disabled')
        self.tree.delete(*self.tree.get_children())  # 이전 결과 초기화

        top_n = int(self.top_n_var.get())
        threading.Thread(target=self._search_thread, args=(keyword, top_n), daemon=True).start()

    def _search_thread(self, keyword, top_n):
        try:
            results = self.controller.analyzer.search_companies_by_keyword(keyword, top_n)
            self.after(0, self._update_ui_with_results, results)
        except Exception as e:
            messagebox.showerror("검색 오류", f"키워드 검색 중 오류 발생:\n{e}")
        finally:
            self.after(0, self.search_button.config, {'state': 'normal'})

    def _update_ui_with_results(self, results):
        for res in results:
            score_percent = f"{res['score'] * 100:.1f}%"
            self.tree.insert("", "end", values=(res['company'], score_percent))

    def go_to_company_details(self, event):
        selected_item = self.tree.focus()
        if not selected_item: return

        item_values = self.tree.item(selected_item, 'values')
        company_name = item_values[0]
        self.controller.navigate_to_company_details(company_name)


class CompanySearchPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        # 필요한 라이브러리를 클래스 생성 시점에 self에 할당
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        import numpy as np
        self.Figure, self.FigureCanvasTkAgg, self.np = Figure, FigureCanvasTkAgg, np

        # --- 상단 컨트롤 프레임 ---
        top_frame = tk.Frame(self)
        top_frame.pack(pady=10, padx=20, fill='x')

        tk.Label(top_frame, text="기업/장소 이름:").pack(side=tk.LEFT, padx=(0, 5))

        # 자동완성 검색창 생성
        self.company_entry = AutocompleteEntry(top_frame, controller=self.controller)
        self.company_entry.pack(side=tk.LEFT, expand=True, fill='x', padx=5)

        # 검색 버튼
        search_button = ttk.Button(top_frame, text="분석 시작", command=self.show_company_analysis)
        search_button.pack(side=tk.LEFT, padx=5)

        # ▼▼▼▼▼ [핵심 수정] 위젯 생성 순서 변경 ▼▼▼▼▼
        # 1. '뒤로가기' 버튼을 먼저 생성합니다.
        self.result_back_button = ttk.Button(top_frame, text="⬅️ 결과/뒤로가기", command=self.controller.show_main_page)

        # 2. '새로고침' 버튼을 생성합니다.
        self.refresh_button = ttk.Button(top_frame, text="🔄 데이터 새로고침", command=self.refresh_data)
        self.refresh_button.pack(side=tk.RIGHT, padx=5)

        # 3. 버튼이 생성된 후에 토글 함수를 호출합니다.
        self.toggle_result_back_button()
        # ▲▲▲▲▲ [수정 완료] ▲▲▲▲▲

        self.status_label = tk.Label(self, text="", fg="blue")
        self.status_label.pack(pady=(0, 5))

        # --- 화면을 4단으로 분할 ---
        paned_window = ttk.PanedWindow(self, orient=tk.VERTICAL)
        paned_window.pack(expand=True, fill='both', padx=20, pady=10)

        # 1. 상단: 그래프 영역
        graph_frame = ttk.LabelFrame(paned_window, text="연도별 사업 카테고리 변화", padding=10)
        paned_window.add(graph_frame, weight=3)
        # ... (그래프 위젯 생성 코드는 기존과 동일) ...

        # 2. 중간-1: 리뷰 통계 요약 (신규 추가)
        stats_summary_frame = ttk.LabelFrame(paned_window, text="리뷰 통계 요약", padding=10)
        paned_window.add(stats_summary_frame, weight=2)
        self.stats_summary_label = tk.Label(stats_summary_frame, text="기업을 선택하면 리뷰 통계가 표시됩니다.", justify=tk.LEFT,
                                            anchor='w')
        self.stats_summary_label.pack(fill='x', padx=5, pady=5)

        # 3. 중간-2: 리뷰 키워드 요약
        keyword_summary_frame = ttk.LabelFrame(paned_window, text="리뷰 키워드 요약", padding=10)
        paned_window.add(keyword_summary_frame, weight=1)
        self.keyword_summary_label = tk.Label(keyword_summary_frame, text="기업을 선택하면 리뷰 키워드 요약이 표시됩니다.", justify=tk.LEFT,
                                              anchor='w')
        self.keyword_summary_label.pack(fill='x', padx=5, pady=5)

        # 4. 하단: 리뷰 목록 영역
        review_list_frame = ttk.LabelFrame(paned_window, text="상세 리뷰 목록", padding=10)
        paned_window.add(review_list_frame, weight=4)

        columns = ('year', 'source', 'rating', 'sentiment', 'review')
        self.review_tree = ttk.Treeview(review_list_frame, columns=columns, show='headings')
        self.review_tree.heading('year', text='연도')
        self.review_tree.heading('source', text='출처')
        self.review_tree.heading('rating', text='평점')
        self.review_tree.heading('sentiment', text='감성')  # 신규 헤더
        self.review_tree.heading('review', text='리뷰 내용')

        # 컬럼 너비 설정
        self.review_tree.column("year", width=60, anchor='center', stretch=tk.NO)
        self.review_tree.column("source", width=120, stretch=tk.NO)
        self.review_tree.column("rating", width=80, anchor='center', stretch=tk.NO)
        self.review_tree.column("sentiment", width=100, anchor='center', stretch=tk.NO)

        review_scrollbar = ttk.Scrollbar(review_list_frame, orient="vertical", command=self.review_tree.yview)
        self.review_tree.configure(yscrollcommand=review_scrollbar.set)

        self.review_tree.pack(side="left", fill="both", expand=True)
        review_scrollbar.pack(side="right", fill="y")

    def toggle_result_back_button(self, show=False):
        if show:
            self.result_back_button.pack(side='left', padx=(0, 5))
        else:
            self.result_back_button.pack_forget()

    def update_company_list(self):
        all_companies = set()
        if self.controller.analyzer.unified_profiles:
            for year, profile_df in self.controller.analyzer.unified_profiles.items():
                if not profile_df.empty:
                    all_companies.update(profile_df.index.tolist())
        companies = sorted(list(all_companies))
        self.company_entry.set_completion_list(companies)
        print(f"--- 기업 검색 페이지: {len(companies)}개 기업 목록 업데이트 완료 ---")

    def refresh_data(self):
        self.status_label.config(text="상태: 구글 시트 정보 새로고침 중...")
        threading.Thread(target=self._refresh_thread, daemon=True).start()

    def _refresh_thread(self):
        self.controller.analyzer.load_and_unify_data_sources()
        self.after(0, self.update_company_list)
        self.after(0, self.status_label.config, {"text": ""})

    def show_company_analysis(self, event=None):
        company_name = self.company_entry.get()
        if not company_name: return

        self.status_label.config(text=f"'{company_name}' 종합 분석 중...")
        self.ax.clear()
        self.ax.set_title(f"'{company_name}' 분석 데이터 로딩 중...")
        self.canvas.draw()
        self.review_tree.delete(*self.review_tree.get_children())
        # ▼▼▼ [수정] 존재하지 않는 self.summary_label 대신 새로운 레이블들을 초기화 ▼▼▼
        self.stats_summary_label.config(text="리뷰 통계 요약을 생성 중입니다...")
        self.keyword_summary_label.config(text="리뷰 키워드 요약을 생성 중입니다...")
        # ▲▲▲ [수정 완료] ▲▲▲

        threading.Thread(target=self._analysis_thread, args=(company_name,), daemon=True).start()

    def _analysis_thread(self, company_name):
        """ 백그라운드 분석 스레드 (요약 기능 호출 추가) """
        try:
            analyzer = self.controller.analyzer
            graph_data = analyzer.get_yearly_category_distribution(company_name)

            # 리뷰를 유형별로 분리
            ext_reviews, peer_reviews = analyzer.get_reviews_by_type(company_name)

            # 통계 요약 생성
            ext_summary = analyzer.summarize_reviews_statistics(ext_reviews, "외부기관", company_name)
            peer_summary = analyzer.summarize_reviews_statistics(peer_reviews, "동료기업", company_name)

            # 협업 선호도 요약 생성
            pref_summary = analyzer.get_preference_summary(company_name)

            # 키워드 요약 생성
            keyword_summary = analyzer.summarize_reviews(company_name)  # 기존 summarize_reviews 함수

            # 모든 리뷰를 합쳐서 목록에 표시
            all_reviews_for_display = self._prepare_reviews_for_display(ext_reviews, peer_reviews)

            self.after(0, self._update_ui, company_name, graph_data, all_reviews_for_display, ext_summary, peer_summary,
                       pref_summary, keyword_summary)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.after(0, self.status_label.config, {"text": f"분석 오류: {e}"})

    def _prepare_reviews_for_display(self, ext_df, peer_df):
        """ 상세 목록에 표시할 리뷰 데이터 리스트를 준비합니다. """
        reviews_list = []
        analyzer = self.controller.analyzer
        for _, row in pd.concat([ext_df, peer_df]).iterrows():
            reviews_list.append({
                'year': row.get('연도', '미상'),
                'source': row.get('평가기관', '정보 없음'),
                'rating': row.get('평점', '정보 없음'),
                'sentiment': analyzer.judge_sentiment_by_rating(row.get('평점')),  # 감성 판단
                'review': row.get('평가내용', '내용 없음')
            })
        return reviews_list

        # ▼▼▼ [수정] _update_ui 메서드의 인자 목록을 호출과 일치시킴 ▼▼▼
    def _update_ui(self, company_name, graph_data, review_data, ext_summary, peer_summary, pref_summary,
                       keyword_summary):

        # ▲▲▲ [수정 완료] ▲▲▲
        """ 모든 분석 결과를 UI에 업데이트합니다. """
        self._update_graph(company_name, graph_data)

        # 새로 추가된 요약 정보들을 업데이트
        self.keyword_summary_label.config(text=keyword_summary)

        # 통계 요약 텍스트 조합
        full_stats_summary = "\n\n".join(
            ["\n".join(ext_summary), "\n".join(peer_summary), "\n".join(pref_summary)]
        )
        self.stats_summary_label.config(text=full_stats_summary.strip() or "요약할 통계 정보가 없습니다.")

        self._update_review_list(review_data)
        self.status_label.config(text="분석 완료")



    def _update_summary(self, summary_text):
        """ [신규] 리뷰 요약 레이블을 업데이트하는 함수 """
        self.summary_label.config(text=summary_text)

    def _update_review_list(self, review_data):
        """ 상세 리뷰 목록을 감성 정보 포함하여 업데이트합니다. """
        self.review_tree.delete(*self.review_tree.get_children())
        for review in review_data:
            self.review_tree.insert('', 'end', values=(
                review['year'], review['source'], review['rating'], review['sentiment'], review['review']
            ))

    def _update_graph(self, company_name, yearly_data):
        self.ax.clear()
        # ▼▼▼ [UI 개선] 데이터가 없을 경우의 처리 강화 ▼▼▼
        if not yearly_data:
            self.ax.text(0.5, 0.5, f"'{company_name}'에 대한\n카테고리 분석 데이터가 없습니다.", ha='center', va='center', fontsize=12,
                         color='gray')
            self.ax.set_title(f"'{company_name}' 분석 결과")
            # 불필요한 축 정보 제거
            self.ax.set_xticks([])
            self.ax.set_yticks([])
            self.ax.spines['top'].set_visible(False)
            self.ax.spines['right'].set_visible(False)
            self.ax.spines['bottom'].set_visible(False)
            self.ax.spines['left'].set_visible(False)
            self.canvas.draw()
            return


class TouristSpotPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        # 상단 헤더
        header_frame = tk.Frame(self)
        header_frame.pack(side='top', fill='x', padx=10, pady=10)
        tk.Button(header_frame, text="< 메인 화면으로", command=lambda: controller.show_main_page()).pack(side='left')

        tk.Label(self, text="분석할 관광지 이름을 입력하세요.", font=("Helvetica", 14)).pack(pady=10)

        input_frame = tk.Frame(self)
        input_frame.pack(pady=5, padx=20, fill='x')
        self.spot_entry = AutocompleteEntry(input_frame, controller=controller, font=("Helvetica", 12))
        self.spot_entry.pack(expand=True, fill='x')

        ctrl_frame = tk.Frame(self)
        ctrl_frame.pack(pady=10)
        tk.Label(ctrl_frame, text="Google 리뷰 수:", font=("Helvetica", 11)).pack(side='left')
        self.review_count_var = tk.StringVar(value='50')
        ttk.Combobox(ctrl_frame, textvariable=self.review_count_var, values=[10, 20, 50, 100, 200], width=5,
                     state="readonly").pack(side='left', padx=5)
        self.analyze_button = tk.Button(ctrl_frame, text="분석 시작", font=("Helvetica", 14, "bold"),
                                        command=self.start_analysis)
        self.analyze_button.pack(side='left', padx=10)

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

    def start_analysis(self):
        # 관광지 분석 로직
        pass

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
    """애플리케이션의 메인 컨트롤러 역할을 하는 최상위 클래스입니다."""
    def __init__(self, api_keys, paths):
        super().__init__()
        self.title("관광-기업 리뷰 분석기")
        self.geometry("1000x800")

        # Analyzer 인스턴스 생성
        self.analyzer = ReviewAnalyzer(api_keys, paths)
        self.analysis_result = {} # 분석 결과를 저장할 변수

        # 프레임을 담을 컨테이너 생성
        container = tk.Frame(self)
        container.pack(side="top", fill="both", expand=True)
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        self.frames = {}
        # 사용할 모든 페이지(Frame)들을 등록합니다. (이름 수정)
        for F in (MainPage, CompanySearchPage, TouristSpotPage, KeywordSearchPage, ResultPage, DetailPage):
            page_name = F.__name__
            frame = F(parent=container, controller=self)
            self.frames[page_name] = frame
            frame.grid(row=0, column=0, sticky="nsew")

        # 초기 로딩 화면 표시
        self.show_frame("MainPage")
        self.frames["MainPage"].show_loading_screen()
        # 백그라운드에서 리소스 로딩 시작
        self._load_resources()

    def show_frame(self, page_name):
        """지정된 이름의 프레임(페이지)을 맨 앞으로 가져옵니다."""
        frame = self.frames[page_name]
        frame.tkraise()

    def _load_resources(self):
        """리소스 로딩을 위한 별도의 스레드를 시작합니다."""
        threading.Thread(target=self._load_resources_thread, daemon=True).start()

    def _load_resources_thread(self):
        """백그라운드에서 모든 데이터를 로딩하는 실제 작업을 수행합니다."""
        try:
            # ▼▼▼ [1차 원인 수정] spot_list 변수를 API 호출을 통해 정의합니다. ▼▼▼
            spot_list = self.analyzer.get_tourist_spots_in_busan()
            # ▲▲▲ [수정 완료] ▲▲▲

            self.analyzer.load_all_resources()

            # 로딩 완료 후 UI 업데이트는 메인 스레드에서 self.after를 통해 안전하게 호출
            self.after(0, self.frames["MainPage"].show_main_content)
            self.after(0, self.frames["CompanySearchPage"].update_company_list)
            self.after(0, self.frames["TouristSpotPage"].update_autocomplete_list, spot_list)

        except Exception as e:
            # ▼▼▼ [2차 원인 수정] 오류 메시지는 반드시 self.after를 통해 호출해야 합니다. ▼▼▼
            error_message = f"데이터 로딩 중 심각한 오류가 발생했습니다: {e}"
            self.after(0, lambda: messagebox.showerror("초기화 오류", error_message))
            self.after(0, self.destroy)
            # ▲▲▲ [수정 완료] ▲▲▲

    def start_full_analysis(self, spot_name, review_count):
        # ▼▼▼ [수정] AI 모델은 self.analyzer에 있습니다. ▼▼▼
        if not self.analyzer.sbert_model:
            # ▲▲▲ [수정 완료] ▲▲▲
            messagebox.showerror("준비 안됨", "AI 모델이 로딩되지 않았습니다.")
            return
        # ▼▼▼ [수정] 실제 분석을 수행할 새 스레드 함수를 호출합니다. ▼▼▼
        threading.Thread(target=self._tourist_spot_analysis_thread, args=(spot_name, review_count), daemon=True).start()
        # ▲▲▲ [수정 완료] ▲▲▲

    def _tourist_spot_analysis_thread(self, spot_name, review_count):
        """관광지 전체 분석을 백그라운드에서 수행합니다."""
        try:
            # 여기에 실제 분석 로직을 추가해야 합니다. (예시)
            # 1. TripAdvisor, Google 등에서 리뷰 수집
            # 2. AI 모델로 리뷰 분류
            # 3. 결과 데이터 조합
            # self.analysis_result = self.analyzer.analyze_tourist_spot(spot_name, review_count)

            print(f"TODO: '{spot_name}'(리뷰 {review_count}개)에 대한 분석 로직 구현 필요")
            # 분석이 끝나면 결과 페이지로 이동
            # self.after(0, self.frames["TouristSpotPage"].analysis_complete_ui)
            # self.after(0, self.show_frame, "ResultPage")
            # self.after(0, self.frames["ResultPage"].update_results)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.after(0, self.frames["TouristSpotPage"].analysis_fail_ui, f"분석 중 오류 발생: {e}")

    def navigate_to_company_details_from_result(self, company_name):
        page = self.frames["CompanySearchPage"]
        page.toggle_result_back_button(show=True)
        page.company_var.set(company_name)
        page.show_company_review()
        self.show_frame("CompanySearchPage")

    def show_main_page(self):
        """메인 페이지로 돌아가는 함수입니다."""
        self.show_frame("MainPage")

    def show_company_search_page(self):
        """기업 분석 페이지를 보여주는 함수입니다."""
        self.show_frame("CompanySearchPage")

    def show_tourist_spot_page(self):
        """관광지 분석 페이지를 보여주는 함수입니다."""
        self.show_frame("TouristSpotPage")

    def navigate_to_company_details(self, company_name):
        # 상세 페이지로 이동하고, 해당 기업의 분석을 바로 시작하는 로직
        self.show_frame("CompanySearchPage")
        self.frames['CompanySearchPage'].company_entry.set(company_name)
        self.frames['CompanySearchPage'].show_company_analysis()

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