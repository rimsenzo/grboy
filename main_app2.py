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

# AI 모델 관련 라이브러리
import torch

# 외부 API 라이브러리
from serpapi import GoogleSearch
import gspread
import pandas as pd
from oauth2client.service_account import ServiceAccountCredentials


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
        # --- API 키 및 경로 초기화 (오류 없는 정상적인 코드) ---
        self.KOREA_TOUR_API_KEY = api_keys['korea_tour_api_key']
        self.TRIPADVISOR_API_KEY = api_keys['tripadvisor_api_key']
        self.SERPAPI_API_KEY = api_keys['serpapi_api_key']
        self.KOREA_TOUR_API_URL = "http://apis.data.go.kr/B551011/KorService2/areaBasedList2"
        self.TRIPADVISOR_API_URL = "https://api.content.tripadvisor.com/api/v1"
        self.paths = paths
        self.GOOGLE_SHEET_KEY_FILENAME = self.paths['google_sheet_key_path']
        self.scopes = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']

        # --- 데이터프레임 초기화 및 로딩 ---
        self.company_df = pd.DataFrame()
        self.review_df = pd.DataFrame()
        self.preference_df = pd.DataFrame()
        self.get_company_data_from_sheet()

        # --- 카테고리 정의 ---
        self.CATEGORIES = {
            'K-문화': ['K팝', 'K드라마', '영화 촬영지', '한류', '부산국제영화제', 'BIFF', '아이돌', '팬미팅', 'SNS', '인스타그램', '핫플레이스', '슬램덩크'],
            '해양': ['바다', '해변', '해수욕장', '해안', '항구', '섬', '등대', '요트', '해상케이블카', '스카이캡슐', '해변열차', '파도', '수족관', '서핑', '스카이워크'],
            '웰니스': ['힐링', '휴식', '스파', '사우나', '온천', '족욕', '마사지', '산책', '자연', '평화', '평온', '치유', '고요함', '명상', '건강'],
            '뷰티': ['미용', '헤어', '피부', '메이크업', '네일', '에스테틱', '피부관리', '뷰티서비스', '마사지', '미용실', '헤어샵', '네일샵', '살롱', '화장품', 'K-뷰티', '퍼스널컬러', '스타일링', '시술', '페이셜'],
            'e스포츠': ['e스포츠', '게임', 'PC방', '대회', '경기장', '프로게이머', '리그오브레전드', 'LCK', '스타크래프트', '페이커', '이스포츠'],
            '미식': ['맛집', '음식', '레스토랑', '카페', '해산물', '음식', '시장', '회', '조개구이', '돼지국밥', '디저트', '식도락']
        }

    def get_company_data_from_sheet(self):
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
                if '기업ID' in self.company_df.columns: self.company_df['기업ID'] = self.company_df['기업ID'].astype(
                    str).str.strip().str.lower()
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
                if e.response.status_code == 503 and attempt < MAX_RETRIES - 1:
                    print(f"경고: Google API 503 오류. {RETRY_DELAY}초 후 재시도... ({attempt + 1}/{MAX_RETRIES})")
                    time.sleep(RETRY_DELAY)
                else:
                    messagebox.showerror("구글 시트 오류", f"데이터 로드 실패 (API 오류):\n{e}"); return
            except Exception as e:
                messagebox.showerror("구글 시트 오류", f"데이터 로드 실패:\n{e}"); return

    def get_reviews_by_type(self, company_name):
        if self.review_df is None or self.review_df.empty: return pd.DataFrame(), pd.DataFrame()
        all_internal_companies = self.company_df['기업명'].unique().tolist()
        target_reviews_df = self.review_df[self.review_df['기업명'] == company_name].copy()
        external_reviews = target_reviews_df[~target_reviews_df['평가기관'].isin(all_internal_companies)]
        peer_reviews = target_reviews_df[target_reviews_df['평가기관'].isin(all_internal_companies)].copy()
        if not peer_reviews.empty:
            unique_reviewers = peer_reviews['평가기관'].unique()
            reviewer_map = {name: f"입주기업 {i + 1}" for i, name in enumerate(unique_reviewers)}
            peer_reviews['평가기관'] = peer_reviews['평가기관'].map(reviewer_map)
        return external_reviews, peer_reviews

    def get_preference_summary(self, company_name):
        if self.preference_df is None or self.preference_df.empty: return []
        company_prefs_df = self.preference_df[self.preference_df['평가기업명'] == company_name]
        if company_prefs_df.empty: return []
        summary_list = []
        for target_institution, group in company_prefs_df.groupby('평가대상기관'):
            if group.empty: continue
            total_reviews, positive_count = len(group), len(group[group['평점'] >= 4])
            positive_ratio = (positive_count / total_reviews) * 100 if total_reviews > 0 else 0
            summary_list.append(f"{company_name}은(는) '{target_institution}'과의 협업을 {positive_ratio:.0f}% 긍정적으로 평가했습니다.")
        return summary_list

    def summarize_reviews(self, reviews_df, reviewer_type, target_company_name):
        if reviews_df.empty: return []
        summary_list = []
        if reviewer_type == '외부기관':
            for evaluator, group in reviews_df.groupby('평가기관'):
                if group.empty: continue
                positive_count, total_count, avg_score = len(group[group['평점'] >= 4]), len(group), group['평점'].mean()
                ratio = (positive_count / total_count) * 100 if total_count > 0 else 0
                summary_list.append(
                    f"'{evaluator}'의 {ratio:.0f}%가 '{target_company_name}'을(를) 긍정적으로 평가하며, 평균 점수는 {avg_score:.1f}점입니다 (5점 만점).")
        elif reviewer_type == '입주기업':
            positive_count, total_count, avg_score = len(reviews_df[reviews_df['평점'] >= 4]), len(reviews_df), \
            reviews_df['평점'].mean()
            ratio = (positive_count / total_count) * 100 if total_count > 0 else 0
            summary_list.append(
                f"'입주기업'들의 {ratio:.0f}%가 '{target_company_name}'을(를) 긍정적으로 평가하며, 평균 점수는 {avg_score:.1f}점입니다 (5점 만점).")
        return summary_list

    def judge_sentiment_by_rating(self, rating):
        try:
            return "긍정 😊" if float(rating) >= 4 else "중립 😐" if float(rating) >= 3 else "부정 😠"
        except (ValueError, TypeError):
            return "정보 없음"

    def get_google_place_id_via_serpapi(self, spot_name):
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
            print("  - 정보: Knowledge Panel에서 Place ID를 찾지 못했습니다. 2단계로 넘어갑니다.")
        except Exception as e:
            print(f"  - 경고: Knowledge Panel 탐색 중 오류 발생 ({e}). 2단계로 넘어갑니다.")
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
            print(f"  - 최종 실패: API 응답에서 유효한 Place ID를 찾지 못했습니다.");
            return None
        except Exception as e:
            print(f"  - 최종 실패: Maps API 탐색 중 예외 발생: {e}"); return None

    def classify_reviews(self, all_reviews):
        """
        [최종 수정] 파인튜닝된 AI 모델을 로드하여 리뷰를 분류합니다.
        """
        model_path = './my_review_classifier'  # 1단계에서 생성된 모델 폴더

        # 모델 폴더가 없으면, 기존의 키워드 기반 분류를 예비로 실행
        if not os.path.exists(model_path):
            print("경고: 학습된 AI 모델을 찾을 수 없습니다. 키워드 기반으로 분류합니다.")
            return self.classify_reviews_by_keyword(all_reviews)

        print(f"\n--- AI 모델 '{model_path}'를 사용하여 리뷰 분류 시작 ---")

        # 분류할 리뷰 텍스트만 리스트로 추출
        review_texts = [review.get('text', '') for review in all_reviews if review.get('text', '').strip()]
        if not review_texts:
            return []

        # 분류 파이프라인 생성 (GPU가 있으면 자동으로 사용)
        classifier = pipeline('text-classification', model=model_path, device=0 if torch.cuda.is_available() else -1)

        # AI 모델로 모든 리뷰를 한 번에 예측
        predictions = classifier(review_texts)

        # 원래 리뷰 데이터와 예측된 카테고리를 합치기
        classified_results = []
        pred_idx = 0
        for review_data in all_reviews:
            text = review_data.get('text', '')
            if text.strip():
                # AI가 예측한 카테고리('label')를 할당
                category = predictions[pred_idx]['label']
                pred_idx += 1
            else:
                category = '기타'  # 내용이 없는 리뷰는 '기타'로 처리

            classified_results.append({
                'review': text,
                'source': review_data.get('source', '알 수 없음'),
                'category': category
            })

        print("--- AI 기반 리뷰 분류 완료 ---")
        return classified_results

    def classify_reviews_by_keyword(self, all_reviews, model, category_embeddings, threshold=0.4):
        from sentence_transformers import util
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
        from sentence_transformers import util
        if self.company_df.empty or '사업내용' not in self.company_df.columns: print("--- 기업 정보가 없어 분류를 건너뜁니다. ---"); return
        print("\n--- 전체 기업 데이터 AI 기반 사전 분류 시작 ---")
        self.company_df['사업내용'] = self.company_df['사업내용'].fillna('')
        business_embeddings = model.encode(self.company_df['사업내용'].tolist(), convert_to_tensor=True)
        categories, scores = [], []
        for emb in business_embeddings:
            sim_scores = {cat: util.cos_sim(emb, cat_emb).max().item() for cat, cat_emb in category_embeddings.items()}
            if not sim_scores: categories.append('기타'); scores.append(0); continue
            best_cat = max(sim_scores, key=sim_scores.get)
            categories.append(best_cat);
            scores.append(sim_scores[best_cat])
        self.company_df['best_category'], self.company_df['category_score'] = categories, scores
        print(f"--- 기업 분류 완료: {len(self.company_df)}개 기업에 카테고리 및 점수 부여 완료 ---")

    def recommend_companies(self, category, top_n=5):
        if self.company_df.empty or 'best_category' not in self.company_df.columns: return []
        recommended_df = self.company_df[self.company_df['best_category'] == category].copy()
        recommended_df.sort_values(by='category_score', ascending=False, inplace=True)
        return recommended_df.head(top_n)['기업명'].tolist()

    # --- 기존의 상세 리뷰/감성분석/요약 메서드 ---
    def get_detailed_reviews_for_company(self, company_id):
        if self.review_df.empty or '기업ID' not in self.review_df.columns: return pd.DataFrame()
        clean_company_id = str(company_id).strip().lower()
        return self.review_df[self.review_df['기업ID'] == clean_company_id].copy()

    def get_reviews_by_type(self, company_name):
        """
        [신규] 선택된 기업에 대한 리뷰를 '외부기관 평가'와 '동료 입주기업 평가'로 분리하여 반환합니다.
        동료 입주기업의 이름은 익명으로 처리됩니다.
        """
        if self.review_df is None or self.review_df.empty:
            return pd.DataFrame(), pd.DataFrame()

        all_internal_companies = self.company_df['기업명'].unique().tolist()
        target_reviews_df = self.review_df[self.review_df['기업명'] == company_name].copy()

        # 외부 기관 평가: 평가기관이 입주기업 목록에 없는 경우
        external_reviews = target_reviews_df[~target_reviews_df['평가기관'].isin(all_internal_companies)]

        # 동료 입주기업 평가: 평가기관이 입주기업 목록에 있는 경우
        peer_reviews = target_reviews_df[target_reviews_df['평가기관'].isin(all_internal_companies)].copy()

        # [요청사항 2] 동료 평가 작성자 익명 처리
        if not peer_reviews.empty:
            unique_reviewers = peer_reviews['평가기관'].unique()
            reviewer_map = {name: f"입주기업 {i + 1}" for i, name in enumerate(unique_reviewers)}
            peer_reviews['평가기관'] = peer_reviews['평가기관'].map(reviewer_map)

        return external_reviews, peer_reviews

    def get_preference_summary(self, company_name):
        """
        [최종 수정] 특정 기업이 평가한 '외부 기관'별 협업 만족도를 요약하여 '문장 리스트'로 반환합니다.
        """
        if self.preference_df is None or self.preference_df.empty:
            return []  # 빈 리스트 반환

        company_prefs_df = self.preference_df[self.preference_df['평가기업명'] == company_name]
        if company_prefs_df.empty:
            return []  # 빈 리스트 반환

        summary_list = []  # 1. 빈 리스트를 먼저 생성합니다.

        for target_institution, group in company_prefs_df.groupby('평가대상기관'):
            if group.empty: continue
            total_reviews = len(group)
            positive_count = len(group[group['평점'] >= 4])
            positive_ratio = (positive_count / total_reviews) * 100 if total_reviews > 0 else 0

            summary_text = f"{company_name}은(는) '{target_institution}'과의 협업을 {positive_ratio:.0f}% 긍정적으로 평가했습니다."
            summary_list.append(summary_text)  # 2. 생성된 문장을 리스트에 추가합니다.

        return summary_list

    def summarize_reviews(self, reviews_df, reviewer_type, target_company_name):
        """
        [최종 수정] 주어진 리뷰 데이터프레임을 요약하여 '문장 리스트'로 반환합니다.
        """
        if reviews_df.empty:
            return []  # 빈 리스트 반환

        summary_list = []  # 1. 빈 리스트를 생성합니다.

        if reviewer_type == '외부기관':
            for evaluator, group in reviews_df.groupby('평가기관'):
                if group.empty: continue
                positive_count = len(group[group['평점'] >= 4])
                total_count = len(group)
                avg_score = group['평점'].mean()
                ratio = (positive_count / total_count) * 100 if total_count > 0 else 0

                summary_text = f"'{evaluator}'의 {ratio:.0f}%가 '{target_company_name}'을(를) 긍정적으로 평가하며, 평균 점수는 {avg_score:.1f}점입니다 (5점 만점)."
                summary_list.append(summary_text)  # 2. 문장을 리스트에 추가합니다.

        elif reviewer_type == '입주기업':
            positive_count = len(reviews_df[reviews_df['평점'] >= 4])
            total_count = len(reviews_df)
            avg_score = reviews_df['평점'].mean()
            ratio = (positive_count / total_count) * 100 if total_count > 0 else 0

            summary_text = f"'입주기업'들의 {ratio:.0f}%가 '{target_company_name}'을(를) 긍정적으로 평가하며, 평균 점수는 {avg_score:.1f}점입니다 (5점 만점)."
            summary_list.append(summary_text)  # 2. 문장을 리스트에 추가합니다.

        return summary_list

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

    def get_peer_reviews(self, company_name):
        """특정 기업에 대한 '동료 입주기업'들의 평가를 찾아 반환합니다."""
        if self.review_df is None or self.review_df.empty:
            return pd.DataFrame()

        all_internal_companies = self.company_df['기업명'].unique().tolist()
        peer_reviews_df = self.review_df[
            (self.review_df['기업명'] == company_name) &
            (self.review_df['평가기관'].isin(all_internal_companies))
            ].copy()

        if not peer_reviews_df.empty:
            unique_reviewers = peer_reviews_df['평가기관'].unique()
            reviewer_map = {name: f"입주기업 {i + 1}" for i, name in enumerate(unique_reviewers)}
            peer_reviews_df['평가기관'] = peer_reviews_df['평가기관'].map(reviewer_map)

        return peer_reviews_df

    def get_tourist_spots_in_busan(self):

        all_spots = []
        # 중복된 장소를 title 기준으로 걸러내기 위한 집합
        seen_titles = set()
        content_type_ids = ['12' , '14' , '28' ]
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
        from sentence_transformers import util
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
        from sentence_transformers import util
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
class AutocompleteEntry(ttk.Entry):
    """
    고급 자동완성 기능을 제공하는 ttk.Entry의 확장 위젯.
    사용자 입력에 따라 Toplevel 팝업으로 제안 목록을 보여줍니다.
    """

    def __init__(self, parent, controller, *args, **kwargs):
        # [핵심 수정] 항목 선택 시 호출할 콜백 함수를 인자로 받음
        self.on_select_callback = kwargs.pop('on_select_callback', None)
        self.completion_list = kwargs.pop('completion_list', [])

        super().__init__(parent, *args, **kwargs)

        self.controller = controller
        self.debounce_timer = None
        self.just_selected = False
        self.var = self["textvariable"]
        if self.var == '':
            self.var = self["textvariable"] = tk.StringVar()

        self.var.trace_add('write', self._debounce_autocomplete)

        self.bind("<FocusOut>", self._hide_popup)
        self.bind("<Down>", self._move_selection)
        self.bind("<Up>", self._move_selection)
        self.bind("<Return>", self._select_item)
        self.bind("<Escape>", self._hide_popup)

        self._popup_window = tk.Toplevel(controller)
        self._popup_window.overrideredirect(True)
        self._popup_window.transient(controller)
        self._popup_window.withdraw()

        self._listbox = tk.Listbox(self._popup_window, font=("Helvetica", 11), selectmode=tk.SINGLE,
                                   exportselection=False, highlightthickness=0)
        self._listbox.pack(expand=True, fill='both')
        self._listbox.bind("<Button-1>", self._select_item)
        self._listbox.bind("<<ListboxSelect>>", lambda e: self.focus_set())

    def set_completion_list(self, new_list):
        self.completion_list = new_list

    def _debounce_autocomplete(self, *args):
        if self.just_selected:
            self.just_selected = False
            return
        if self.debounce_timer:
            self.after_cancel(self.debounce_timer)
        self.debounce_timer = self.after(300, self._show_autocomplete)

    def _show_autocomplete(self):
        typed_text = self.var.get().lower().strip()
        if not typed_text:
            self._hide_popup();
            return
        filtered_list = [item for item in self.completion_list if typed_text in item.lower()]
        if not filtered_list:
            self._hide_popup();
            return

        self._listbox.delete(0, tk.END)
        for item in filtered_list: self._listbox.insert(tk.END, item)

        x, y, width = self.winfo_rootx(), self.winfo_rooty() + self.winfo_height() + 2, self.winfo_width()
        list_height = min(len(filtered_list), 10)
        height = self._listbox.size() * 24 if self._listbox.size() <= list_height else list_height * 24
        self._popup_window.geometry(f"{width}x{height}+{x}+{y}")
        if not self._popup_window.winfo_viewable(): self._popup_window.deiconify()

        self._listbox.selection_clear(0, tk.END);
        self._listbox.selection_set(0);
        self._listbox.see(0)

    def _hide_popup(self, event=None):
        self._popup_window.withdraw()

    def _select_item(self, event=None):
        """[핵심 수정] 항목 선택 후, 포커스를 위젯 밖으로 빼고 콜백을 호출합니다."""
        selected_indices = self._listbox.curselection()
        if not selected_indices:
            self._hide_popup()
            return "break"

        value = self._listbox.get(selected_indices[0])
        self.just_selected = True
        self.var.set(value)
        self._hide_popup()

        # [수정] 더 이상 self.focus_set()을 호출하지 않음

        # [추가] 콜백 함수가 있으면 호출하여 포커스를 이동시킴
        if self.on_select_callback:
            self.on_select_callback()

        return "break"

    def _move_selection(self, event):
        if not self._popup_window.winfo_viewable(): return "break"
        current_selection, size = self._listbox.curselection(), self._listbox.size()
        if not current_selection:
            self._listbox.selection_set(0);
            return "break"
        idx = current_selection[0]
        next_idx = idx + 1 if event.keysym == "Down" else idx - 1
        if 0 <= next_idx < size:
            self._listbox.selection_clear(0, tk.END);
            self.after(10, lambda: self._listbox.selection_set(next_idx));
            self._listbox.see(next_idx)
        return "break"


class TouristSearchPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        header_frame = tk.Frame(self)
        header_frame.pack(fill='x', pady=10, padx=10)
        tk.Button(header_frame, text="< 시작 화면으로", command=lambda: controller.show_frame("StartPage")).pack(side='left')

        tk.Label(self, text="분석할 관광지 이름을 입력하거나, 아래 목록에서 선택하세요.", font=("Helvetica", 14)).pack(pady=10)

        # 1. 자동완성 입력창
        input_frame = tk.Frame(self)
        input_frame.pack(pady=5, padx=20, fill='x')
        tk.Label(input_frame, text="관광지 이름:", font=("Helvetica", 12)).pack(side='left', padx=(0, 5))

        # [핵심 수정] 생성 시 on_select_callback 인자로 포커스 이동 함수를 전달
        self.spot_entry = AutocompleteEntry(input_frame, controller,
                                            font=("Helvetica", 12),
                                            completion_list=[],
                                            on_select_callback=self._focus_on_analyze_button)
        self.spot_entry.pack(side='left', expand=True, fill='x')

        # 2. 전체 목록 리스트박스
        list_frame = tk.Frame(self)
        list_frame.pack(pady=10, padx=20, fill='both', expand=True)
        list_scrollbar = tk.Scrollbar(list_frame, orient="vertical")
        self.listbox = tk.Listbox(list_frame, font=("Helvetica", 11), yscrollcommand=list_scrollbar.set)
        list_scrollbar.config(command=self.listbox.yview)
        list_scrollbar.pack(side="right", fill="y")
        self.listbox.pack(side="left", fill="both", expand=True)
        self.listbox.bind('<<ListboxSelect>>', self.on_listbox_select)

        # 3. 분석 컨트롤
        analysis_control_frame = tk.Frame(self)
        analysis_control_frame.pack(pady=10, padx=20)
        tk.Label(analysis_control_frame, text="Google 리뷰 수:", font=("Helvetica", 11)).pack(side='left')
        self.review_count_var = tk.StringVar()
        review_count_combo = ttk.Combobox(analysis_control_frame, textvariable=self.review_count_var,
                                          values=[10, 20, 50, 100, 200], width=5, font=("Helvetica", 11),
                                          state="readonly")
        review_count_combo.set(50)
        review_count_combo.pack(side='left', padx=(0, 20))
        self.analyze_button = tk.Button(analysis_control_frame, text="분석 시작", font=("Helvetica", 14, "bold"),
                                        command=self.start_analysis)
        self.analyze_button.pack(side='left')

        # 4. 하단 상태 표시줄
        status_frame = tk.Frame(self)
        status_frame.pack(fill='x', padx=20, pady=(5, 10), side='bottom')
        self.status_label = tk.Label(status_frame, text="", font=("Helvetica", 10))
        self.status_label.pack()
        self.progress_bar = ttk.Progressbar(status_frame, orient='horizontal', mode='determinate')

    def _focus_on_analyze_button(self):
        """[핵심 추가] '분석 시작' 버튼으로 키보드 포커스를 이동시키는 콜백 함수."""
        self.analyze_button.focus_set()

    def on_listbox_select(self, event):
        selected_indices = self.listbox.curselection()
        if not selected_indices: return
        selected_value = self.listbox.get(selected_indices[0])
        self.spot_entry.var.set(selected_value)
        # 리스트박스 선택 시에도 포커스를 분석 버튼으로 이동
        self._focus_on_analyze_button()

    def update_autocomplete_list(self, spot_list):
        spot_names = sorted([spot['title'] for spot in spot_list if spot and spot.get('title')])
        self.spot_entry.set_completion_list(spot_names)
        self.listbox.delete(0, tk.END)
        for name in spot_names: self.listbox.insert(tk.END, name)
        self.status_label.config(text=f"상태: 대기 중 ({len(spot_names)}개 관광지 로드 완료)")

    def start_analysis(self):
        spot_name = self.spot_entry.get()
        if not spot_name: messagebox.showwarning("입력 오류", "분석할 관광지 이름을 입력해주세요."); return
        if spot_name not in self.spot_entry.completion_list: messagebox.showwarning("입력 오류",
                                                                                    "목록에 있는 관광지를 선택하거나 정확히 입력해주세요."); return
        try:
            review_count = int(self.review_count_var.get())
        except (ValueError, TypeError):
            review_count = 50
        self.controller.start_full_analysis(spot_name, review_count)

    def analysis_start_ui(self, spot_name):
        self.status_label.config(text=f"'{spot_name}' 분석을 시작합니다...");
        self.progress_bar.pack(fill='x', pady=(5, 0));
        self.analyze_button.config(state='disabled')

    def update_progress_ui(self, value, message):
        self.progress_bar['value'] = value; self.status_label.config(text=message)

    def analysis_complete_ui(self):
        self.progress_bar.pack_forget();
        self.analyze_button.config(state='normal');
        self.status_label.config(text="분석 완료! 결과 페이지로 이동합니다.");
        self.spot_entry.delete(0, tk.END)

    def analysis_fail_ui(self, error_message):
        messagebox.showerror("분석 오류", error_message);
        self.progress_bar.pack_forget();
        self.analyze_button.config(state='normal');
        self.status_label.config(text="분석 실패")

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

        # 1. 상단 프레임: 모든 컨트롤 위젯을 담습니다.
        top_frame = tk.Frame(self)
        top_frame.pack(pady=10, padx=20, fill='x')

        button_container = tk.Frame(top_frame)
        button_container.pack(side='left', padx=(0, 15))

        # 1. 항상 표시되는 '< 시작 화면으로' 버튼
        tk.Button(button_container, text="< 시작 화면으로",
                  command=lambda: controller.show_frame("StartPage")).pack(side='left')

        # 2. 조건부로 표시될 '< 분석 결과로 돌아가기' 버튼 (객체만 생성하고 화면에는 아직 표시 안 함)
        self.result_back_button = tk.Button(button_container, text="< 분석 결과로 돌아가기",
                                            command=lambda: controller.show_frame("ResultPage"))
        # --- ▲▲▲ [수정 완료] ▲▲▲ ---

        # 기업 선택 위젯들 (버튼 컨테이너 오른쪽에 배치)
        tk.Label(top_frame, text="기업 선택:", font=("Helvetica", 12, "bold")).pack(side='left', padx=(0, 10))
        self.company_entry = AutocompleteEntry(top_frame, controller,
                                               font=("Helvetica", 12),
                                               # 항목 선택 시 show_company_review 메서드가 바로 호출되도록 콜백 설정
                                               on_select_callback=self.show_company_review)
        self.company_entry.pack(side='left', expand=True, fill='x')
        #
        self.company_var = self.company_entry.var
        self.company_combobox = ttk.Combobox(top_frame, textvariable=self.company_var, width=40, state='readonly')
        self.company_combobox.pack(side='left', expand=True, fill='x')
        #self.company_combobox.bind("<<ComboboxSelected>>", self.show_company_review)

        # 목록 새로고침 버튼
        refresh_button = ttk.Button(top_frame, text="목록 새로고침", command=self.refresh_data)
        refresh_button.pack(side='left', padx=(10, 0))

        # 나머지 UI 요소들 (이전과 동일)
        self.status_label = tk.Label(self, text="", fg="blue")
        self.status_label.pack(pady=(0, 5))
        main_pane = ttk.PanedWindow(self, orient='vertical')
        main_pane.pack(expand=True, fill='both', padx=20, pady=10)
        summary_frame = ttk.LabelFrame(main_pane, text="종합 평가 요약", padding=10)
        main_pane.add(summary_frame, weight=1)
        self.summary_text = tk.Text(summary_frame, wrap='word', height=8, font=("Helvetica", 11), state='disabled', bg='#f0f0f0', fg='black')
        self.summary_text.pack(expand=True, fill='both')
        detail_frame = ttk.LabelFrame(main_pane, text="상세 평가 목록", padding=10)
        main_pane.add(detail_frame, weight=2)
        self.detail_text = tk.Text(detail_frame, wrap='word', font=("Helvetica", 11), state='disabled')
        self.detail_text.pack(expand=True, fill='both')

    def toggle_result_back_button(self, show):
        """[핵심 추가] '분석 결과로 돌아가기' 버튼의 표시 여부를 제어하는 함수."""
        if show:
            # 버튼이 이미 표시된 상태가 아니라면, 화면에 추가합니다.
            if not self.result_back_button.winfo_ismapped():
                self.result_back_button.pack(side='left', padx=(5, 0))
        else:
            # 버튼을 화면에서 숨깁니다.
            self.result_back_button.pack_forget()

    def update_company_list(self):
        companies = self.controller.analyzer.company_df['기업명'].unique().tolist()
        self.company_combobox['values'] = sorted(companies)
        if companies:
            self.company_combobox.current(0)
            self.show_company_review()

    def refresh_data(self):
        self.status_label.config(text="상태: 구글 시트 정보 새로고침 중...")
        threading.Thread(target=self._refresh_thread, daemon=True).start()

    def _refresh_thread(self):
        self.controller.analyzer.get_company_data_from_sheet()
        self.after(0, self.update_company_list)
        self.after(0, self.status_label.config, {"text": ""})

    def show_company_review(self, event=None):
        selected_company_name = self.company_var.get()
        if not selected_company_name: return

        for widget in [self.summary_text, self.detail_text]:
            widget.config(state=tk.NORMAL)
            widget.delete('1.0', tk.END)

        preference_summaries = self.controller.analyzer.get_preference_summary(selected_company_name)
        if preference_summaries:
            self.summary_text.insert(tk.END, "--- 외부 기관 협업 평가 ---\n")
            for summary in preference_summaries:
                self.summary_text.insert(tk.END, f"• {summary}\n")
            self.summary_text.insert(tk.END, "\n")

        external_reviews, peer_reviews = self.controller.analyzer.get_reviews_by_type(selected_company_name)
        external_summaries = self.controller.analyzer.summarize_reviews(external_reviews, '외부기관', selected_company_name)
        if external_summaries:
            self.summary_text.insert(tk.END, "--- 외부 기관의 평가 요약 ---\n")
            for summary in external_summaries:
                self.summary_text.insert(tk.END, f"• {summary}\n")
            self.summary_text.insert(tk.END, "\n")

        peer_summaries = self.controller.analyzer.summarize_reviews(peer_reviews, '입주기업', selected_company_name)
        if peer_summaries:
            self.summary_text.insert(tk.END, "--- 동료 입주기업의 평가 요약 ---\n")
            for summary in peer_summaries:
                self.summary_text.insert(tk.END, f"• {summary}\n")
            self.summary_text.insert(tk.END, "\n")

        if not preference_summaries and not external_summaries and not peer_summaries:
            self.summary_text.insert(tk.END, "표시할 평가 요약 정보가 없습니다.")

        all_reviews = pd.concat([external_reviews, peer_reviews], ignore_index=True)
        if all_reviews.empty:
            self.detail_text.insert(tk.END, "표시할 상세 평가 정보가 없습니다.")
        else:
            for index, row in all_reviews.iterrows():
                evaluator, rating, content = row['평가기관'], row['평점'], row['평가내용']
                sentiment = self.controller.analyzer.judge_sentiment_by_rating(rating)
                self.detail_text.insert(tk.END, f"[작성: {evaluator}]\n")
                self.detail_text.insert(tk.END, f"평점: {rating:.1f}  |  분석: {sentiment}\n")
                self.detail_text.insert(tk.END, f"내용: {content}\n--------------------------------------------------\n")

        for widget in [self.summary_text, self.detail_text]:
            widget.config(state=tk.DISABLED)

class ResultPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        # --- 상단 헤더 프레임 ---
        header_frame = tk.Frame(self)
        header_frame.pack(fill='x', pady=10, padx=10, side='top')

        tk.Button(header_frame, text="< 관광지 검색으로", command=lambda: controller.show_frame("TouristSearchPage")).pack(
            side='left')

        self.title_label = tk.Label(header_frame, text="", font=("Helvetica", 18, "bold"))
        self.title_label.pack(side='left', padx=20)

        # '텍스트로 내보내기' 버튼
        self.export_button = tk.Button(header_frame, text="리뷰 텍스트로 내보내기 💾", command=self.export_reviews_to_txt)
        self.export_button.pack(side='right', padx=10)

        # --- 메인 콘텐츠 프레임 (스크롤 가능 영역) ---
        main_content_frame = tk.Frame(self)
        main_content_frame.pack(fill="both", expand=True, padx=10, pady=10)

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

    def export_reviews_to_txt(self):
        """
        [수정 완료] 'tk.filedialog'가 아닌, 직접 import한 'filedialog'를 사용합니다.
        """
        result = self.controller.analysis_result
        if not result or 'classified_reviews' not in result:
            messagebox.showwarning("내보내기 오류", "내보낼 분석 결과가 없습니다.")
            return

        spot_name = result.get('spot_name', 'untitle_reviews')
        safe_spot_name = "".join([c for c in spot_name if c.isalpha() or c.isdigit() or c in (' ', '_')]).rstrip()

        try:
            # --- ▼▼▼ 바로 이 부분이 수정되었습니다 ▼▼▼ ---
            filepath = filedialog.asksaveasfilename(
                defaultextension=".txt",
                filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")],
                initialfile=f"{safe_spot_name}_리뷰.txt",
                title="리뷰를 텍스트 파일로 저장"
            )
            # --- ▲▲▲ 여기까지 수정 완료 ▲▲▲ ---

            if not filepath:
                return

            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(f"--- '{spot_name}' 관광지 리뷰 분석 결과 ---\n\n")

                classified_reviews = result.get('classified_reviews', [])
                if not classified_reviews:
                    f.write("수집된 리뷰 데이터가 없습니다.")
                else:
                    # 라벨링하기 좋은 형식으로, 리뷰 내용만 한 줄에 하나씩 저장합니다.
                    for review_data in classified_reviews:
                        text = review_data.get('review', '').strip()
                        if text:  # 내용이 있는 리뷰만 저장
                            f.write(f"{text}\n")

            messagebox.showinfo("저장 완료", f"리뷰를 성공적으로 저장했습니다.\n\n경로: {filepath}")

        except Exception as e:
            messagebox.showerror("파일 저장 오류", f"파일을 저장하는 중 오류가 발생했습니다:\n{e}")

    def update_results(self):
        for widget in self.scrollable_frame.winfo_children(): widget.destroy()

        result = self.controller.analysis_result
        self.title_label.config(text=f"'{result.get('spot_name', '')}' 분석 결과")

        if result.get('recommended_companies'):
            reco_frame = ttk.LabelFrame(self.scrollable_frame, text=f"🏫 '{result.get('best_category')}' 연관 기업 추천",
                                        padding=10)
            reco_frame.pack(fill='x', padx=10, pady=10, anchor='n')
            for company_name in result['recommended_companies']:
                company_link = tk.Label(reco_frame, text=f"  - {company_name}",
                                        font=("Helvetica", 12, "underline"), fg="blue", cursor="hand2")
                company_link.pack(anchor='w', pady=3)
                company_link.bind("<Button-1>",
                                  lambda event,
                                         name=company_name: self.controller.navigate_to_company_details_from_result(
                                      name))

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
        self.withdraw()  # 메인 윈도우를 초기에 숨깁니다.

        self.title("관광-기업 연계 분석기")
        self.geometry("800x650")
        font.nametofont("TkDefaultFont").configure(family="Helvetica", size=12)

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

        # --- [핵심 수정 1] ---
        # __init__에서는 직접 아무것도 실행하지 않습니다.
        # "0.1초 뒤에 팝업을 띄우고 로딩을 준비해줘" 라고 예약만 합니다.
        self.after(100, self.show_popup_and_prepare_loading)

    def show_popup_and_prepare_loading(self):
        """팝업을 먼저 화면에 그리고, 그 다음에 로딩을 시작하도록 예약하는 중간 다리 역할의 메서드."""
        # 1. 팝업 창을 만들고 화면에 그리도록 요청합니다.
        self.create_loading_popup()

        # --- [핵심 수정 2] ---
        # '바로' 로딩을 시작하지 않고, 팝업이 그려질 아주 짧은 시간(50ms)을 줍니다.
        # 그 후에 로딩 스레드를 시작하도록 다시 한번 '예약'합니다.
        # 이 시간차 덕분에 팝업이 확실하게 화면에 먼저 나타납니다.
        self.after(50, self.load_initial_resources)

    def create_loading_popup(self):
        """로딩 상태를 보여주는 팝업 Toplevel 창을 생성하고 중앙에 배치합니다."""
        self.loading_popup = tk.Toplevel(self)
        self.loading_popup.title("로딩 중")
        self.loading_popup.resizable(False, False)
        self.loading_popup.protocol("WM_DELETE_WINDOW", lambda: None)
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

        # "일단 화면에 그려줘" 라고 Tkinter에 요청하는 중요한 코드입니다.
        self.loading_popup.update_idletasks()

    def close_loading_popup(self):
        """로딩 팝업을 닫고 메인 애플리케이션 창을 보여줍니다."""
        if hasattr(self, 'loading_popup') and self.loading_popup.winfo_exists():
            self.loading_popup.grab_release()
            self.loading_popup.destroy()
        self.deiconify()
        self.lift()
        self.focus_force()

    def load_initial_resources(self):
        """(이제 준비가 되었으니) 백그라운드에서 리소스 로딩을 시작합니다."""
        threading.Thread(target=self._load_resources_thread, daemon=True).start()

    def show_frame(self, page_name):
        frame = self.frames[page_name]
        if page_name == "CompanySearchPage": frame.update_company_list()
        if page_name == "ResultPage": frame.update_results()
        frame.tkraise()

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
            from sentence_transformers import sentencetransformers, util
            from transformers import pipeline
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

        # [핵심 수정] 이제 함수를 호출하여 데이터 로딩/정리 작업만 시킵니다.
        self.analyzer.get_company_data_from_sheet()

        self.after(0, page.refresh_display)
        self.after(0, page.status_label.config, {"text": ""})

    def navigate_to_company_search(self):
        """
        [수정] 일반 경로로 기업 검색 페이지로 이동합니다.
        '분석 결과로 돌아가기' 버튼을 숨깁니다.
        """
        company_page = self.frames["CompanySearchPage"]
        company_page.toggle_result_back_button(show=False)
        self.show_frame("CompanySearchPage")

    def navigate_to_company_details_from_result(self, company_name):
        """
        [수정] 결과 페이지에서 기업 상세 정보로 이동합니다.
        '분석 결과로 돌아가기' 버튼을 표시합니다.
        """
        company_page = self.frames["CompanySearchPage"]
        company_page.toggle_result_back_button(show=True)

        # 선택한 기업 정보 설정 및 화면 표시
        company_page.company_var.set(company_name)
        company_page.show_company_review()
        self.show_frame("CompanySearchPage")

    def _show_error_message_safely(self, title, message):
        """[신규] 메인 스레드에서 안전하게 오류 메시지 박스를 띄우는 함수"""
        messagebox.showerror(title, message)
        # 치명적 오류가 발생했으므로, 팝업을 닫고 프로그램을 종료합니다.
        self.close_loading_popup()
        self.destroy()

    def _load_resources_thread(self):
        """백그라운드에서 리소스를 로드하고 로딩 팝업의 상태를 업데이트합니다."""
        total_steps = 3

        def update_popup(progress, message):
            self.loading_progress_bar['value'] = progress
            self.loading_status_label.config(text=message)

        try:
            # 1단계: 관광지 목록 로딩
            self.after(0, update_popup, 20, "자동완성용 관광지 목록 로딩 중...")
            all_spots = self.analyzer.get_tourist_spots_in_busan()
            self.frames["TouristSearchPage"].update_autocomplete_list(all_spots)

            # 2단계: AI 모델 로딩 (지연 import 적용)
            self.after(0, update_popup, 50, f"AI 분석 모델 로딩 중... (장치: {self.device})")
            from sentence_transformers import SentenceTransformer
            self.sbert_model = SentenceTransformer('jhgan/ko-sroberta-multitask', device=self.device)
            self.category_embeddings = {cat: self.sbert_model.encode(kw, convert_to_tensor=True) for cat, kw in
                                        self.analyzer.CATEGORIES.items()}
            print("--- AI 모델 및 카테고리 임베딩 로딩 완료 ---")

            # 3단계: 기업 정보 AI 기반 분류
            self.after(0, update_popup, 80, "기업 정보 분석 및 분류 중...")
            self.analyzer.classify_all_companies(self.sbert_model, self.category_embeddings)

            self.after(0, update_popup, 100, "준비 완료!")
            self.after(500, self.close_loading_popup)

        except Exception as e:
            # --- [핵심 수정] ---
            # 여기서 직접 messagebox를 호출하지 않습니다.
            # 대신, self.after를 통해 메인 스레드에게 오류 메시지 표시를 '요청'합니다.
            error_message = f"프로그램 준비 중 오류가 발생했습니다.\n\n오류 유형: {type(e).__name__}\n\n오류 내용: {e}"
            self.after(0, self._show_error_message_safely, "초기화 오류", error_message)


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

