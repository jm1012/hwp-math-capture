# 웹 버전 (PDF → 한글 .hwpx)

브라우저에서 수학 시험지 PDF를 한글(.hwpx) 파일로 바꾸고, 문제 확인 창에서 오인식을 고칩니다.
**인식은 모두 사용자 브라우저 안에서 하고 PDF는 밖으로 나가지 않습니다** (서버 없음, 정적 사이트).

- 기능: PDF 끌어 놓기 → .hwpx 내려받기, 문제 확인(원본과 결과 나란히, 해상도 2배로 다시 읽기, 문제 영역 다시 잡기, 수식·글·그림 영역 나누기, 고친 결과로 다시 만들기)
- 지문 캡처·클립보드·단축키는 exe 에만 있습니다.

## 구조

exe 와 **같은 파이썬 코드(`app/*.py`)** 를 브라우저 안의 Python(Pyodide)에서 그대로 돌립니다. 그래서 인식 규칙을 고치면 exe 와 웹이 함께 바뀝니다.

| 파일 | 하는 일 |
|---|---|
| `src/index.html`, `app.js`, `app.css` | 화면 |
| `src/engine.js` | 모델 받기(브라우저 Cache Storage 에 보관), 워커 연결 |
| `src/py-worker.js` | Pyodide 로 `app/` 코드 실행, PDFium(wasm) 연결 |
| `src/ort-worker.js` | onnxruntime-web 으로 모델 계산 (WebGPU, 안 되면 WASM). 파이썬 쪽은 SharedArrayBuffer 로 결과를 기다림 |
| `py/onnxruntime`, `py/pypdfium2`, `py/tokenizers` | 브라우저용 대체 모듈 (app 코드가 쓰는 API 만) |
| `py/webapi.py` | 화면이 부르는 함수 (변환, 문제 확인) |
| `build.py` | `web/dist` 만들기 (Pyodide·onnxruntime-web·PDFium·KaTeX 를 npm/jsDelivr 에서 받아 해시 확인) |

모델: 큰 모델은 사용자 브라우저가 Hugging Face 에서 직접 받고(exe 의 `models.py` 와 같은 주소), 빌드 때 만드는 파생 파일(`encoder_int8.onnx`, `decoder_kv.npz`)만 사이트에 둡니다. 처음 한 번 약 270MB.

## 배포

`.github/workflows/web-pages.yml` 이 main 에 올라온 `web/`·`app/` 변경을 GitHub Pages 에 올립니다.
처음 한 번 저장소 **Settings → Pages → Source 를 "GitHub Actions"** 로 바꿔야 합니다.
GitHub Pages 는 응답 헤더를 못 바꾸므로 `coi-serviceworker` 로 cross-origin isolation 을 켭니다 (처음 열 때 한 번 새로 고침됨).

## 시험

```bash
python app/models.py                                # 모델 받기 + 파생 파일 (app/model)
python web/build.py --models app/model
MODEL_DIR=app/model python web/test/serve.py 8765 &  # 시험 서버 (COOP/COEP 헤더)
python web/test/native_run.py /tmp/native.json       # 기준: 원래 파이썬(onnxruntime)으로 184장
node web/test/web_run.mjs /tmp/web.json              # 웹 엔진으로 184장 (Playwright Chromium)
python web/test/compare.py /tmp/native.json /tmp/web.json
node web/test/e2e.mjs 시험지.pdf /tmp/e2e 1-2         # 화면 시험 (변환, 문제 확인, 다시 만들기)
```
