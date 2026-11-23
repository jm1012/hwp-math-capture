r"""실행파일 만들기 (Windows, app 폴더에서):  .venv\Scripts\python build_exe.py
결과: dist\수식캡처\ 폴더 (수식캡처.exe + model\)  →  dist\hwp-math-capture-windows.zip (GitHub는 한글 파일명을 바꿔 버려서 영문)
"""
import os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "pyinstaller==6.22.3", "pefile", "onnx"])

# 1) 모델 파일 (없으면 Hugging Face 에서 받음)
import models
model_src = models.prepare(models.download(os.path.join(HERE, "model")))  # + int8 인코더, KV 캐시 가중치
if models.missing(model_src):
    sys.exit(f"모델 파일이 없습니다: {models.missing(model_src)}")

# 2) 아이콘
from PIL import Image, ImageDraw
img = Image.new("RGBA", (256, 256), (31, 111, 235, 255))
d = ImageDraw.Draw(img)
d.rectangle((56, 56, 200, 200), outline="white", width=16)
d.line((88, 160, 128, 96, 168, 160), fill="white", width=16)
img.save("icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])

# 3) PyInstaller (폴더 형태: 시작이 빠름)
# 3-1) 부트로더: PyInstaller 기본 부트로더는 백신 머신러닝 오탐(Behavior:Win32/DefenseEvasion.A!ml)이 잦아
#      소스에서 직접 빌드한 것(bootloader/<버전>/, mingw-w64)을 빌드하는 동안만 바꿔 끼운다
import PyInstaller
BL_SRC = os.path.join(HERE, "bootloader", PyInstaller.__version__)
BL_DST = os.path.join(os.path.dirname(PyInstaller.__file__), "bootloader", "Windows-64bit-intel")
swapped = []
if os.path.isdir(BL_SRC):
    for n in ("run.exe", "runw.exe"):
        src, dst = os.path.join(BL_SRC, n), os.path.join(BL_DST, n)
        if os.path.exists(src) and os.path.exists(dst):
            shutil.copy2(dst, dst + ".orig"); shutil.copy2(src, dst); swapped.append(dst)
    print("직접 빌드한 부트로더 사용:", BL_SRC)
else:
    print("경고: 이 PyInstaller 버전용 부트로더가 없어 기본 부트로더를 씀 →", PyInstaller.__version__)

# 3-2) 버전 정보 (파일 속성 > 자세히)
VERSION = os.environ.get("APP_VERSION", "2.0.5")
_v = tuple(int(x) for x in (VERSION.split(".") + ["0", "0", "0"])[:4])
with open("version_info.txt", "w", encoding="utf-8") as f:
    f.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={_v}, prodvers={_v}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('041204B0', [
    StringStruct('CompanyName', 'hwp-math-capture'),
    StringStruct('FileDescription', '수식 캡처 (한글 수식 붙여넣기)'),
    StringStruct('FileVersion', '{VERSION}'),
    StringStruct('InternalName', 'hwp-math-capture'),
    StringStruct('LegalCopyright', 'GPL-3.0, https://github.com/jm1012/hwp-math-capture'),
    StringStruct('OriginalFilename', '수식캡처.exe'),
    StringStruct('ProductName', 'hwp-math-capture'),
    StringStruct('ProductVersion', '{VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1042, 1200])])])
""")

args = [
    sys.executable, "-m", "PyInstaller", "app.py", "--name", "수식캡처", "--noconfirm", "--clean",
    "--windowed", "--icon", "icon.ico", "--version-file", "version_info.txt",
    "--collect-all", "rapidocr",            # 설정 yaml, 글꼴 등 데이터 파일 포함
    "--add-data", f"spacing_data{os.pathsep}spacing_data",   # 띄어쓰기 모델 (4.5MB)
    "--collect-binaries", "onnxruntime",
    "--hidden-import", "pystray._win32", "--hidden-import", "win32clipboard",
    "--copy-metadata", "rapidocr", "--copy-metadata", "onnxruntime", "--copy-metadata", "tokenizers",
    "--copy-metadata", "numpy", "--copy-metadata", "pyyaml",
    "--exclude-module", "torch", "--exclude-module", "matplotlib", "--exclude-module", "onnx",
]
try:
    subprocess.check_call(args)
finally:
    for dst in swapped:  # 바꿔 끼운 부트로더를 원래대로
        shutil.move(dst + ".orig", dst)

out = os.path.join("dist", "수식캡처")

# 4) VC++ 런타임(x64)을 앱 폴더에 함께 넣는다 → 재배포 패키지가 없는 PC에서도 onnxruntime/opencv 로드 가능
VC_DLLS = ["vcruntime140.dll", "vcruntime140_1.dll", "vcruntime140_threads.dll",
           "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "msvcp140_atomic_wait.dll",
           "msvcp140_codecvt_ids.dll", "concrt140.dll", "vcomp140.dll"]
sysdir = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")


def _ver(p):
    try:
        import pefile
        pe = pefile.PE(p, fast_load=True); pe.parse_data_directories(
            directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
        fi = pe.VS_FIXEDFILEINFO[0]; pe.close()
        return (fi.FileVersionMS << 32) | fi.FileVersionLS
    except Exception:
        return 0


for dll in VC_DLLS:
    src = os.path.join(sysdir, dll)
    if not os.path.exists(src):
        print("경고: 시스템에 없음 →", dll)
        continue
    dst = os.path.join(out, "_internal", dll)
    if not os.path.exists(dst) or _ver(src) >= _ver(dst):   # 더 새 버전으로 통일
        shutil.copy2(src, dst)
    print("VC 런타임 복사:", dll)

# 5) 누락 DLL 검사 (비시스템 DLL 이 빠져 있으면 빌드 실패)
import check_deps
_n, _missing = check_deps.check(out)
if _missing:
    for d, users in sorted(_missing.items()):
        print("누락 DLL:", d, "←", users[0][0])
    sys.exit("빌드 실패: 번들에 없는 DLL 이 있습니다 (위 목록)")
print(f"DLL 의존성 검사 통과 ({_n}개 파일)")

# 원본 인코더/디코더(약 120MB)는 빠른 파일(int8 인코더, KV 캐시 가중치)로 대신하므로 넣지 않음
shutil.copytree(model_src, os.path.join(out, "model"), dirs_exist_ok=True,
                ignore=lambda d, names: [n for n in names if n in ("encoder_model.onnx", "decoder_model.onnx")
                                         or n.endswith((".part", ".part.onnx", ".part.npz"))])
if models.missing(os.path.join(out, "model")):
    sys.exit(f"번들 모델 파일이 없습니다: {models.missing(os.path.join(out, 'model'))}")
with open(os.path.join(out, "사용법.txt"), "w", encoding="utf-8") as f:
    f.write("수식캡처.exe 를 실행하세요.\n"
            "수식 하나: 단축키(기본 Ctrl+Shift+Q)를 누르고 수식을 드래그 → 한글에서 Ctrl+V.\n"
            "글자+수식 지문: 단축키(기본 Ctrl+Alt+J)를 누르고 문제 영역을 드래그 → 한글에서 Ctrl+V.\n"
            "끄기: 작업 표시줄의 '수식 캡처' 창에서 [종료].\n"
            "처음 실행 때 'Windows의 PC 보호' 창이 뜨면 [추가 정보] → [실행].\n")
zip_path = shutil.make_archive(os.path.join("dist", "hwp-math-capture-windows"), "zip", "dist", "수식캡처")
print("완료:", os.path.abspath(out), "/", os.path.abspath(zip_path))
