import pandas as pd
import os


def merge_datasets():
    """
    기존 학습 데이터와 새로 검수한 데이터를 하나로 합칩니다.
    """
    # --- 파일 경로 설정 ---
    original_data_path = 'project-2-at-2025-07-17-05-58-56f4865a.csv'
    corrected_data_path = 'corrected_reviews.csv'  # AI 예측 후, 사람이 수정한 데이터 파일
    output_path = 'combined_training_data.csv'  # 최종 통합 데이터 파일

    # --- 파일 존재 여부 확인 ---
    if not os.path.exists(original_data_path):
        print(f"오류: 최초 학습 데이터 '{original_data_path}'를 찾을 수 없습니다.")
        return
    if not os.path.exists(corrected_data_path):
        print(
            f"오류: 검수 완료 데이터 '{corrected_data_path}'를 찾을 수 없습니다. (predict_reviews.py 실행 -> Label Studio에서 검토/수정 후 Export 하셨나요?)")
        return

    print("--- 1. 데이터셋 로딩 ---")
    df_original = pd.read_csv(original_data_path)
    df_corrected = pd.read_csv(corrected_data_path)
    print(f"최초 데이터: {len(df_original)}개 행")
    print(f"검수 데이터: {len(df_corrected)}개 행")

    # --- 2. 데이터 통합 및 중복 제거 ---
    # 두 데이터프레임을 위아래로 합침
    df_combined = pd.concat([df_original, df_corrected], ignore_index=True)

    # 'text' 컬럼 기준으로 중복된 리뷰가 있다면, 마지막 것만 남김 (최신 라벨 유지)
    initial_count = len(df_combined)
    df_combined.drop_duplicates(subset=['text'], keep='last', inplace=True)
    final_count = len(df_combined)

    print(f"\n--- 2. 데이터 통합 완료 ---")
    print(f"총 {initial_count}개 데이터를 통합하여, 중복 제거 후 {final_count}개의 고유한 데이터를 확보했습니다.")

    # --- 3. 최종 통합 파일 저장 ---
    df_combined.to_csv(output_path, index=False, encoding='utf-8-sig')
    print(f"\n성공! 통합된 데이터가 '{output_path}' 파일로 저장되었습니다.")


if __name__ == '__main__':
    merge_datasets()
