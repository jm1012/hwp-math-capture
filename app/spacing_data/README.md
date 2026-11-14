# 띄어쓰기 모델

[quickspacer](https://github.com/cosmoquester/quickspacer) (MIT License, Copyright (c) 2022 ParkSangJun) 의
ConvSpacer3 (level 3) 가중치를 TensorFlow SavedModel 에서 꺼내 float16 numpy 파일로 저장한 것입니다.
원 모델은 국립국어원 모두의 말뭉치 문어 말뭉치(버전 1.0)로 학습되었습니다.

- `quickspacer3.npz`: 가중치 (embedding, conv1d ~ conv1d_4)
- `vocab.txt`: 글자 사전 (0=<PAD>, 1=<UNK>, 2=공백)

`app/spacing.py` 가 numpy 로 같은 계산을 합니다 (원본 TensorFlow 결과와 108문장 모두 일치 확인).
