"""PDF → 한글 파일(.hwpx) 변환 창 (v2.0.6)

PDF 를 고르고 쪽 범위를 정하면 쪽마다 단·문제를 나눠 읽어 원본처럼 2단으로 된 .hwpx 를 만든다.
진행률·남은 시간을 보여 주고, 취소할 수 있다. 인식은 캡처와 같은 인식기를 같이 쓴다(동시에는 하나씩).
"""
from __future__ import annotations

import os
import threading
import time
import tkinter as tk
import traceback
from tkinter import filedialog, messagebox, ttk


class LockedReader:
    """Recognizer 의 지문 인식기를 잠금을 걸고 부름 (변환 중에도 캡처가 섞여 돌 수 있게 문제 하나씩)"""

    def __init__(self, rec):
        self.rec = rec
        self.notes = []

    def __call__(self, img, **kw):
        with self.rec._lock:
            out = self.rec.passage(img, **kw)
            self.notes = list(getattr(self.rec.passage, "notes", []))
            self.last_regions = list(getattr(self.rec.passage, "last_regions", []))
            return out

    def rec_image(self, img):
        with self.rec._lock:
            return self.rec.passage.rec_image(img)

    @property
    def last_em(self):
        return getattr(self.rec.passage, "last_em", None)


class PdfDialog:
    def __init__(self, root: tk.Tk, rec, cfg: dict, on_close=None):
        self.rec, self.cfg, self.on_close = rec, cfg, on_close
        self.cancel = threading.Event()
        self.worker = None
        w = self.win = tk.Toplevel(root)
        w.title("PDF → 한글 파일 변환")
        w.configure(bg="white", padx=16, pady=12)
        w.resizable(False, False)
        f = ("Malgun Gothic", 10)
        tk.Label(w, text="PDF 파일", font=f, bg="white").grid(row=0, column=0, sticky="w")
        self.pdf = tk.StringVar()
        tk.Entry(w, textvariable=self.pdf, width=46, font=f).grid(row=0, column=1, padx=6)
        tk.Button(w, text="찾기…", font=f, command=self._pick).grid(row=0, column=2)
        tk.Label(w, text="쪽 범위", font=f, bg="white").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.pages = tk.StringVar()
        tk.Entry(w, textvariable=self.pages, width=20, font=f).grid(row=1, column=1, sticky="w", padx=6, pady=(6, 0))
        tk.Label(w, text="예: 1-20 (비우면 전체)", font=("Malgun Gothic", 9), bg="white", fg="#666").grid(
            row=1, column=1, sticky="e", pady=(6, 0))
        tk.Label(w, text="저장할 곳", font=f, bg="white").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.out = tk.StringVar()
        tk.Entry(w, textvariable=self.out, width=46, font=f).grid(row=2, column=1, padx=6, pady=(6, 0))
        tk.Button(w, text="바꾸기…", font=f, command=self._pick_out).grid(row=2, column=2, pady=(6, 0))
        self.bar = ttk.Progressbar(w, length=440, mode="determinate", maximum=1000)
        self.bar.grid(row=3, column=0, columnspan=3, pady=(12, 4), sticky="we")
        self.msg = tk.Label(w, text="본인이 쓸 권리가 있는 자료만 변환하세요. 문제마다 몇 초씩 걸립니다.",
                            font=("Malgun Gothic", 9), bg="white", fg="#555", anchor="w", justify="left", wraplength=520)
        self.msg.grid(row=4, column=0, columnspan=3, sticky="we")
        bar = tk.Frame(w, bg="white")
        bar.grid(row=5, column=0, columnspan=3, sticky="e", pady=(10, 0))
        self.go = tk.Button(bar, text="변환 시작", font=f, width=10, command=self._start)
        self.go.pack(side="left")
        self.stop = tk.Button(bar, text="취소", font=f, width=8, command=self._cancel, state="disabled")
        self.stop.pack(side="left", padx=6)
        self.open_btn = tk.Button(bar, text="결과 열기", font=f, width=9, command=self._open, state="disabled")
        self.open_btn.pack(side="left")
        self.review_btn = tk.Button(bar, text="문제 확인", font=f, width=9, command=self._review, state="disabled")
        self.review_btn.pack(side="left", padx=(6, 0))
        tk.Button(w, text="예전 변환 결과 확인…", font=("Malgun Gothic", 9), command=self._open_work).grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.work_dir = None
        w.protocol("WM_DELETE_WINDOW", self._close)
        import dropfiles
        if dropfiles.enable(w, self._dropped):
            self._say("PDF 파일을 이 창에 끌어 놓아도 됩니다. 본인이 쓸 권리가 있는 자료만 변환하세요.")
        w.lift()
        w.focus_force()

    # ------------------------------------------------------------------
    def _pick(self):
        p = filedialog.askopenfilename(parent=self.win, title="PDF 고르기", filetypes=[("PDF", "*.pdf")])
        if p:
            self.set_pdf(p, keep_out=True)

    def set_pdf(self, p, keep_out=False):
        """PDF 를 고름. 저장할 곳은 비어 있거나 keep_out=False 이면 PDF 옆 같은 이름 .hwpx"""
        p = os.path.normpath(p)
        self.pdf.set(p)
        if not keep_out or not self.out.get():
            self.out.set(os.path.splitext(p)[0] + ".hwpx")

    def busy(self):
        return bool(self.worker and self.worker.is_alive())

    def _dropped(self, files):
        import dropfiles
        p = dropfiles.first_pdf(files)
        if self.busy():
            self._say("변환 중에는 파일을 바꿀 수 없습니다.", "#d1242f")
        elif not p:
            self._say("PDF 파일만 끌어 놓을 수 있습니다.", "#d1242f")
        else:
            self.set_pdf(p)
            self._say("PDF 를 골랐습니다. [변환 시작]을 누르세요.")

    def _pick_out(self):
        p = filedialog.asksaveasfilename(parent=self.win, title="저장할 곳", defaultextension=".hwpx",
                                         filetypes=[("한글 문서", "*.hwpx")])
        if p:
            self.out.set(os.path.normpath(p))

    def _say(self, text, color="#555"):
        self.msg.config(text=text, fg=color)

    def _start(self):
        pdf, out = self.pdf.get().strip(), self.out.get().strip()
        if not os.path.isfile(pdf):
            messagebox.showwarning("PDF → 한글", "PDF 파일을 골라 주세요.", parent=self.win)
            return
        if not out:
            out = os.path.splitext(pdf)[0] + ".hwpx"
            self.out.set(out)
        if not out.lower().endswith(".hwpx"):
            out += ".hwpx"
            self.out.set(out)
        if os.path.exists(out) and not messagebox.askyesno("PDF → 한글", f"이미 있는 파일입니다. 덮어쓸까요?\n{out}",
                                                           parent=self.win):
            return
        self.cancel.clear()
        self.go.config(state="disabled")
        self.stop.config(state="normal")
        self.open_btn.config(state="disabled")
        self.review_btn.config(state="disabled")
        self.bar["value"] = 0
        self._say("인식 모델 준비 중…")
        self.t0 = time.time()
        self.worker = threading.Thread(target=self._run, args=(pdf, out, self.pages.get()), daemon=True)
        self.worker.start()

    def _run(self, pdf, out, pages):
        from pdf_convert import Cancelled, convert
        from pdf_work import work_dir_for
        try:
            self.rec.ready.wait()
            if self.rec.error:
                raise RuntimeError(f"인식 모델을 불러오지 못했습니다: {self.rec.error}")
            c = self.cfg
            letters = (bool(c.get("letters_bold", True)), bool(c.get("letters_italic", False))) \
                if c.get("letters_unify", True) else None
            rep = convert(pdf, out, LockedReader(self.rec), pages=pages, dpi=int(c.get("pdf_dpi", 150)),
                          figures=bool(c.get("figures", True)), letters=letters,
                          progress=lambda d, t, m: self.win.after(0, self._progress, d, t, m), cancel=self.cancel,
                          work_dir=work_dir_for(out))
            self.win.after(0, self._done, rep, out)
        except Cancelled:
            self.win.after(0, self._fail, "취소했습니다. 파일은 만들지 않았습니다.")
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self.win.after(0, self._fail, f"변환하지 못했습니다: {e}")

    def _progress(self, done, total, text):
        if not self.win.winfo_exists():
            return
        frac = done / max(1, total)
        self.bar["value"] = int(1000 * frac)
        el = time.time() - self.t0
        left = ""
        if frac > 0.3:  # 인식 단계가 어느 정도 진행돼야 남은 시간이 맞음
            rest = el / frac * (1 - frac)
            left = f" · 남은 시간 약 {int(rest // 60)}분 {int(rest % 60)}초"
        self._say(f"{text} ({int(100 * frac)}%{left})")

    def _done(self, rep, out):
        self.go.config(state="normal")
        self.stop.config(state="disabled")
        self.open_btn.config(state="normal")
        self.bar["value"] = 1000
        self.result = out
        self.work_dir = getattr(rep, "work_dir", None)
        if self.work_dir:
            self.review_btn.config(state="normal")
        self._say("완료: " + rep.text(), "#1a7f37")

    def _fail(self, text):
        if not self.win.winfo_exists():
            return
        self.go.config(state="normal")
        self.stop.config(state="disabled")
        self._say(text, "#d1242f")

    def _cancel(self):
        self.cancel.set()
        self._say("취소하는 중… (지금 문제까지 끝나면 멈춥니다)")

    def _open(self):
        try:
            os.startfile(self.result)  # noqa: S606  한글에서 열기
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("PDF → 한글", f"파일을 열지 못했습니다: {e}", parent=self.win)

    def _review(self, work_dir=None):
        from review_dialog import ReviewDialog
        wd = work_dir or self.work_dir
        if not wd:
            return
        try:
            ReviewDialog(self.win, wd, reader=LockedReader(self.rec), ready=self.rec.ready)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            messagebox.showwarning("문제 확인", f"작업 파일을 열지 못했습니다: {e}", parent=self.win)

    def _open_work(self):
        p = filedialog.askopenfilename(parent=self.win, title="변환할 때 만든 '_작업' 폴더의 work.json 고르기",
                                       filetypes=[("작업 파일", "work.json")])
        if p:
            self._review(os.path.dirname(p))

    def _close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno("PDF → 한글", "변환 중입니다. 취소하고 닫을까요?", parent=self.win):
                return
            self.cancel.set()
        self.win.destroy()
        if self.on_close:
            self.on_close()
