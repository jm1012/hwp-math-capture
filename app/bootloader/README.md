# PyInstaller 부트로더 (직접 빌드)

PyInstaller 기본 부트로더로 만든 exe 를 Windows Defender 가 머신러닝 추정으로 오탐하는 일이 있어
(`Behavior:Win32/DefenseEvasion.A!ml`, v2.0.5), 같은 버전 소스에서 직접 빌드한 부트로더를 쓴다.
`build_exe.py` 가 빌드하는 동안만 PyInstaller 설치 폴더의 부트로더를 이것으로 바꿔 끼우고 끝나면 되돌린다.

- `6.22.3/run.exe`, `runw.exe`: PyInstaller 6.22.3 소스(sdist)의 `bootloader/`에서 mingw-w64 (gcc 13) 로 빌드
  ```
  CC=x86_64-w64-mingw32-gcc python waf distclean all --target-arch=64bit
  ```
- **주의 (wscript 고쳐서 빌드)**: mingw 에서는 waf 가 `libgen.h` 의 `dirname()`/`basename()` 을 찾아 쓰는데,
  mingw 의 이 함수는 시스템 ANSI 코드 페이지(CP949)로 경로를 읽어 UTF-8 한글 경로(예: `C:\Users\이정민\…`)를 망가뜨린다.
  그러면 exe 폴더가 `.` 로 잡혀 "Failed to load Python DLL '.\_internal\python312.dll'" 오류가 난다.
  그래서 `wscript` 의 함수 검사 반복문에 다음을 넣어 Windows 에서는 부트로더 자체 구현을 쓰게 했다:
  ```python
  if ctx.env.DEST_OS == 'win32' and function_name in ('dirname', 'basename'):
      continue
  ```
  빌드 뒤 `build/c4che/_cache.py` 의 DEFINES 에 `HAVE_DIRNAME`, `HAVE_BASENAME` 이 없어야 한다.
- PyInstaller 버전을 올리면 같은 버전 소스로 다시 빌드해 `<버전>/` 폴더에 넣을 것 (버전이 다르면 기본 부트로더를 씀).
