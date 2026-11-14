"""수식 캡처 → 한글 수식 붙여넣기 도구

사용법
  1. 이 프로그램을 실행해 둔다 (작업 표시줄 오른쪽 아래 트레이에 아이콘이 생김).
  2. 수식 하나: Ctrl+Shift+Q / 글자+수식 지문: Ctrl+Alt+J 를 누르면 화면이 어두워진다. 영역을 드래그한다.
  3. 잠시 후 "복사됨" 알림이 뜨면 한글에서 Ctrl+V. 글자는 글자로, 수식은 수식 개체로 붙는다.
     (다른 프로그램에 붙이면 수식이 LaTeX 글자로 붙는다)
"""
from __future__ import annotations

import ctypes
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
import traceback

HERE = os.path.dirname(os.path.abspath(sys.argv[0]))
CONFIG_PATH = os.path.join(HERE, "config.json")
LOG_PATH = os.path.join(HERE, "history.log")
if sys.stderr is None or sys.stdout is None:  # pythonw 로 실행하면 콘솔이 없음
    sys.stdout = sys.stderr = open(os.path.join(HERE, "error.log"), "a", encoding="utf-8", buffering=1)
DEFAULT_CONFIG = {"hotkey": "ctrl+shift+q", "passage_hotkey": "ctrl+alt+j", "font_pt": 11}
MODES = {  # 모드: (설정 키, 이름)
    "formula": ("hotkey", "수식"),
    "passage": ("passage_hotkey", "지문"),
}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except FileNotFoundError:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return cfg

def make_icon():
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (31, 111, 235, 255))
    d = ImageDraw.Draw(img)
    d.rectangle((14, 14, 50, 50), outline="white", width=4)
    d.line((22, 40, 32, 24, 42, 40), fill="white", width=4)
    return img


def already_running() -> bool:
    """같은 프로그램이 이미 켜져 있으면 True (이름 있는 뮤텍스로 확인)."""
    global _MUTEX
    _MUTEX = ctypes.windll.kernel32.CreateMutexW(None, False, "FormulaCapture.SingleInstance")
    return ctypes.windll.kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS


class Toast:
    """오른쪽 아래에 잠깐 뜨는 알림 창."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.win = None
        self.job = None

    def show(self, title: str, body: str = "", ms: int = 3500, color="#1f6feb"):
        if self.win is None or not self.win.winfo_exists():
            self.win = tk.Toplevel(self.root)
            self.win.overrideredirect(True)
            self.win.attributes("-topmost", True)
            self.frame = tk.Frame(self.win, bg="white", highlightthickness=2)
            self.frame.pack(fill="both", expand=True)
            self.t = tk.Label(self.frame, font=("Malgun Gothic", 11, "bold"), bg="white", anchor="w")
            self.t.pack(fill="x", padx=12, pady=(10, 2))
            self.b = tk.Label(self.frame, font=("Consolas", 10), bg="white", fg="#333",
                              anchor="w", justify="left", wraplength=420)
            self.b.pack(fill="x", padx=12, pady=(0, 10))
        self.frame.config(highlightbackground=color)
        self.t.config(text=title, fg=color)
        self.b.config(text=body)
        self.win.update_idletasks()
        w, h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.win.geometry(f"{max(w, 300)}x{h}+{sw - max(w, 300) - 24}+{sh - h - 72}")
        self.win.deiconify()
        if self.job:
            self.root.after_cancel(self.job)
        self.job = self.root.after(ms, self.win.withdraw) if ms else None


class App:
    def __init__(self):
        from overlay import enable_dpi_awareness
        enable_dpi_awareness()
        self.cfg = load_config()
        try:  # 작업 표시줄에서 python 이 아니라 이 프로그램으로 보이게
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FormulaCapture.App")
        except Exception:
            pass
        self.root = tk.Tk()
        self._build_window()
        self.toast = Toast(self.root)
        self.events: queue.Queue[str] = queue.Queue()
        self.busy = False

        from recognizer import Recognizer
        self.rec = Recognizer()
        self.rec.load_async()
        self.toast.show("수식 캡처 준비 중…", "인식 모델을 불러오는 중입니다.", ms=0)
        threading.Thread(target=self._wait_ready, daemon=True).start()

        from hotkey import HotkeyManager, validate
        self.hotkeys = {}
        for mode, (key, _name) in MODES.items():
            if validate(self.cfg[key]):
                self.cfg[key] = DEFAULT_CONFIG[key]
            self.hotkeys[mode] = HotkeyManager(self.cfg[key], lambda m=mode: self.events.put(("capture", m)))
            if not self.hotkeys[mode].first_result:
                self.events.put(("hotkey_fail", mode))
        self._start_tray()
        self.root.after(100, self._poll)

    # ------------------------------------------------------------------
    def _build_window(self):
        """작업 표시줄에 보이는 작은 제어 창. 닫으면 프로그램이 끝난다."""
        r = self.root
        r.title("수식 캡처")
        r.resizable(False, False)
        r.configure(bg="white", padx=18, pady=14)
        try:
            from PIL import ImageTk
            self._icon = ImageTk.PhotoImage(make_icon())
            r.iconphoto(True, self._icon)
        except Exception:
            pass
        f = ("Malgun Gothic", 10)
        self.status_lbl = tk.Label(r, text="● 인식 모델 불러오는 중…", font=("Malgun Gothic", 11, "bold"),
                                   bg="white", fg="#9a6700", anchor="w")
        self.status_lbl.pack(fill="x")
        self.hk_lbl = tk.Label(r, text="", font=f, bg="white", fg="#333", anchor="w")
        self.hk_lbl.pack(fill="x", pady=(6, 2))
        tk.Label(r, text="영역을 드래그한 뒤 한글에서 Ctrl+V 하세요.\n"
                         "지문 캡처는 글자는 글자로, 수식은 수식 개체로 붙여 줍니다.\n"
                         "창을 닫거나 [종료]를 누르면 프로그램이 끝납니다.",
                 font=("Malgun Gothic", 9), bg="white", fg="#666", justify="left", anchor="w").pack(fill="x", pady=(0, 10))
        bar = tk.Frame(r, bg="white")
        bar.pack(fill="x")
        tk.Button(bar, text="수식 캡처", font=f, width=9,
                  command=lambda: self.events.put(("capture", "formula"))).pack(side="left")
        tk.Button(bar, text="지문 캡처", font=f, width=9,
                  command=lambda: self.events.put(("capture", "passage"))).pack(side="left", padx=(6, 0))
        tk.Button(bar, text="종료", font=f, width=7, command=lambda: self.events.put("quit")).pack(side="right")
        bar2 = tk.Frame(r, bg="white")
        bar2.pack(fill="x", pady=(6, 0))
        tk.Button(bar2, text="수식 단축키 변경", font=("Malgun Gothic", 9),
                  command=lambda: self.events.put(("hotkey_dialog", "formula"))).pack(side="left")
        tk.Button(bar2, text="지문 단축키 변경", font=("Malgun Gothic", 9),
                  command=lambda: self.events.put(("hotkey_dialog", "passage"))).pack(side="left", padx=6)
        r.protocol("WM_DELETE_WINDOW", lambda: self.events.put("quit"))
        self._refresh_hotkey_label()
        r.update_idletasks()
        w, h = r.winfo_reqwidth(), r.winfo_reqheight()
        sw, sh = r.winfo_screenwidth(), r.winfo_screenheight()
        r.geometry(f"{w}x{h}+{sw - w - 40}+{sh - h - 120}")
        # 한 번 그린 뒤(보이지 않게) 최소화해야 복원했을 때 내용이 제대로 나온다
        r.attributes("-alpha", 0.0)
        r.deiconify()
        r.update()
        r.iconify()  # 작업 표시줄 버튼으로 시작
        r.attributes("-alpha", 1.0)

    def _refresh_hotkey_label(self):
        if hasattr(self, "hk_lbl"):
            self.hk_lbl.config(text=f"수식 캡처: {self._hk('formula')}    지문 캡처: {self._hk('passage')}")

    def _set_status(self, text, color):
        self.status_lbl.config(text=f"● {text}", fg=color)

    def _wait_ready(self):
        self.rec.ready.wait()
        if self.rec.error:
            self.events.put("load_fail")
        else:
            self.events.put("ready")

    def _start_tray(self):
        try:
            import pystray
            from hotkey import pretty
            from PIL import Image, ImageDraw
            img = make_icon()
            menu = pystray.Menu(
                pystray.MenuItem(lambda item: f"수식 캡처 ({pretty(self.cfg['hotkey'])})",
                                 lambda: self.events.put(("capture", "formula")), default=True),
                pystray.MenuItem(lambda item: f"지문 캡처 ({pretty(self.cfg['passage_hotkey'])})",
                                 lambda: self.events.put(("capture", "passage"))),
                pystray.MenuItem("수식 단축키 변경…", lambda: self.events.put(("hotkey_dialog", "formula"))),
                pystray.MenuItem("지문 단축키 변경…", lambda: self.events.put(("hotkey_dialog", "passage"))),
                pystray.MenuItem("종료", lambda: self.events.put("quit")),
            )
            self.tray = pystray.Icon("formula_capture", img, "수식 캡처", menu)
            threading.Thread(target=self.tray.run, daemon=True).start()
        except Exception:
            self.tray = None

    def _poll(self):
        try:
            while True:
                ev = self.events.get_nowait()
                kind = ev[0] if isinstance(ev, tuple) else ev
                if kind == "capture":
                    if not self.busy:
                        self.capture(ev[1])
                elif kind == "hotkey_dialog":
                    self.open_hotkey_dialog(ev[1])
                elif ev == "ready":
                    self._set_status("준비 완료", "#1a7f37")
                    self.toast.show("수식 캡처 준비 완료",
                                    f"수식 하나: {self._hk('formula')}   글자+수식 지문: {self._hk('passage')}\n"
                                    "단축키는 작업 표시줄의 '수식 캡처' 창에서 바꿀 수 있어요.")
                elif ev == "load_fail":
                    self._set_status("인식 모델 오류", "#d1242f")
                    self.toast.show("인식 모델 오류", str(self.rec.error), ms=0, color="#d1242f")
                elif kind == "hotkey_fail":
                    mode = ev[1]
                    self.toast.show("단축키 등록 실패",
                                    f"{MODES[mode][1]} 캡처 단축키 {self._hk(mode)} 를 다른 프로그램이 쓰고 있어요.\n"
                                    "다른 키를 골라 주세요.",
                                    ms=0, color="#d1242f")
                    self.open_hotkey_dialog(mode)
                elif ev == "quit":
                    if self.tray:
                        self.tray.stop()
                    for hk in self.hotkeys.values():
                        hk.stop()
                    self.root.destroy()
                    return
                elif kind == "result":
                    self._show_result(*ev[1:])
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    def _hk(self, mode="formula"):
        from hotkey import pretty
        return pretty(self.cfg[MODES[mode][0]])

    def open_hotkey_dialog(self, mode="formula"):
        from hotkey import HotkeyDialog
        if getattr(self, "_dlg", None) and self._dlg.win.winfo_exists():
            self._dlg.win.lift()
            return
        key, name = MODES[mode]
        # 창이 열려 있는 동안은 현재 단축키를 잠시 해제해야 그 키도 입력받을 수 있다
        self.hotkeys[mode].suspend()
        self._dlg = HotkeyDialog(self.root, self.cfg[key], DEFAULT_CONFIG[key],
                                 lambda new: self._save_hotkey(mode, new),
                                 on_close=self.hotkeys[mode].resume, title=f"{name} 캡처 단축키 변경")

    def _save_hotkey(self, mode: str, new: str):
        from hotkey import pretty
        key, name = MODES[mode]
        for other, (okey, oname) in MODES.items():
            if other != mode and self.cfg[okey] == new:
                return False, f"{pretty(new)} 는 {oname} 캡처 단축키로 쓰고 있어요. 다른 조합을 골라 주세요."
        if not self.hotkeys[mode].change(new):
            return False, f"{pretty(new)} 는 다른 프로그램이 이미 쓰고 있어요. 다른 조합을 골라 주세요."
        self.hotkeys[mode].first_result = True
        self.cfg[key] = new
        self._refresh_hotkey_label()
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, ensure_ascii=False, indent=2)
        except OSError as e:
            return True, f"적용은 됐지만 저장하지 못했어요: {e}"
        if self.tray:
            self.tray.update_menu()
        self.toast.show("단축키 변경됨", f"이제 {pretty(new)} 로 {name} 캡처합니다.", color="#1a7f37")
        return True, ""

    # ------------------------------------------------------------------
    def capture(self, mode="formula"):
        from overlay import select_region
        if self.root.state() == "normal":
            self.root.iconify()
            self.root.update()
            time.sleep(0.25)
        self.toast.win and self.toast.win.withdraw()
        img = select_region(self.root)
        if img is None:
            return
        self.busy = True
        if not self.rec.ready.is_set():
            self.toast.show("잠시만요…", "인식 모델을 아직 불러오는 중입니다.", ms=0)
        else:
            self.toast.show("인식 중…", "", ms=0)
        target = self._work_passage if mode == "passage" else self._work
        threading.Thread(target=target, args=(img,), daemon=True).start()

    def _work(self, img):
        t0 = time.time()
        try:
            from latex2hwp import latex_to_hwp
            from hwp_clipboard import set_equation_clipboard
            latex = self.rec.recognize(img)
            script = latex_to_hwp(latex)
            set_equation_clipboard(script, plain_text=latex)
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{latex}\t{script}\n")
            self.events.put(("result", "ok", f"LaTeX: {latex}\n한글: {script}", time.time() - t0))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self.events.put(("result", "err", str(e), 0))

    def _work_passage(self, img):
        """글자 + 수식 지문: 글자는 글자로, 수식은 한글 수식 개체로"""
        t0 = time.time()
        try:
            from latex2hwp import latex_to_hwp
            from passage import to_markdown
            from hwp_clipboard import set_passage_clipboard
            paras = self.rec.read_passage(img)
            if not paras:
                raise RuntimeError("글자나 수식을 찾지 못했습니다. 영역을 조금 넓게 잡아 보세요.")
            hwp = []
            for para in paras:
                segs = []
                for k, v in para:
                    if k == "text":
                        segs.append(("text", v))
                        continue
                    try:
                        segs.append(("eq", latex_to_hwp(v)))
                    except Exception:  # noqa: BLE001  변환 못 한 수식은 LaTeX 그대로 수식 칸에
                        segs.append(("eq", v))
                hwp.append(segs)
            md = to_markdown(paras)
            set_passage_clipboard(hwp, plain_text=md)
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t[지문]\t{md.replace(chr(10), ' / ')}\n")
            n_eq = sum(k == "math" for p in paras for k, _ in p)
            preview = md if len(md) <= 220 else md[:220] + "…"
            self.events.put(("result", "ok", f"문단 {len(paras)}개, 수식 {n_eq}개\n{preview}", time.time() - t0))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self.events.put(("result", "err", str(e), 0))

    def _show_result(self, kind, body, dt):
        self.busy = False
        if kind == "ok":
            self.toast.show(f"복사됨 ({dt:.1f}초) — 한글에서 Ctrl+V", body, ms=7000, color="#1a7f37")
        else:
            self.toast.show("인식 실패", a, ms=8000, color="#d1242f")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    if already_running():
        ctypes.windll.user32.MessageBoxW(None, "수식 캡처가 이미 실행 중입니다.\n작업 표시줄의 '수식 캡처' 창을 확인하세요.",
                                         "수식 캡처", 0x40)
        sys.exit(0)
    App().run()
