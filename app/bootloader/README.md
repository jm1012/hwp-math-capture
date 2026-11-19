# PyInstaller 부트로더 (직접 빌드)

PyInstaller 기본 부트로더로 만든 exe 를 Windows Defender 가 머신러닝 추정으로 오탐하는 일이 있어
(`Behavior:Win32/DefenseEvasion.A!ml`, v2.0.5), 같은 버전 소스에서 직접 빌드한 부트로더를 쓴다.
`build_exe.py` 가 빌드하는 동안만 PyInstaller 설치 폴더의 부트로더를 이것으로 바꿔 끼우고 끝나면 되돌린다.

- `6.22.3/run.exe`, `runw.exe`: PyInstaller 6.22.3 소스(sdist)의 `bootloader/`에서 mingw-w64 (gcc 13) 로 빌드
  ```
  CC=x86_64-w64-mingw32-gcc python waf distclean all --target-arch=64bit
  ```
- PyInstaller 버전을 올리면 같은 버전 소스로 다시 빌드해 `<버전>/` 폴더에 넣을 것 (버전이 다르면 기본 부트로더를 씀).
