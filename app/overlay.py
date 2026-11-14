"""화면 캡처 오버레이: 화면을 어둡게 덮고 드래그한 영역을 잘라 돌려준다 (Windows 캡처 도구처럼)."""
from __future__ import annotations

import ctypes
import tkinter as tk

from PIL import Image, ImageEnhance, ImageGrab, ImageTk


def enable_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # 모니터별 DPI
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def virtual_screen():
    u = ctypes.windll.user32
    return (u.GetSystemMetrics(76), u.GetSystemMetrics(77),   # 왼쪽, 위 (음수일 수 있음)
            u.GetSystemMetrics(78), u.GetSystemMetrics(79))   # 너비, 높이


def select_region(root: tk.Tk) -> Image.Image | None:
    """모든 모니터를 덮는 창을 띄우고 드래그한 영역 이미지를 돌려준다. Esc/우클릭은 취소."""
    x0, y0, w, h = virtual_screen()
    shot = ImageGrab.grab(all_screens=True)
    if shot.size != (w, h):
        shot = shot.resize((w, h))
    dim = ImageEnhance.Brightness(shot).enhance(0.55)

    win = tk.Toplevel(root)
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    win.geometry(f"{w}x{h}{x0:+d}{y0:+d}")
    cv = tk.Canvas(win, width=w, height=h, highlightthickness=0, cursor="crosshair")
    cv.pack()
    bg = ImageTk.PhotoImage(dim)
    cv.create_image(0, 0, image=bg, anchor="nw")
    cv.create_text(w // 2, 40, text="수식 부분을 드래그하세요  (Esc: 취소)",
                   fill="white", font=("Malgun Gothic", 16, "bold"))

    state = {"start": None, "rect": None, "patch": None, "result": None}
    patch_img = {"ref": None}

    def on_down(e):
        state["start"] = (e.x, e.y)

    def on_move(e):
        if not state["start"]:
            return
        sx, sy = state["start"]
        l, t, r, b = min(sx, e.x), min(sy, e.y), max(sx, e.x), max(sy, e.y)
        if state["patch"]:
            cv.delete(state["patch"])
            cv.delete(state["rect"])
        if r - l > 1 and b - t > 1:
            patch_img["ref"] = ImageTk.PhotoImage(shot.crop((l, t, r, b)))  # 선택 부분은 밝게
            state["patch"] = cv.create_image(l, t, image=patch_img["ref"], anchor="nw")
            state["rect"] = cv.create_rectangle(l, t, r, b, outline="#2f80ff", width=2)

    def on_up(e):
        if not state["start"]:
            return
        sx, sy = state["start"]
        l, t, r, b = min(sx, e.x), min(sy, e.y), max(sx, e.x), max(sy, e.y)
        if r - l >= 5 and b - t >= 5:
            state["result"] = shot.crop((l, t, r, b))
        win.destroy()

    def cancel(_=None):
        win.destroy()

    cv.bind("<ButtonPress-1>", on_down)
    cv.bind("<B1-Motion>", on_move)
    cv.bind("<ButtonRelease-1>", on_up)
    cv.bind("<ButtonPress-3>", cancel)
    win.bind("<Escape>", cancel)
    win.focus_force()
    win.grab_set()
    root.wait_window(win)
    return state["result"]
