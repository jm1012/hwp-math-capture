# 제3자 구성 요소 고지 (Third-Party Notices)

이 프로그램은 아래 오픈소스 구성 요소를 사용합니다. 배포용 실행 파일(Releases의 zip)에는 이 구성 요소들이 함께 들어 있습니다.

## 수식 인식 모델

| 구성 요소 | 라이선스 | 출처 |
|---|---|---|
| texify (코드) | GPL-3.0 | https://github.com/VikParuchuri/texify |
| texify 모델 가중치 (`vikp/texify`) | **CC BY-NC-SA 4.0** | https://huggingface.co/vikp/texify |

> **모델 가중치 이용 조건:** texify 모델은 Vik Paruchuri가 만들었고 CC BY-NC-SA 4.0으로 배포됩니다.
> 따라서 실행 파일(모델 포함)은 **비상업적 용도로만** 쓸 수 있고, 다시 배포할 때도 같은 조건과 출처 표기를 지켜야 합니다.
> 라이선스 전문: https://creativecommons.org/licenses/by-nc-sa/4.0/

## 라이브러리

| 구성 요소 | 라이선스 | 출처 |
|---|---|---|
| PyTorch | BSD-3-Clause | https://github.com/pytorch/pytorch |
| Hugging Face Transformers | Apache-2.0 | https://github.com/huggingface/transformers |
| huggingface_hub, tokenizers, safetensors | Apache-2.0 | https://github.com/huggingface |
| Pillow | MIT-CMU (HPND) | https://github.com/python-pillow/Pillow |
| pywin32 | PSF-2.0 | https://github.com/mhammond/pywin32 |
| pystray | LGPL-3.0 | https://github.com/moses-palmer/pystray |
| NumPy | BSD-3-Clause | https://github.com/numpy/numpy |
| PyInstaller (실행 파일 제작) | GPL-2.0 + 부트로더 예외 | https://github.com/pyinstaller/pyinstaller |
| Python | PSF-2.0 | https://www.python.org |
| Microsoft Visual C++ 런타임 | Microsoft 재배포 허용 조건 | https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files |

각 라이브러리의 라이선스 전문은 해당 저장소와, 실행 파일 폴더 안 `_internal\*.dist-info` 폴더에 들어 있습니다.
