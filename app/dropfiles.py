"""창에 파일 끌어 놓기 (Windows 탐색기 → tkinter 창)

tkinter 는 파일 끌어 놓기를 지원하지 않아, 창의 메시지 처리기를 바꿔 끼우고 WM_DROPFILES 를 받는다.
새 의존성이 없다 (ctypes 로 user32·shell32 직접 호출). Windows 가 아니면 아무 일도 하지 않는다.
"""
from __future__ import annotations

import sys
import traceback

WM_DROPFILES = 0x0233
_KEEP = []  # 콜백이 가비지 컬렉션되면 창이 죽으므로 붙잡아 둔다


def enable(widget, on_files) -> bool:
    """widget(창)에 파일을 끌어 놓으면 on_files(경로 목록)을 tkinter 스레드에서 부른다. 성공하면 True."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        u32, sh = ctypes.windll.user32, ctypes.windll.shell32
        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        set_proc = getattr(u32, "SetWindowLongPtrW", None) or u32.SetWindowLongW
        set_proc.restype = ctypes.c_void_p
        set_proc.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        u32.CallWindowProcW.restype = LRESULT
        u32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                        wintypes.LPARAM]
        sh.DragQueryFileW.restype = wintypes.UINT
        sh.DragQueryFileW.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.c_wchar_p, wintypes.UINT]
        sh.DragFinish.argtypes = [ctypes.c_void_p]
        sh.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]

        widget.update_idletasks()
        hwnd = widget.winfo_id()
        old = [None]

        def proc(h, msg, wp, lp):
            if msg == WM_DROPFILES:
                files = []
                try:
                    for i in range(sh.DragQueryFileW(wp, 0xFFFFFFFF, None, 0)):
                        n = sh.DragQueryFileW(wp, i, None, 0)
                        buf = ctypes.create_unicode_buffer(n + 1)
                        sh.DragQueryFileW(wp, i, buf, n + 1)
                        files.append(buf.value)
                finally:
                    sh.DragFinish(wp)
                if files:
                    widget.after(0, on_files, files)
                return 0
            return u32.CallWindowProcW(old[0], h, msg, wp, lp)

        cb = WNDPROC(proc)
        _KEEP.append(cb)
        old[0] = set_proc(hwnd, -4, ctypes.cast(cb, ctypes.c_void_p))  # GWLP_WNDPROC
        try:  # 관리자 권한으로 실행했을 때도 탐색기에서 끌어 놓을 수 있게
            for m in (WM_DROPFILES, 0x004A, 0x0049):
                u32.ChangeWindowMessageFilterEx(hwnd, m, 1, None)
        except Exception:
            pass
        sh.DragAcceptFiles(hwnd, True)
        return True
    except Exception:  # noqa: BLE001  끌어 놓기가 안 돼도 프로그램은 돌아야 함
        traceback.print_exc()
        return False


def first_pdf(files):
    return next((f for f in files if f.lower().endswith(".pdf")), None)
