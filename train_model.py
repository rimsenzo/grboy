import pandas as pd
import torch
from sklearn.model_selection import train_test_split
from transformers import (
    AutoTokenizer,
    AutoModelForSequenceClassification,
    Trainer,
    TrainingArguments
)
from datasets import Dataset
import os


def train_review_classifier():
    """
    라벨링된 CSV 데이터를 사용하여 리뷰 분류 모델을 학습하고 저장합니다.
    """
    # --- 1. 기본 설정 ---
    CSV_FILE_PATH = 'combined_training_data.csv'  # 제공해주신 학습 데이터 파일
    BASE_MODEL = 'jhgan/ko-sroberta-multitask'
    OUTPUT_DIR = './my_review_classifier'  # 학습된 모델이 저장될 폴더

    print(f"--- 1. 데이터 로딩 및 전처리 시작 ---")

    # --- 2. 데이터 로드 및 정제 ---
    if not os.path.exists(CSV_FILE_PATH):
        print(f"오류: '{CSV_FILE_PATH}' 파일을 찾을 수 없습니다. 스크립트와 같은 폴더에 있는지 확인해주세요.")
        return

    df = pd.read_csv(CSV_FILE_PATH)
    # Label Studio에서 Export한 컬럼명에 맞춰 수정
    df = df[['text', 'sentiment']].copy()
    df.dropna(subset=['text', 'sentiment'], inplace=True)
    df = df[df['text'].str.strip() != '']
    df = df[df['sentiment'].str.strip() != '']

    print(f"총 {len(df)}개의 유효한 라벨링 데이터를 로드했습니다.")

    # --- 3. 라벨 인코딩 ---
    unique_labels = sorted(df['sentiment'].unique())
    label2id = {label: i for i, label in enumerate(unique_labels)}
    id2label = {i: label for i, label in enumerate(unique_labels)}
    df['label'] = df['sentiment'].map(label2id)

    print(f"라벨 인코딩 완료. 총 {len(unique_labels)}개의 카테고리: {unique_labels}")

    # --- 4. 학습/검증 데이터 분리 (검증 데이터는 참고용으로만 사용) ---
    train_df, _ = train_test_split(df, test_size=0.2, random_state=42, stratify=df['label'])
    train_dataset = Dataset.from_pandas(train_df)

    print(f"학습 데이터 {len(train_dataset)}개를 준비했습니다.")
    print("\n--- 2. 모델 및 토크나이저 준비 ---")

    # --- 5. 토크나이저 로드 및 데이터 토큰화 ---
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)

    def tokenize_function(examples):
        return tokenizer(examples['text'], padding='max_length', truncation=True)

    tokenized_train_dataset = train_dataset.map(tokenize_function, batched=True)
    print("데이터 토큰화 완료.")

    # --- 6. 모델 로드 ---
    model = AutoModelForSequenceClassification.from_pretrained(
        BASE_MODEL, num_labels=len(unique_labels), label2id=label2id, id2label=id2label
    )
    print(f"'{BASE_MODEL}' 모델 로드 완료. 분류할 카테고리 수: {len(unique_labels)}개")
    print("\n--- 3. 모델 학습 시작 ---")

    # --- 7. 학습 설정 (버전 충돌 없는 단순화된 버전) ---
    # ▼▼▼ [핵심 수정] 버전 충돌을 일으키는 인자들을 모두 제거했습니다. ▼▼▼
    training_args = TrainingArguments(
        output_dir=OUTPUT_DIR,  # 결과물 저장 경로
        num_train_epochs=4,  # 전체 데이터 4번 반복 학습
        per_device_train_batch_size=8,  # 한 번에 처리할 데이터 수
        weight_decay=0.01,  # 과적합 방지를 위한 기술
        logging_dir='./logs',  # 학습 로그 저장 경로
        logging_steps=10,  # 10번 학습마다 로그 출력
        save_total_limit=1,  # 최종 모델 1개만 저장
    )
    # ▲▲▲ [수정 완료] ▲▲▲

    # --- 8. 트레이너 생성 및 학습 실행 ---
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized_train_dataset,
        # 검증 데이터셋은 인자에서 제외
    )

    trainer.train()

    print("\n--- 4. 학습 완료 및 모델 저장 ---")

    # --- 9. 최종 모델 저장 ---
    trainer.save_model(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)

    print(f"학습이 완료되었습니다! 맞춤형 모델이 '{OUTPUT_DIR}' 폴더에 성공적으로 저장되었습니다.")


if __name__ == '__main__':
    train_review_classifier()
