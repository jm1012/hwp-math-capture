"""문제 확인 창 화면 시험 (Windows, 사람 손 없이). 변환할 때 만든 작업 폴더가 있어야 함.
python test_review_gui.py <작업 폴더> [화면 저장 폴더]
  1) 창을 열고 첫 문제(확인할 문제가 있으면 그것)를 고름        → 1_select.png
  2) 해상도 2배로 다시 읽기 → 새 결과가 나옴                    → 2_hires.png
  3) 영역 다시 잡기 창(원래 자리) → 위쪽 절반만 잡아 다시 읽기  → 3_picker.png, 4_box.png
  4) 새 결과를 한글로 복사 → 클립보드에 한글 형식이 들어갔는지
  5) 이 결과로 바꾸기 → 한글 파일을 임시 이름으로 다시 저장        → 5_accept.png
원래 작업 폴더는 건드리지 않도록 복사본으로 시험한다.
"""
import os
import shutil
import sys
import tempfile
import time
import tkinter as tk

from PIL import ImageGrab

import pdf_work as W
from pdf_dialog import LockedReader
from recognizer import Recognizer
from review_dialog import BoxPicker, ReviewDialog

src = sys.argv[1]
shots = sys.argv[2] if len(sys.argv) > 2 else os.path.join(tempfile.gettempdir(), "review_shots")
os.makedirs(shots, exist_ok=True)
tmp = tempfile.mkdtemp()
wd = os.path.join(tmp, "t_작업")
shutil.copytree(src, wd)
w0 = W.load(wd)
w0.out = os.path.join(tmp, "t.hwpx")
W.save(w0)

rec = Recognizer()
rec._load()
root = tk.Tk()
root.withdraw()
dlg = ReviewDialog(root, wd, reader=LockedReader(rec), ready=rec.ready)
log = []


def shot(name):
    dlg.win.update()
    for t in list(dlg.win.children.values()):
        if isinstance(t, tk.Toplevel):
            t.update()
    x, y = dlg.win.winfo_rootx(), dlg.win.winfo_rooty()
    ww, hh = dlg.win.winfo_width(), dlg.win.winfo_height()
    ImageGrab.grab(bbox=(x, y, x + ww, y + hh), all_screens=True).save(os.path.join(shots, name))
    log.append(name)


def wait_cand(then, t0=None):
    t0 = t0 or time.time()
    if dlg.cand is not None:
        then()
    elif time.time() - t0 > 120:
        print("FAIL: 120초 안에 새 결과가 안 나옴", dlg.msg.cget("text"))
        root.quit()
    else:
        root.after(300, wait_cand, then, t0)


def step1():
    flagged = [i for i, k in enumerate(dlg.rows) if dlg.work.flags[k]]
    i = flagged[0] if flagged else 0
    dlg.lb.selection_clear(0, "end")
    dlg.lb.selection_set(i)
    dlg._select()
    print("골랐음:", dlg.work.label(dlg.k), dlg.work.flags[dlg.k])
    print("결과:", dlg.cur.get("1.0", "end")[:200].replace("\n", " / "))
    shot("1_select.png")
    dlg._reread(scale=2.0)
    wait_cand(step2)


def step2():
    print("2배:", dlg.cand_text.get("1.0", "end")[:200].replace("\n", " / "), dlg.cand[1])
    shot("2_hires.png")
    dlg._drop()
    p = dlg.work.probs[dlg.k]
    picker = BoxPicker(dlg.win, dlg.work, dlg.k, lambda box: dlg._reread(box=box, what="새 영역으로 다시 읽은 결과"))
    picker.win.update()
    x, y = picker.win.winfo_rootx(), picker.win.winfo_rooty()
    ImageGrab.grab(bbox=(x, y, x + picker.win.winfo_width(), y + picker.win.winfo_height()), all_screens=True).save(
        os.path.join(shots, "3_picker.png"))
    b = p.box
    s = picker.s
    picker.c.coords(picker.rect, b[0] * s, b[1] * s, b[2] * s, (b[1] + (b[3] - b[1]) / 2) * s)
    picker._ok()
    wait_cand(step3)


def step3():
    print("영역:", dlg.cand_text.get("1.0", "end")[:200].replace("\n", " / "), dlg.cand[1])
    shot("4_box.png")
    dlg._copy(True)
    print("복사:", dlg.msg.cget("text"))
    try:
        import win32clipboard as cb
        cb.OpenClipboard()
        fmts = []
        f = 0
        while True:
            f = cb.EnumClipboardFormats(f)
            if not f:
                break
            try:
                fmts.append(cb.GetClipboardFormatName(f))
            except Exception:  # noqa: BLE001
                fmts.append(str(f))
        cb.CloseClipboard()
        print("클립보드 형식:", fmts)
    except Exception as e:  # noqa: BLE001
        print("클립보드 확인 못 함:", e)
    k = dlg.k
    dlg._accept()
    v = W.load(wd)
    print("바꾼 문제 저장됨:", v.edited[k])
    from tkinter import messagebox
    messagebox.askyesno = lambda *a, **kw: True
    dlg._rebuild()
    print("다시 저장:", dlg.msg.cget("text"), os.path.exists(w0.out))
    shot("5_accept.png")
    print("PASS" if v.edited[k] and os.path.exists(w0.out) else "FAIL")
    print("화면:", shots, log)
    root.after(500, root.quit)


root.after(1500, step1)
root.mainloop()
