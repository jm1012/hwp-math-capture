# 수식 캡처 → 한글 붙여넣기

화면에 보이는 수식을 드래그하면 인식해서, **한글(HWP)에서 Ctrl+V 한 번으로 수식 개체로 붙여 주는** Windows 프로그램입니다.

- 단축키(기본 `Ctrl+Shift+Q`) → 수식 영역 드래그 → 1~2초 뒤 "복사됨" → 한글에서 `Ctrl+V`
- 인터넷 없이 내 PC(CPU)에서 동작하는 무료 모델 [texify](https://github.com/VikParuchuri/texify) 사용
- 한글 외 프로그램(메모장 등)에 붙이면 LaTeX 글자로 붙음

## 로드맵

| 버전 | 기능 | 상태 |
|---|---|---|
| v1.x | 수식 인식 → 한글 수식 붙여넣기 | 현재 |
| v2.x | 수식 + 한글 지문 인식 | 계획 |
| v3.x | 수식 + 지문 인식 + 문제풀이 | 계획 |

각 버전의 실행 파일은 [Releases](../../releases)에서 받을 수 있습니다.

## 설치 (실행 파일)

1. [Releases](../../releases)에서 `수식캡처.zip`을 받아 원하는 곳에 압축을 풉니다.
2. `수식캡처.exe`를 실행합니다. 처음 실행 때 "Windows의 PC 보호" 창이 뜨면 **[추가 정보] → [실행]**.
3. 오른쪽 아래에 "준비 완료" 알림이 뜨면 사용할 수 있습니다 (모델 로드 10~30초).

지원 환경: Windows 10/11, 한글 2020 (다른 버전은 아직 시험하지 않음)

## 사용법

1. `Ctrl+Shift+Q` → 화면이 어두워지면 수식 부분을 드래그 (`Esc`: 취소)
2. "복사됨" 알림 → 한글에서 `Ctrl+V` → 수식 개체로 붙음
3. 끄기: 작업 표시줄의 **수식 캡처** 창에서 [종료]

단축키 변경, 설정 파일 등 자세한 내용은 [app/사용법.md](app/사용법.md)를 보세요.

**정확도:** 인쇄체 고등학교 수식 48장 기준 약 73% ([비교 결과](research/step1-model-compare/결과_1단계.md)). 틀린 수식은 한글에서 더블클릭해 수식 편집기로 고치면 됩니다. 손글씨는 아직 시험하지 않았습니다.

## 소스에서 실행

Python 3.12, Windows 필요.

```bat
cd app
setup.bat          :: 가상환경 만들고 필요한 패키지 설치 (처음 한 번)
수식캡처.bat        :: 실행
```

실행 파일 만들기: `app` 폴더에서 `.venv\Scripts\python build_exe.py` → `dist\수식캡처.zip`

## 폴더 구성

```
app/        프로그램 코드
  app.py            트레이 프로그램, 단축키, 전체 흐름
  overlay.py        화면 드래그 캡처
  recognizer.py     수식 이미지 → LaTeX (texify)
  latex2hwp.py      LaTeX → 한글 수식 스크립트 변환
  hwp_clipboard.py  한글 수식 개체 클립보드 형식 만들기
  hotkey.py         전역 단축키 등록/변경
  build_exe.py      실행 파일(zip) 만들기, VC++ 런타임 포함
  check_deps.py     실행 파일에 빠진 DLL 검사
research/   개발 중 실험 기록
  step1-model-compare/  무료 수식 인식 모델 3종 비교
  step2-latex2hwp/      LaTeX → 한글 변환 검증
```

## 라이선스

- 이 프로그램의 소스 코드는 [GPL-3.0](LICENSE)을 따릅니다 (texify 코드가 GPL-3.0이기 때문).
- **수식 인식 모델 가중치**(texify, Vik Paruchuri 제작)는 [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)입니다. 모델이 들어 있는 실행 파일은 **비상업적 용도로만** 쓸 수 있습니다.
- 사용한 라이브러리의 라이선스는 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)에 정리했습니다.

"한글", "HWP"는 한글과컴퓨터의 상표이며, 이 프로젝트는 한글과컴퓨터와 관련이 없습니다.
