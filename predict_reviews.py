import pandas as pd
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification, pipeline
import os


def predict_categories():
    """
    학습된 모델을 로드하여 새로운 리뷰 텍스트 파일의 카테고리를 예측합니다.
    """
    MODEL_PATH = './my_review_classifier'  # 이전에 학습된 모델이 저장된 폴더
    TEST_DATA_PATH = 'test_reviews.txt'  # 분류할 리뷰가 담긴 텍스트 파일
    OUTPUT_CSV_PATH = 'predicted_reviews.csv'  # 예측 결과가 저장될 CSV 파일

    if not os.path.exists(MODEL_PATH):
        print(f"오류: 모델 폴더 '{MODEL_PATH}'를 찾을 수 없습니다. 모델 학습을 먼저 완료해주세요.")
        return
    if not os.path.exists(TEST_DATA_PATH):
        print(f"오류: 테스트 데이터 파일 '{TEST_DATA_PATH}'를 찾을 수 없습니다.")
        return

    print("--- 1. 학습된 모델 및 토크나이저 로딩 ---")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL_PATH)

    # GPU 사용이 가능하면 GPU로, 아니면 CPU로 분류 파이프라인 생성
    device = 0 if torch.cuda.is_available() else -1
    classifier = pipeline('text-classification', model=model, tokenizer=tokenizer, device=device)

    print("--- 2. 테스트 데이터 로딩 ---")
    with open(TEST_DATA_PATH, 'r', encoding='utf-8') as f:
        reviews = [line.strip() for line in f if line.strip()]

    print(f"총 {len(reviews)}개의 리뷰를 로드했습니다.")
    print("--- 3. 카테고리 예측 시작 ---")

    # 모든 리뷰에 대해 예측 실행
    predictions = classifier(reviews)

    # 예측 결과를 데이터프레임으로 변환
    results = []
    for review_text, prediction in zip(reviews, predictions):
        results.append({
            'text': review_text,
            'sentiment': prediction['label']  # Label Studio가 인식하는 컬럼명 'sentiment' 사용
        })

    df_results = pd.DataFrame(results)

    print("--- 4. 예측 결과 저장 ---")
    df_results.to_csv(OUTPUT_CSV_PATH, index=False, encoding='utf-8-sig')

    print(f"예측이 완료되었습니다! 결과가 '{OUTPUT_CSV_PATH}' 파일에 저장되었습니다.")
    print("이제 이 CSV 파일을 Label Studio에 업로드하여 결과를 검토하고 수정할 수 있습니다.")


if __name__ == '__main__':
    predict_categories()
