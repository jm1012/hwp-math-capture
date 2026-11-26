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
import time
import tkinter as tk
import traceback
from tkinter import messagebox, ttk

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
        self.btn_box = tk.Button(bar, text="문제 영역 다시 잡기…", font=F, command=self._pick_box)
        self.btn_box.pack(side="left")
        self.btn_reg = tk.Button(bar, text="수식·글·그림 영역 나누기…", font=F, command=self._edit_regions)
        self.btn_reg.pack(side="left", padx=6)

        # 다시 읽는 중 표시 (진행 막대 + 지금 하는 일 + 걸린 시간)
        self.prog_frame = tk.Frame(right, bg="#eef4ff", padx=10, pady=8, highlightthickness=1,
                                   highlightbackground="#9cc0ff")
        self.prog_label = tk.Label(self.prog_frame, text="", font=("Malgun Gothic", 10, "bold"), bg="#eef4ff",
                                   fg="#1f6feb", anchor="w")
        self.prog_label.pack(fill="x")
        self.prog_bar = ttk.Progressbar(self.prog_frame, mode="determinate", maximum=100)
        self.prog_bar.pack(fill="x", pady=(4, 0))
        self.prog = None  # (문제 k, 시작 시각, 비율, 글)

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
        self.reason.config(text=_reason_text(fl))
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
        # 읽지 않은 곳 (어느 영역에도 안 든 잉크): 빨간 상자
        regs = self.work.regions[self.k] if self.k is not None and self.k < len(self.work.regions) else []
        for r in regs:
            if r.get("kind") == "unread":
                x0, y0, x1, y1 = r["box"]
                c.create_rectangle(2 + x0 * s - 3, 2 + y0 * s - 3, 2 + x1 * s + 3, 2 + y1 * s + 3, outline="#d1242f", width=2)

    @staticmethod
    def _set_text(t, s):
        t.config(state="normal")
        t.delete("1.0", "end")
        t.insert("1.0", s)
        t.config(state="disabled")

    def say(self, text, color="#555"):
        self.msg.config(text=text, fg=color)

    # ------------------------------------------------------------------ 다시 읽기
    def _reread(self, scale=1.0, box=None, what=None, regions=None):
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
        for b in (self.btn_hi, self.btn_box, self.btn_reg):
            b.config(state="disabled")
        self._drop()
        self.prog = [k, time.time(), 0.0, "준비하는 중"]
        self._show_prog()
        self.prog_frame.pack(fill="x", pady=(10, 0))
        self.win.config(cursor="watch")
        self.say(f"{self.work.label(k)} 다시 읽는 중…")

        def prog(f, text):
            self.q.put(("prog", k, (f, text)))

        def run():
            try:
                if self.ready is not None:
                    if not self.ready.is_set():
                        prog(0.0, "인식 모델 준비를 기다리는 중")
                    self.ready.wait()
                paras, fl, pim, regs = W.reread(self.work, k, self.reader, box=box, scale=scale, regions=regions,
                                                progress=prog)
                if scale != 1:  # 확인 창의 문제 그림·영역은 변환 해상도 기준
                    pim = pim.resize((round(pim.width / scale), round(pim.height / scale)), Image.LANCZOS)
                # 문제 영역을 새로 잡으면 그림 자리가 바뀌므로 예전 사용자 영역은 버림
                ureg = regions if regions is not None else ([] if box is not None else None)
                self.q.put(("cand", k, (paras, fl, pim, what, regs, ureg)))
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                self.q.put(("err", k, f"다시 읽지 못했습니다: {e}"))

        threading.Thread(target=run, daemon=True).start()

    def _poll(self):
        try:
            while True:
                kind, k, val = self.q.get_nowait()
                if kind == "prog":
                    if self.prog is not None:
                        self.prog[2], self.prog[3] = val
                    continue
                self.busy = False
                self.prog = None
                self.prog_frame.pack_forget()
                self.win.config(cursor="")
                for b in (self.btn_hi, self.btn_box, self.btn_reg):
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
        if self.prog is not None:
            self._show_prog()
        if self.win.winfo_exists():
            self.win.after(100, self._poll)

    def _show_prog(self):
        k, t0, f, text = self.prog
        sec = int(time.time() - t0)
        other = "" if k == self.k else f" ({self.work.label(k)})"
        self.prog_label.config(text=f"다시 읽는 중{other}… {text} · {int(f * 100)}% · {sec}초")
        self.prog_bar["value"] = max(2, int(f * 100))

    def _show_cand(self, cand):
        self.cand = cand
        paras, fl, pim, what = cand[:4]
        self.cand_title.config(text=what)
        self.cand_reason.config(text=_reason_text(fl) if fl else "의심되는 곳 없음",
                                fg="#d1242f" if fl else "#1a7f37")
        self._set_text(self.cand_text, W.preview_text(paras, self.work.probs[self.k].num))
        self.cand_frame.pack(fill="x")

    def _drop(self):
        self.cand = None
        self.cand_frame.pack_forget()

    def _accept(self):
        if not self.cand or self.k is None:
            return
        paras, fl, pim, _, regs, ureg = self.cand
        k = self.k
        try:
            W.replace(self.work, k, paras, fl, regions=regs, user_regions=ureg)
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

    def _edit_regions(self):
        if self.k is None or self.busy or getattr(self, "_crop", None) is None:
            return
        if not os.path.isfile(self.work.pdf):
            self.say(f"원본 PDF 를 찾을 수 없습니다: {self.work.pdf}", "#d1242f")
            return
        k = self.k
        RegionEditor(self.win, self._crop, self.work.label(k), self.work.regions[k] if k < len(self.work.regions) else [],
                     self.work.user_regions[k] if k < len(self.work.user_regions) else [],
                     lambda regs: self._reread(regions=regs, what="정한 영역대로 다시 읽은 결과"))

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


def _reason_text(fl) -> str:
    if not fl:
        return ""
    t = "확인할 점: " + ", ".join(fl)
    if any(f.startswith("읽지 않은 곳") for f in fl):
        t += "  (원본 그림의 빨간 상자. [영역 나누기]에서 그 상자를 눌러 종류를 정하면 다시 읽음)"
    return t


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


KIND = {"math": ("수식", "#1f6feb"), "text": ("글", "#57606a"), "image": ("그림", "#1a7f37")}


class RegionEditor:
    """문제 그림 위에서 수식·글·그림 영역을 정함.
    점선 = AI 가 나눈 영역, 실선 = 사용자가 정한 영역 (다시 읽을 때 이것을 따름).
    종류를 고르고 드래그하면 새 영역. 점선 영역을 클릭하면 그 자리를 고른 종류로 정함. [지우기] 에서 실선을 클릭하면 지움."""

    def __init__(self, parent, crop, title, ai_regions, user_regions, on_ok):
        self.on_ok = on_ok
        self.ai = [dict(r) for r in ai_regions]
        self.user = [dict(r) for r in user_regions]
        w = self.win = tk.Toplevel(parent)
        w.title(f"영역 나누기 — {title}")
        w.configure(bg="white", padx=8, pady=8)
        w.transient(parent)
        sw, sh = w.winfo_screenwidth(), w.winfo_screenheight()
        self.s = min(2.0, (sw - 120) / crop.width, (sh - 260) / crop.height)
        im = crop.resize((max(1, int(crop.width * self.s)), max(1, int(crop.height * self.s))), Image.LANCZOS)
        self._img = ImageTk.PhotoImage(im)
        top = tk.Frame(w, bg="white")
        top.pack(fill="x")
        self.mode = tk.StringVar(value="image")
        for key, text in (("math", "수식"), ("text", "글"), ("image", "그림"), ("erase", "지우기")):
            color = KIND[key][1] if key in KIND else "#d1242f"
            tk.Radiobutton(top, text=text, value=key, variable=self.mode, font=F, bg="white", fg=color,
                           selectcolor="white", indicatoron=False, width=6).pack(side="left", padx=2)
        tk.Label(top, text="  종류를 고르고 드래그 → 새 영역 · 점선 클릭 → 그 영역을 고른 종류로 · [지우기]로 실선 클릭 → 지움",
                 font=FS, bg="white", fg="#555").pack(side="left")
        c = self.c = tk.Canvas(w, width=im.width, height=im.height, highlightthickness=0, cursor="crosshair")
        c.pack(pady=(6, 0))
        c.create_image(0, 0, image=self._img, anchor="nw")
        c.bind("<ButtonPress-1>", self._down)
        c.bind("<B1-Motion>", self._move)
        c.bind("<ButtonRelease-1>", self._up)
        bar = tk.Frame(w, bg="white")
        bar.pack(fill="x", pady=(6, 0))
        self.info = tk.Label(bar, text="", font=FS, bg="white", fg="#555")
        self.info.pack(side="left")
        tk.Button(bar, text="정한 영역대로 다시 읽기", font=F, command=self._ok).pack(side="right")
        tk.Button(bar, text="취소", font=F, command=w.destroy).pack(side="right", padx=6)
        tk.Button(bar, text="내 영역 모두 지우기", font=F, command=self._clear).pack(side="right")
        self.drag = None
        self._draw()
        w.grab_set()

    def _draw(self):
        c = self.c
        c.delete("reg")
        for r in self.ai:
            if any(_iou(r["box"], u["box"]) > 0.5 for u in self.user):
                continue
            if r["kind"] == "unread":  # 읽지 않은 곳: 빨간 상자 (누르면 고른 종류로 정함)
                x0, y0, x1, y1 = (v * self.s for v in r["box"])
                c.create_rectangle(x0 - 3, y0 - 3, x1 + 3, y1 + 3, outline="#d1242f", width=2, tags="reg")
                continue
            name, col = KIND.get(r["kind"], ("?", "#999"))
            c.create_rectangle(*[v * self.s for v in r["box"]], outline=col, width=1, dash=(4, 3), tags="reg")
        for r in self.user:
            name, col = KIND[r["kind"]]
            x0, y0 = r["box"][0] * self.s, r["box"][1] * self.s
            c.create_rectangle(*[v * self.s for v in r["box"]], outline=col, width=3, tags="reg")
            c.create_text(x0 + 3, y0 + 2, text=name, anchor="nw", fill=col, font=("Malgun Gothic", 9, "bold"), tags="reg")
        n = {k: sum(r["kind"] == k for r in self.user) for k in KIND}
        self.info.config(text="내가 정한 영역: " + ", ".join(f"{KIND[k][0]} {v}개" for k, v in n.items() if v) if self.user
                         else "내가 정한 영역 없음 (정하지 않은 곳은 자동)")

    def _down(self, e):
        self.drag = (e.x, e.y)
        self.c.delete("drag")

    def _move(self, e):
        if not self.drag or self.mode.get() == "erase":
            return
        self.c.delete("drag")
        col = KIND[self.mode.get()][1]
        self.c.create_rectangle(self.drag[0], self.drag[1], e.x, e.y, outline=col, width=2, tags="drag")

    def _up(self, e):
        if not self.drag:
            return
        x0, y0 = self.drag
        self.drag = None
        self.c.delete("drag")
        px, py = e.x / self.s, e.y / self.s
        mode = self.mode.get()
        if abs(e.x - x0) < 6 and abs(e.y - y0) < 6:  # 클릭
            hit = lambda r: r["box"][0] <= px <= r["box"][2] and r["box"][1] <= py <= r["box"][3]  # noqa: E731
            if mode == "erase":
                self.user = [r for r in self.user if not hit(r)]
            else:
                cand = sorted((r for r in self.user + self.ai if hit(r)), key=lambda r: _area(r["box"]))
                if cand:
                    b = list(cand[0]["box"])
                    self.user = [r for r in self.user if _iou(r["box"], b) <= 0.5] + [{"box": b, "kind": mode}]
            self._draw()
            return
        if mode == "erase":
            return
        b = [min(x0, e.x) / self.s, min(y0, e.y) / self.s, max(x0, e.x) / self.s, max(y0, e.y) / self.s]
        self.user.append({"box": [round(v, 1) for v in b], "kind": mode})
        self._draw()

    def _clear(self):
        self.user = []
        self._draw()

    def _ok(self):
        regs = [dict(r) for r in self.user]
        self.win.destroy()
        self.on_ok(regs)


def _area(b):
    return max(0, b[2] - b[0]) * max(0, b[3] - b[1])


def _iou(a, b):
    i = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return i / max(1e-6, _area(a) + _area(b) - i)
