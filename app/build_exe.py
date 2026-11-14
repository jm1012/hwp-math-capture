r"""실행파일 만들기 (Windows, app 폴더에서):  .venv\Scripts\python build_exe.py
결과: dist\수식캡처\ 폴더 (수식캡처.exe + model\)  →  dist\hwp-math-capture-windows.zip (GitHub는 한글 파일명을 바꿔 버려서 영문)
"""
import os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "pyinstaller"])

# 1) 모델을 로컬 폴더로 받아 둔다 (Hugging Face 캐시에서 복사)
from huggingface_hub import snapshot_download
model_src = snapshot_download("vikp/texify", allow_patterns=["*.json", "*.safetensors", "*.model"])

# 2) 아이콘
from PIL import Image, ImageDraw
img = Image.new("RGBA", (256, 256), (31, 111, 235, 255))
d = ImageDraw.Draw(img)
d.rectangle((56, 56, 200, 200), outline="white", width=16)
d.line((88, 160, 128, 96, 168, 160), fill="white", width=16)
img.save("icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])

# 3) PyInstaller (폴더 형태: 시작이 빠름)
args = [
    sys.executable, "-m", "PyInstaller", "app.py", "--name", "수식캡처", "--noconfirm", "--clean",
    "--windowed", "--icon", "icon.ico",
    "--collect-all", "texify", "--collect-data", "transformers",
    "--collect-submodules", "transformers.models.donut", "--collect-submodules", "transformers.models.mbart",
    "--hidden-import", "pystray._win32", "--hidden-import", "win32clipboard",
    "--copy-metadata", "transformers", "--copy-metadata", "tokenizers", "--copy-metadata", "torch",
    "--copy-metadata", "huggingface_hub", "--copy-metadata", "safetensors", "--copy-metadata", "pydantic_settings",
    "--copy-metadata", "regex", "--copy-metadata", "requests", "--copy-metadata", "tqdm",
    "--copy-metadata", "filelock", "--copy-metadata", "numpy", "--copy-metadata", "packaging",
    "--copy-metadata", "pyyaml",
]
subprocess.check_call(args)

out = os.path.join("dist", "수식캡처")

# 4) VC++ 런타임(x64)을 앱 폴더에 함께 넣는다 → 재배포 패키지가 없는 PC에서도 torch 로드 가능
#    (torch_cpu.dll 은 vcruntime140_threads.dll 등 최신 런타임을 요구함)
VC_DLLS = ["vcruntime140.dll", "vcruntime140_1.dll", "vcruntime140_threads.dll",
           "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "msvcp140_atomic_wait.dll",
           "msvcp140_codecvt_ids.dll", "concrt140.dll", "vcomp140.dll", "mfc140u.dll"]
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
    for dst_dir in (os.path.join(out, "_internal"), os.path.join(out, "_internal", "torch", "lib")):
        dst = os.path.join(dst_dir, dll)
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

shutil.copytree(model_src, os.path.join(out, "model"), dirs_exist_ok=True)
with open(os.path.join(out, "사용법.txt"), "w", encoding="utf-8") as f:
    f.write("수식캡처.exe 를 실행하세요.\n"
            "단축키(기본 Ctrl+Shift+Q)를 누르고 수식을 드래그 → 한글에서 Ctrl+V.\n"
            "끄기: 작업 표시줄의 '수식 캡처' 창에서 [종료].\n"
            "처음 실행 때 'Windows의 PC 보호' 창이 뜨면 [추가 정보] → [실행].\n")
zip_path = shutil.make_archive(os.path.join("dist", "hwp-math-capture-windows"), "zip", "dist", "수식캡처")
print("완료:", os.path.abspath(out), "/", os.path.abspath(zip_path))
