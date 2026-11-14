r"""번들 DLL 의존성 검사:  .venv\Scripts\python check_deps.py [dist\수식캡처]
번들 안의 모든 .dll/.pyd/.exe 가 가져오는(import / delay-import) DLL 중
번들에도 없고 Windows 기본 시스템 DLL 도 아닌 것을 출력한다. 없으면 종료코드 0.
"""
import os, sys
import pefile

SYSTEM = {
    "kernel32", "user32", "gdi32", "advapi32", "shell32", "ole32", "oleaut32", "ws2_32", "ntdll",
    "bcrypt", "crypt32", "comdlg32", "comctl32", "shlwapi", "version", "winmm", "imm32", "setupapi",
    "cfgmgr32", "dbghelp", "psapi", "rpcrt4", "secur32", "uxtheme", "dwmapi", "iphlpapi", "userenv",
    "winhttp", "wininet", "normaliz", "msvcrt", "ucrtbase", "bcryptprimitives", "odbc32", "oledlg",
    # 그 외 모든 Windows 10/11 에 기본 포함되는 DLL
    "gdiplus", "winspool", "winspool.drv", "mpr", "netapi32", "wtsapi32", "powrprof", "msimg32",
    "opengl32", "glu32", "d3d9", "d3d11", "d3d12", "dxgi", "dcomp", "d2d1", "dwrite", "windowscodecs",
    "hid", "wintrust", "ncrypt", "mswsock", "dnsapi", "oleacc", "propsys", "shcore", "usp10",
    "msvfw32", "avicap32", "avrt", "mfplat", "mf", "mfreadwrite", "mfuuid", "ksuser", "dsound",
    "dinput8", "xinput1_4", "wldap32", "kernelbase", "sspicli", "credui", "cryptui", "wevtapi",
    "pdh", "ntdsapi", "authz", "msacm32", "mscms", "comsvcs", "urlmon", "wsock32", "dbgeng",
    "rstrtmgr", "virtdisk", "winusb", "wer", "bthprops.cpl", "hhctrl.ocx", "winsta", "tdh",
    "imagehlp", "esent", "activeds", "netutils", "srvcli", "samcli", "logoncli", "clusapi",
    "dhcpcsvc", "fwpuclnt", "rasapi32", "sensapi", "wlanapi", "nvcuda",  # nvcuda: 드라이버, 지연로드 전용
}


def is_system(name):
    n = name.lower()
    if n.startswith(("api-ms-win-", "ext-ms-")):
        return True
    base = n[:-4] if n.endswith(".dll") else n
    return base in SYSTEM or n in SYSTEM


def imports_of(path):
    try:
        pe = pefile.PE(path, fast_load=True)
        pe.parse_data_directories(directories=[
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"]])
    except Exception as e:
        print("  (읽기 실패)", path, e)
        return set(), set()
    normal = {e.dll.decode(errors="replace") for e in getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])}
    delay = {e.dll.decode(errors="replace") for e in getattr(pe, "DIRECTORY_ENTRY_DELAY_IMPORT", [])}
    pe.close()
    return normal, delay


def check(root):
    files = []
    for dp, _, fns in os.walk(root):
        files += [os.path.join(dp, f) for f in fns if f.lower().endswith((".dll", ".pyd", ".exe"))]
    present = {os.path.basename(f).lower() for f in files}
    missing = {}  # dll -> [(importer, kind)]
    for f in files:
        normal, delay = imports_of(f)
        for kind, names in (("import", normal), ("delay", delay)):
            for d in names:
                if d.lower() in present or is_system(d):
                    continue
                missing.setdefault(d.lower(), []).append((os.path.relpath(f, root), kind))
    return len(files), missing


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist", "수식캡처")
    n, missing = check(root)
    print(f"검사한 파일 {n}개:", root)
    if not missing:
        print("누락된 비시스템 DLL 없음")
        sys.exit(0)
    for d, users in sorted(missing.items()):
        kinds = sorted({k for _, k in users})
        print(f"누락: {d}  [{','.join(kinds)}]  ← {len(users)}개 파일, 예: {users[0][0]}")
    sys.exit(1)
