# 제3자 구성 요소 고지 (Third-Party Notices)

이 프로그램은 아래 오픈소스 구성 요소를 사용합니다. 배포용 실행 파일(Releases의 zip)에는 이 구성 요소들이 함께 들어 있습니다.

## 인식 모델 (실행 파일의 `model` 폴더)

| 구성 요소 | 라이선스 | 출처 |
|---|---|---|
| Pix2Text MFR 1.5 (수식 인식, `mfr/`) | MIT | https://huggingface.co/breezedeus/pix2text-mfr-1.5 |
| Pix2Text MFD 1.5 (수식 위치 검출, `mfd/`) | MIT (모델 카드), 파일 메타데이터에 AGPL-3.0 (Ultralytics YOLO로 학습) | https://huggingface.co/breezedeus/pix2text-mfd-1.5 |
| PaddleOCR PP-OCRv5 글자 검출 (`ocr/det.onnx`) | Apache-2.0 | https://huggingface.co/PaddlePaddle/PP-OCRv5_mobile_det_onnx |
| PaddleOCR PP-OCRv5 한국어 인식 (`ocr/rec_korean.onnx`) | Apache-2.0 | https://huggingface.co/PaddlePaddle/korean_PP-OCRv5_mobile_rec_onnx |
| PaddlePaddle PP-DocLayout_plus-L (그림·표 위치 검출, `layout/`) | Apache-2.0 | https://huggingface.co/PaddlePaddle/PP-DocLayout_plus-L_onnx |
| quickspacer ConvSpacer3 띄어쓰기 모델 (`app/spacing_data`, numpy 로 변환) | MIT, Copyright (c) 2022 ParkSangJun | https://github.com/cosmoquester/quickspacer |

> v1.x 실행 파일에 들어 있던 texify 모델(CC BY-NC-SA 4.0, 비상업 조건)은 v2부터 쓰지 않습니다.

## 라이브러리

| 구성 요소 | 라이선스 | 출처 |
|---|---|---|
| ONNX Runtime | MIT | https://github.com/microsoft/onnxruntime |
| RapidOCR | Apache-2.0 | https://github.com/RapidAI/RapidOCR |
| OpenCV (opencv-python-headless) | Apache-2.0 | https://github.com/opencv/opencv-python |
| Hugging Face tokenizers | Apache-2.0 | https://github.com/huggingface/tokenizers |
| Shapely, pyclipper, OmegaConf, PyYAML | BSD-3-Clause / MIT | https://pypi.org |
| Pillow | MIT-CMU (HPND) | https://github.com/python-pillow/Pillow |
| pypdfium2 (PDFium 포함) | Apache-2.0 / BSD-3-Clause (PDFium) | https://github.com/pypdfium2-team/pypdfium2 |
| python-hwpx (.hwpx 파일 만들기) | Apache-2.0 | https://pypi.org/project/python-hwpx/ |
| lxml | BSD-3-Clause | https://github.com/lxml/lxml |
| pywin32 | PSF-2.0 | https://github.com/mhammond/pywin32 |
| pystray | LGPL-3.0 | https://github.com/moses-palmer/pystray |
| NumPy | BSD-3-Clause | https://github.com/numpy/numpy |
| PyInstaller (실행 파일 제작) | GPL-2.0 + 부트로더 예외 | https://github.com/pyinstaller/pyinstaller |
| Python | PSF-2.0 | https://www.python.org |
| Microsoft Visual C++ 런타임 | Microsoft 재배포 허용 조건 | https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files |

각 라이브러리의 라이선스 전문은 해당 저장소와, 실행 파일 폴더 안 `_internal\*.dist-info` 폴더에 들어 있습니다.

## 웹 버전 (`web/`, GitHub Pages)

웹 버전은 위 인식 모델과 파이썬 라이브러리(pywin32, pystray, PyInstaller 제외)를 브라우저 안에서 씁니다. 그 밖에 아래 구성 요소가 사이트에 들어 있습니다.

| 구성 요소 | 라이선스 | 출처 |
|---|---|---|
| Pyodide (브라우저용 Python, NumPy·OpenCV·Pillow·lxml·Shapely·pyclipper 빌드 포함) | MPL-2.0 (각 패키지는 원래 라이선스) | https://github.com/pyodide/pyodide |
| onnxruntime-web | MIT | https://github.com/microsoft/onnxruntime |
| @embedpdf/pdfium (PDFium WebAssembly) | MIT / BSD-3-Clause (PDFium) | https://github.com/embedpdf/embed-pdf-viewer |
| KaTeX (문제 확인 창의 수식 표시) | MIT | https://github.com/KaTeX/KaTeX |
| coi-serviceworker | MIT | https://github.com/gzuidhof/coi-serviceworker |
| 나눔고딕 (원문자 견본, 필요한 글자만) | SIL OFL 1.1 | https://hangeul.naver.com/font |
| colorlog, tqdm, requests, six | MIT / MPL-2.0 / Apache-2.0 | https://pypi.org |
