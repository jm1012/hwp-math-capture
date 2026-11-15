# 수식 캡처 → 한글 붙여넣기

화면에 보이는 수식이나 수학 문제를 드래그하면 인식해서, **한글(HWP)에서 Ctrl+V 한 번으로 붙여 주는** Windows 프로그램입니다.

- **수식 캡처** (기본 `Ctrl+Shift+Q`): 수식 하나 → 한글 수식 개체
- **지문 캡처** (기본 `Ctrl+Alt+J`, v2): 글자와 수식이 섞인 문제 → 글자는 글자로, 수식은 수식 개체로 문장 속에 붙음
- 인터넷 없이 내 PC(CPU)에서 동작하는 무료 모델 사용: [Pix2Text](https://github.com/breezedeus/Pix2Text) 수식 검출·인식, [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) 한국어 OCR, [quickspacer](https://github.com/cosmoquester/quickspacer) 띄어쓰기 교정
- 한글 외 프로그램(메모장 등)에 붙이면 수식이 LaTeX 글자(`$…$`)로 붙음

## 로드맵

| 버전 | 기능 | 상태 |
|---|---|---|
| v1.x | 수식 인식 → 한글 수식 붙여넣기 | 완료 |
| v2.x | 수식 + 한글 지문 인식 | 현재 |
| v3.x | 수식 + 지문 인식 + 문제풀이 | 계획 |

각 버전의 실행 파일은 [Releases](../../releases)에서 받을 수 있습니다.

## 설치 (실행 파일)

1. [Releases](../../releases)에서 `hwp-math-capture-windows.zip`을 받아 원하는 곳에 압축을 풉니다.
2. `수식캡처.exe`를 실행합니다. 처음 실행 때 "Windows의 PC 보호" 창이 뜨면 **[추가 정보] → [실행]**.
3. 오른쪽 아래에 "준비 완료" 알림이 뜨면 사용할 수 있습니다 (모델 로드 몇 초).

지원 환경: Windows 10/11, 한글 2020 (다른 버전은 아직 시험하지 않음)

## 사용법

1. 수식 하나: `Ctrl+Shift+Q` / 문제 전체(글자+수식): `Ctrl+Alt+J` → 화면이 어두워지면 영역을 드래그 (`Esc`: 취소)
2. "복사됨" 알림 → 한글에서 `Ctrl+V`
3. 끄기: 작업 표시줄의 **수식 캡처** 창에서 [종료]

단축키 변경, 설정 파일 등 자세한 내용은 [app/사용법.md](app/사용법.md)를 보세요.

## 알아 둘 점

- **크게 보이게 해서 캡처하세요.** 화면 속 글자가 작으면 인식 정확도가 떨어집니다. PDF나 한글 화면을 확대(Ctrl+마우스 휠 등)한 뒤 캡처하면 결과가 훨씬 좋아집니다.
- **그래프·도형 같은 그림은 빼고 캡처하세요.** 그림은 옮겨지지 않고, 그림 속 숫자나 기호가 글자로 섞여 들어갈 수 있습니다. 그림이 있는 문제는 글과 수식 부분만 드래그하세요.
- **수식 캡처는 한국어를 읽지 못합니다.** 수식 하나(`Ctrl+Shift+Q`)로 캡처하면 수식 안에 들어 있는 한글(예: 구간 중괄호의 "…인 경우")이 엉뚱한 기호로 바뀝니다. 한글이 섞인 부분은 지문 캡처(`Ctrl+Alt+J`)를 쓰세요. 다만 지문 캡처에서도 여러 줄짜리 큰 수식(구간 중괄호 등) 안의 한글은 아직 제대로 읽지 못합니다.

**정확도:** 수식 하나는 인쇄체 고등학교 수식 48장 기준 약 77% ([1단계 비교](research/step1-model-compare/결과_1단계.md), [v2 지문 실험](research/step3-passage/결과.md)). 지문 캡처는 한글 글자 오류율 약 7%이고, 조건 상자·(가)(나) 빈칸 상자·그림은 아직 잘 못 읽습니다. 틀린 수식은 한글에서 더블클릭해 수식 편집기로 고치면 됩니다. 손글씨는 아직 시험하지 않았습니다.

## 소스에서 실행

Python 3.12, Windows 필요.

```bat
cd app
setup.bat          :: 가상환경 만들고 필요한 패키지와 모델(약 210MB) 설치 (처음 한 번)
수식캡처.bat        :: 실행
```

실행 파일 만들기: `app` 폴더에서 `.venv\Scripts\python build_exe.py` → `dist\hwp-math-capture-windows.zip`

## 폴더 구성

```
app/        프로그램 코드
  app.py            트레이 프로그램, 단축키, 전체 흐름
  overlay.py        화면 드래그 캡처
  recognizer.py     인식 엔진 묶음 (모델 불러오기)
  mfr.py            수식 이미지 → LaTeX (Pix2Text MFR, onnxruntime)
  mfd.py            그림 속 수식 위치 찾기 (Pix2Text MFD)
  passage.py        글자+수식 지문 인식, 줄/문단 정리
  spacing.py        한국어 띄어쓰기 교정 (quickspacer 모델, numpy)
  latex_fix.py      인식 결과 정리 (표기 통일, 보기 번호 ①~⑤ 등)
  latex2hwp.py      LaTeX → 한글 수식 스크립트 변환
  hwp_clipboard.py  한글 클립보드 형식 만들기 (수식 하나 / 글자+수식 문단)
  models.py         모델 파일 위치와 내려받기
  hotkey.py         전역 단축키 등록/변경
  build_exe.py      실행 파일(zip) 만들기, VC++ 런타임 포함
  check_deps.py     실행 파일에 빠진 DLL 검사
research/   개발 중 실험 기록
  step1-model-compare/  무료 수식 인식 모델 3종 비교
  step2-latex2hwp/      LaTeX → 한글 변환 검증
  step3-passage/        글자+수식 지문 인식 실험 (v2)
  step4-spacing/        띄어쓰기 교정기 비교
```

## 라이선스

- 이 프로그램의 소스 코드는 [GPL-3.0](LICENSE)을 따릅니다.
- v2부터 쓰는 인식 모델은 Pix2Text(MIT), PaddleOCR(Apache-2.0)입니다. v1의 texify 모델(CC BY-NC-SA 4.0, 비상업 조건)은 v2에서 더 이상 쓰지 않습니다.
- 수식 위치 검출 모델(Pix2Text MFD)은 Ultralytics YOLO로 학습되어 모델 파일에 AGPL-3.0 표기가 있습니다. AGPL-3.0은 GPL-3.0과 함께 쓸 수 있고, 이 프로그램은 소스를 공개합니다.
- 사용한 라이브러리의 라이선스는 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)에 정리했습니다.

"한글", "HWP"는 한글과컴퓨터의 상표이며, 이 프로젝트는 한글과컴퓨터와 관련이 없습니다.
