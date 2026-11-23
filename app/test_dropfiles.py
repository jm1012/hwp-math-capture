"""끌어 놓기 자체 시험 (Windows 전용, 다른 OS 에서는 건너뜀): 같은 프로세스에서 DROPFILES 메모리를 만들어 WM_DROPFILES 를 보냄.
python test_dropfiles.py  (app 폴더에서)"""
import ctypes, sys
if sys.platform != "win32":
    print("skip (Windows 전용)"); sys.exit(0)
import tkinter as tk
from ctypes import wintypes
sys.path.insert(0, ".")
import dropfiles
got = []
r = tk.Tk(); r.title("drop test"); tk.Entry(r).pack(); r.update()
ok = dropfiles.enable(r, lambda f: (got.extend(f), r.after(100, r.destroy)))
print("enable:", ok)
k32, u32 = ctypes.windll.kernel32, ctypes.windll.user32
k32.GlobalAlloc.restype = ctypes.c_void_p; k32.GlobalLock.restype = ctypes.c_void_p
k32.GlobalLock.argtypes = [ctypes.c_void_p]; k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
files = ["C:\\시험 폴더\\가나다.pdf", "C:\\b.txt"]
payload = ("\0".join(files) + "\0\0").encode("utf-16-le")
class DROPFILES(ctypes.Structure):
    _fields_ = [("pFiles", wintypes.DWORD), ("x", wintypes.LONG), ("y", wintypes.LONG), ("fNC", wintypes.BOOL), ("fWide", wintypes.BOOL)]
size = ctypes.sizeof(DROPFILES) + len(payload)
h = k32.GlobalAlloc(0x0042, size)
p = k32.GlobalLock(h)
df = DROPFILES(ctypes.sizeof(DROPFILES), 0, 0, 0, 1)
ctypes.memmove(p, ctypes.byref(df), ctypes.sizeof(df)); ctypes.memmove(p + ctypes.sizeof(df), payload, len(payload))
k32.GlobalUnlock(h)
u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u32.PostMessageW(r.winfo_id(), 0x0233, h, 0)
r.after(5000, r.destroy); r.mainloop()
print("received:", got, "first_pdf:", dropfiles.first_pdf(got))
print("PASS" if got == files else "FAIL")
