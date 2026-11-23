"""PDF 변환 문제 확인 창 (v2.0.7)

변환 뒤 남긴 작업 폴더(pdf_work)를 열어
  - 문제 목록에서 확인할 문제(⚠)를 고르고
  - 원본 문제 그림과 인식 결과를 나란히 보고
  - 해상도를 두 배로 하거나 영역을 다시 잡아 다시 읽은 후보와 비교해
  - 그 문제만 한글로 복사(Ctrl+V)하거나, 결과를 바꿔 한글 파일을 다시 저장한다.
인식은 백그라운드 스레드에서 하고, 결과는 큐로 받아 tkinter 스레드에서 그린다.
"""
from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
import traceback
from tkinter import messagebox

from PIL import Image, ImageTk

import pdf_work as W

F = ("Malgun Gothic", 10)
FS = ("Malgun Gothic", 9)


class ReviewDialog:
    def __init__(self, root, work_dir: str, reader=None, ready=None):
        """reader: 인식기 (pdf_dialog.LockedReader). ready: 인식 모델 준비 Event (없으면 바로 씀)"""
        self.work = W.load(work_dir)
        self.reader, self.ready = reader, ready
        self.q = queue.Queue()
        self.busy = False
        self.k = None
        self.cand = None   # (문단들, 의심 이유, 문제 그림, 설명)
        self._img = None

        w = self.win = tk.Toplevel(root)
        w.title("문제 확인 — " + os.path.basename(self.work.pdf))
        w.configure(bg="white", padx=12, pady=10)
        w.geometry("1120x760")
        w.minsize(900, 600)

        top = tk.Frame(w, bg="white")
        top.pack(fill="x")
        self.only = tk.BooleanVar(value=False)
        tk.Checkbutton(top, text="확인할 문제(⚠)만 보기", variable=self.only, bg="white", font=F,
                       command=self._fill).pack(side="left")
        tk.Button(top, text="한글 파일 다시 저장", font=F, command=self._rebuild).pack(side="right")
        self.summary = tk.Label(top, text="", bg="white", font=FS, fg="#555")
        self.summary.pack(side="left", padx=12)

        body = tk.Frame(w, bg="white")
        body.pack(fill="both", expand=True, pady=(8, 0))
        left = tk.Frame(body, bg="white")
        left.pack(side="left", fill="y")
        self.lb = tk.Listbox(left, width=34, font=F, activestyle="none", exportselection=False)
        sb = tk.Scrollbar(left, command=self.lb.yview)
        self.lb.config(yscrollcommand=sb.set)
        self.lb.pack(side="left", fill="y")
        sb.pack(side="left", fill="y")
        self.lb.bind("<<ListboxSelect>>", lambda e: self._select())

        right = tk.Frame(body, bg="white", padx=12)
        right.pack(side="left", fill="both", expand=True)
        tk.Label(right, text="원본", font=("Malgun Gothic", 10, "bold"), bg="white", anchor="w").pack(fill="x")
        self.canvas = tk.Canvas(right, bg="#f6f8fa", height=300, highlightthickness=1, highlightbackground="#ddd")
        self.canvas.pack(fill="x")
        self.canvas.bind("<Configure>", lambda e: self._draw_crop())
        self.reason = tk.Label(right, text="", font=FS, bg="white", fg="#d1242f", anchor="w", justify="left",
                               wraplength=740)
        self.reason.pack(fill="x", pady=(4, 0))
        tk.Label(right, text="인식 결과  (〔 〕 안은 한글 수식)", font=("Malgun Gothic", 10, "bold"), bg="white",
                 anchor="w").pack(fill="x", pady=(6, 0))
        self.cur = tk.Text(right, height=7, font=F, wrap="word", relief="solid", bd=1)
        self.cur.pack(fill="x")
        bar = tk.Frame(right, bg="white")
        bar.pack(fill="x", pady=(6, 0))
        self.btn_copy = tk.Button(bar, text="이 문제 한글로 복사", font=F, command=lambda: self._copy(False))
        self.btn_copy.pack(side="left")
        self.btn_hi = tk.Button(bar, text="해상도 2배로 다시 읽기", font=F, command=lambda: self._reread(scale=2.0))
        self.btn_hi.pack(side="left", padx=6)
        self.btn_box = tk.Button(bar, text="영역 다시 잡기…", font=F, command=self._pick_box)
        self.btn_box.pack(side="left")

        self.cand_frame = tk.Frame(right, bg="white")
        self.cand_title = tk.Label(self.cand_frame, text="새 결과", font=("Malgun Gothic", 10, "bold"), bg="white",
                                   fg="#1f6feb", anchor="w")
        self.cand_title.pack(fill="x", pady=(10, 0))
        self.cand_reason = tk.Label(self.cand_frame, text="", font=FS, bg="white", fg="#d1242f", anchor="w")
        self.cand_reason.pack(fill="x")
        self.cand_text = tk.Text(self.cand_frame, height=7, font=F, wrap="word", relief="solid", bd=1)
        self.cand_text.pack(fill="x")
        cb = tk.Frame(self.cand_frame, bg="white")
        cb.pack(fill="x", pady=(6, 0))
        tk.Button(cb, text="이 결과로 바꾸기", font=F, command=self._accept).pack(side="left")
        tk.Button(cb, text="새 결과를 한글로 복사", font=F, command=lambda: self._copy(True)).pack(side="left", padx=6)
        tk.Button(cb, text="버리기", font=F, command=self._drop).pack(side="left")

        self.msg = tk.Label(w, text="", font=FS, bg="white", fg="#555", anchor="w", justify="left", wraplength=1080)
        self.msg.pack(fill="x", pady=(8, 0))

        self.rows = []
        self._fill()
        if self.rows:
            self.lb.selection_set(0)
            self._select()
        w.after(100, self._poll)
        w.lift()
        w.focus_force()

    # ------------------------------------------------------------------ 목록
    def _row_text(self, k):
        mark = "✎ " if self.work.edited[k] else ("⚠ " if self.work.flags[k] else "   ")
        return mark + self.work.label(k)

    def _fill(self):
        keep = self.k
        n_flag = sum(1 for f in self.work.flags if f)
        self.summary.config(text=f"문제 {sum(p.kind == 'problem' for p in self.work.probs)}개 중 확인할 문제 {n_flag}개")
        self.rows = [k for k, p in enumerate(self.work.probs) if p.kind == "problem"
                     and (not self.only.get() or self.work.flags[k] or self.work.edited[k])]
        self.lb.delete(0, "end")
        for k in self.rows:
            self.lb.insert("end", self._row_text(k))
            if self.work.flags[k]:
                self.lb.itemconfig("end", fg="#9a3412")
        if keep in self.rows:
            i = self.rows.index(keep)
            self.lb.selection_set(i)
            self.lb.see(i)

    def _select(self):
        sel = self.lb.curselection()
        if not sel:
            return
        k = self.rows[sel[0]]
        if k == self.k:
            return
        self.k = k
        self._drop()
        self._show_current()

    def _show_current(self):
        k = self.k
        p = self.work.probs[k]
        self._set_text(self.cur, W.preview_text(self.work.results[k], p.num))
        fl = self.work.flags[k]
        self.reason.config(text=("확인할 점: " + ", ".join(fl)) if fl else "")
        try:
            with Image.open(W.crop_path(self.work, k)) as im:
                self._crop = im.convert("RGB")
        except OSError:
            self._crop = None
        self._draw_crop()

    def _draw_crop(self):
        c = self.canvas
        c.delete("all")
        im = getattr(self, "_crop", None)
        if im is None:
            return
        cw, ch = max(50, c.winfo_width() - 4), max(50, c.winfo_height() - 4)
        s = min(cw / im.width, ch / im.height, 2.0)
        self._img = ImageTk.PhotoImage(im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS))
        c.create_image(2, 2, image=self._img, anchor="nw")

    @staticmethod
    def _set_text(t, s):
        t.config(state="normal")
        t.delete("1.0", "end")
        t.insert("1.0", s)
        t.config(state="disabled")

    def say(self, text, color="#555"):
        self.msg.config(text=text, fg=color)

    # ------------------------------------------------------------------ 다시 읽기
    def _reread(self, scale=1.0, box=None, what=None):
        if self.k is None or self.busy:
            return
        if self.reader is None:
            self.say("인식기가 없어 다시 읽을 수 없습니다.", "#d1242f")
            return
        if not os.path.isfile(self.work.pdf):
            self.say(f"원본 PDF 를 찾을 수 없습니다: {self.work.pdf}", "#d1242f")
            return
        k = self.k
        what = what or ("해상도 2배로 다시 읽은 결과" if scale != 1 else "다시 읽은 결과")
        self.busy = True
        for b in (self.btn_hi, self.btn_box):
            b.config(state="disabled")
        self.say(f"{self.work.label(k)} 다시 읽는 중…")

        def run():
            try:
                if self.ready is not None:
                    self.ready.wait()
                paras, fl, pim = W.reread(self.work, k, self.reader, box=box, scale=scale)
                self.q.put(("cand", k, (paras, fl, pim, what)))
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                self.q.put(("err", k, f"다시 읽지 못했습니다: {e}"))

        threading.Thread(target=run, daemon=True).start()

    def _poll(self):
        try:
            while True:
                kind, k, val = self.q.get_nowait()
                self.busy = False
                for b in (self.btn_hi, self.btn_box):
                    b.config(state="normal")
                if kind == "err":
                    self.say(val, "#d1242f")
                elif k == self.k:
                    self._show_cand(val)
                    self.say("새 결과가 나왔습니다. 원본과 비교해 보세요.")
                else:
                    self.say(f"{self.work.label(k)} 새 결과는 다른 문제를 골라서 버렸습니다.")
        except queue.Empty:
            pass
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        if self.win.winfo_exists():
            self.win.after(100, self._poll)

    def _show_cand(self, cand):
        self.cand = cand
        paras, fl, pim, what = cand
        self.cand_title.config(text=what)
        self.cand_reason.config(text=("확인할 점: " + ", ".join(fl)) if fl else "의심되는 곳 없음",
                                fg="#d1242f" if fl else "#1a7f37")
        self._set_text(self.cand_text, W.preview_text(paras, self.work.probs[self.k].num))
        self.cand_frame.pack(fill="x")

    def _drop(self):
        self.cand = None
        self.cand_frame.pack_forget()

    def _accept(self):
        if not self.cand or self.k is None:
            return
        paras, fl, pim, _ = self.cand
        k = self.k
        try:
            W.replace(self.work, k, paras, fl)
            pim.save(W.crop_path(self.work, k))
        except OSError as e:
            self.say(f"작업 파일을 저장하지 못했습니다: {e}", "#d1242f")
            return
        self._drop()
        self._show_current()
        self._fill()
        self.say(f"{self.work.label(k)} 결과를 바꿨습니다. [한글 파일 다시 저장]을 누르면 한글 파일에 들어갑니다. "
                 "이미 한글에서 고친 파일이면 [이 문제 한글로 복사] 후 그 자리에 붙여 넣으세요.", "#1a7f37")

    # ------------------------------------------------------------------ 영역 다시 잡기
    def _pick_box(self):
        if self.k is None or self.busy:
            return
        if not os.path.isfile(self.work.pdf):
            self.say(f"원본 PDF 를 찾을 수 없습니다: {self.work.pdf}", "#d1242f")
            return
        BoxPicker(self.win, self.work, self.k, lambda box: self._reread(box=box, what="새 영역으로 다시 읽은 결과"))

    # ------------------------------------------------------------------ 복사·저장
    def _copy(self, cand: bool):
        if self.k is None:
            return
        paras = self.cand[0] if cand and self.cand else None
        try:
            from hwp_clipboard import set_passage_clipboard
            from passage import to_markdown
            hwp = W.problem_hwp(self.work, self.k, paras, W.body_pt(self.work))
            set_passage_clipboard(hwp, plain_text=to_markdown(paras or self.work.results[self.k] or []))
            self.say(f"{self.work.label(self.k)} 복사됨 — 한글에서 그 문제를 지우고 Ctrl+V 하세요.", "#1a7f37")
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self.say(f"복사하지 못했습니다: {e}", "#d1242f")

    def _rebuild(self):
        out = self.work.out
        if os.path.exists(out) and not messagebox.askyesno(
                "문제 확인", f"한글 파일을 다시 저장합니다.\n{out}\n\n한글에서 직접 고친 내용이 있으면 사라집니다. 계속할까요?",
                parent=self.win):
            return
        try:
            counts = W.rebuild(self.work)
        except PermissionError:
            self.say("저장하지 못했습니다. 한글에서 그 파일을 닫고 다시 눌러 주세요.", "#d1242f")
            return
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self.say(f"저장하지 못했습니다: {e}", "#d1242f")
            return
        self.say(f"다시 저장했습니다: {out} (문단 {counts.get('paragraphs', 0)}개, 수식 {counts.get('equations', 0)}개)",
                 "#1a7f37")


class BoxPicker:
    """쪽 그림 위에서 영역을 드래그로 다시 잡음. 지금 영역은 파란 상자, 새 영역은 빨간 상자."""

    def __init__(self, parent, work, k, on_box):
        self.work, self.k, self.on_box = work, k, on_box
        p = work.probs[k]
        self.page = W.page_image(work, p.page)
        w = self.win = tk.Toplevel(parent)
        w.title(f"영역 다시 잡기 — {work.label(k)}")
        w.configure(bg="white", padx=8, pady=8)
        w.transient(parent)
        sh = w.winfo_screenheight()
        self.s = min(1.0, (sh - 200) / self.page.height)
        im = self.page.resize((int(self.page.width * self.s), int(self.page.height * self.s)), Image.LANCZOS)
        self._img = ImageTk.PhotoImage(im)
        tk.Label(w, text="문제 영역을 마우스로 끌어서 잡으세요. 번호와 선지까지 넉넉하게 잡는 것이 좋습니다.",
                 font=FS, bg="white", fg="#555").pack(fill="x")
        c = self.c = tk.Canvas(w, width=im.width, height=im.height, highlightthickness=0, cursor="crosshair")
        c.pack()
        c.create_image(0, 0, image=self._img, anchor="nw")
        for b in p.blocks:
            c.create_rectangle(*[v * self.s for v in b.box], outline="#1f6feb", width=1, dash=(3, 2))
        bx = p.box
        self.rect = c.create_rectangle(*[v * self.s for v in bx], outline="#d1242f", width=2)
        self.box = list(bx)
        c.bind("<ButtonPress-1>", self._down)
        c.bind("<B1-Motion>", self._move)
        bar = tk.Frame(w, bg="white")
        bar.pack(fill="x", pady=(6, 0))
        tk.Button(bar, text="이 영역으로 다시 읽기", font=F, command=self._ok).pack(side="right")
        tk.Button(bar, text="취소", font=F, command=w.destroy).pack(side="right", padx=6)
        w.grab_set()

    def _down(self, e):
        self.x0, self.y0 = e.x, e.y
        self.c.coords(self.rect, e.x, e.y, e.x, e.y)

    def _move(self, e):
        self.c.coords(self.rect, self.x0, self.y0, e.x, e.y)

    def _ok(self):
        x0, y0, x1, y1 = self.c.coords(self.rect)
        box = [int(min(x0, x1) / self.s), int(min(y0, y1) / self.s), int(max(x0, x1) / self.s), int(max(y0, y1) / self.s)]
        if box[2] - box[0] < 10 or box[3] - box[1] < 10:
            return
        self.win.destroy()
        self.on_box(box)
