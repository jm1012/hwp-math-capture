"""전역 단축키: 등록/변경(재시작 없이)과 '원하는 키 조합을 눌러 지정'하는 설정 창."""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import queue
import threading
import tkinter as tk

MOD_ALT, MOD_CTRL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
MODS = {"ctrl": MOD_CTRL, "alt": MOD_ALT, "shift": MOD_SHIFT, "win": MOD_WIN}
WM_HOTKEY, WM_APP_REREGISTER = 0x0312, 0x8001

# 가상 키 코드 ↔ 이름
VK_NAMES = {**{0x41 + i: chr(0x41 + i) for i in range(26)},
            **{0x30 + i: str(i) for i in range(10)},
            **{0x70 + i: f"F{i + 1}" for i in range(24)},
            **{0x60 + i: f"Num{i}" for i in range(10)},
            0x20: "Space", 0x09: "Tab", 0x0D: "Enter", 0x2D: "Insert", 0x2E: "Delete",
            0x24: "Home", 0x23: "End", 0x21: "PageUp", 0x22: "PageDown",
            0x25: "Left", 0x26: "Up", 0x27: "Right", 0x28: "Down", 0x13: "Pause",
            0x91: "ScrollLock", 0x2C: "PrintScreen",
            0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: "/", 0xC0: "`",
            0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'"}
NAME_VK = {v.lower(): k for k, v in VK_NAMES.items()}
MODIFIER_VKS = {0x10, 0x11, 0x12, 0x5B, 0x5C, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5,
                0x15, 0x19}  # 마지막 둘: 한/영, 한자 키
# 다른 프로그램의 기본 동작을 빼앗으면 곤란한 조합
RESERVED = {"ctrl+c", "ctrl+v", "ctrl+x", "ctrl+z", "ctrl+y", "ctrl+a", "ctrl+s", "ctrl+p",
            "ctrl+o", "ctrl+n", "ctrl+f", "alt+f4", "alt+tab", "ctrl+alt+delete"}


def parse(text: str) -> tuple[int, int]:
    """'ctrl+shift+q' → (mods, vk)"""
    mods, vk = 0, None
    for part in text.lower().replace(" ", "").split("+"):
        if part in MODS:
            mods |= MODS[part]
        elif part in NAME_VK:
            vk = NAME_VK[part]
        elif part == "plus":
            vk = 0xBB
        else:
            raise ValueError(f"알 수 없는 키: {part}")
    if vk is None:
        raise ValueError("일반 키(글자, 숫자, F1 등)가 하나 있어야 합니다.")
    return mods, vk


def fmt(mods: int, vk: int) -> str:
    parts = [n for n, m in MODS.items() if mods & m]
    return "+".join(parts + [VK_NAMES.get(vk, f"VK{vk}").lower()])


def pretty(text: str) -> str:
    """'ctrl+shift+q' → 'Ctrl + Shift + Q'"""
    out = []
    for p in text.split("+"):
        if p in MODS:
            out.append(p.capitalize())
        elif p in NAME_VK:
            out.append(VK_NAMES[NAME_VK[p]])
        else:
            out.append(p)
    return " + ".join(out)


def validate(text: str) -> str | None:
    """문제가 있으면 이유를 돌려준다."""
    try:
        mods, vk = parse(text)
    except ValueError as e:
        return str(e)
    if text in RESERVED:
        return "복사/붙여넣기처럼 자주 쓰는 단축키라 쓸 수 없어요."
    is_fkey = 0x70 <= vk <= 0x87 or vk in (0x13, 0x91, 0x2C)
    if not (mods & (MOD_CTRL | MOD_ALT | MOD_WIN)) and not is_fkey:
        return "Ctrl, Alt, Win 중 하나와 함께 눌러 주세요 (F1~F24 같은 기능키는 단독 사용 가능)."
    return None


class HotkeyManager:
    """별도 스레드에서 RegisterHotKey 하고 WM_HOTKEY 를 받는다. change() 로 즉시 바꿀 수 있다."""

    def __init__(self, hotkey: str, on_fire):
        self.current = hotkey
        self.on_fire = on_fire
        self._tid = None
        self._req: queue.Queue = queue.Queue()
        self._started = threading.Event()
        self.first_result: bool | None = None
        threading.Thread(target=self._run, daemon=True).start()
        self._started.wait(3)

    def _register(self, text: str) -> bool:
        u = ctypes.windll.user32
        u.UnregisterHotKey(None, 1)
        try:
            mods, vk = parse(text)
        except ValueError:
            return False
        return bool(u.RegisterHotKey(None, 1, mods | MOD_NOREPEAT, vk))

    def _run(self):
        u = ctypes.windll.user32
        self._tid = ctypes.windll.kernel32.GetCurrentThreadId()
        msg = wt.MSG()
        u.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # 메시지 큐 생성
        self.first_result = self._register(self.current)
        self._started.set()
        suspended = False
        while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                self.on_fire()
            elif msg.message == WM_APP_REREGISTER:
                new, reply = self._req.get()
                if new is None:  # 일시 중지 (설정 창이 열려 있는 동안)
                    u.UnregisterHotKey(None, 1)
                    suspended = True
                    reply.put(True)
                elif new == "":  # 다시 시작
                    suspended = False
                    reply.put(self._register(self.current))
                elif self._register(new):
                    self.current = new
                    if suspended:  # 설정 창이 닫힐 때 다시 등록한다
                        u.UnregisterHotKey(None, 1)
                    reply.put(True)
                else:
                    if not suspended:
                        self._register(self.current)  # 실패하면 원래 단축키로 되돌림
                    reply.put(False)

    def stop(self):
        """단축키를 해제하고 스레드를 끝낸다 (프로그램 종료 시)."""
        if self._tid:
            ctypes.windll.user32.PostThreadMessageW(self._tid, 0x0012, 0, 0)  # WM_QUIT

    def suspend(self):
        self.change(None)

    def resume(self) -> bool:
        return self.change("")

    def change(self, new: str | None) -> bool:
        """새 단축키로 바꾼다. 다른 프로그램이 이미 쓰고 있으면 False (기존 단축키 유지)."""
        reply: queue.Queue = queue.Queue()
        self._req.put((new, reply))
        ctypes.windll.user32.PostThreadMessageW(self._tid, WM_APP_REREGISTER, 0, 0)
        try:
            return reply.get(timeout=3)
        except queue.Empty:
            return False


class HotkeyDialog:
    """'원하는 키 조합을 누르세요' 창. 저장하면 on_save(새 단축키 문자열) → (성공 여부, 메시지)."""

    def __init__(self, root: tk.Tk, current: str, default: str, on_save, on_close=None, title="단축키 변경"):
        self.on_save = on_save
        self.on_close = on_close
        self.default = default
        self.value: str | None = None
        self.win = w = tk.Toplevel(root)
        w.title(title)
        w.attributes("-topmost", True)
        w.resizable(False, False)
        w.configure(bg="white", padx=20, pady=16)
        f = ("Malgun Gothic", 10)
        tk.Label(w, text=f"현재 단축키: {pretty(current)}", font=f, bg="white", anchor="w").pack(fill="x")
        tk.Label(w, text="아래 칸을 클릭하고 원하는 키 조합을 눌러 주세요.", font=f, bg="white",
                 fg="#555", anchor="w").pack(fill="x", pady=(6, 6))
        self.box = tk.Label(w, text="여기를 클릭한 뒤 키를 누르세요", font=("Malgun Gothic", 14, "bold"),
                            bg="#f3f6fb", fg="#1f6feb", width=26, height=2, relief="solid", bd=1,
                            takefocus=1)
        self.box.pack(fill="x")
        self.msg = tk.Label(w, text="", font=f, bg="white", fg="#d1242f", anchor="w", wraplength=330,
                            justify="left")
        self.msg.pack(fill="x", pady=(6, 8))
        bar = tk.Frame(w, bg="white")
        bar.pack(fill="x")
        tk.Button(bar, text=f"기본값 ({pretty(default)})", font=f, command=self._reset).pack(side="left")
        tk.Button(bar, text="취소", font=f, width=7, command=self.close).pack(side="right")
        self.save_btn = tk.Button(bar, text="저장", font=f, width=7, state="disabled", command=self._save)
        self.save_btn.pack(side="right", padx=(0, 6))
        self.box.bind("<Button-1>", lambda e: self.box.focus_set())
        self.box.bind("<KeyPress>", self._on_key)
        w.protocol("WM_DELETE_WINDOW", self.close)
        w.update_idletasks()
        sw, sh = w.winfo_screenwidth(), w.winfo_screenheight()
        w.geometry(f"+{(sw - w.winfo_reqwidth()) // 2}+{(sh - w.winfo_reqheight()) // 3}")
        w.focus_force()
        self.box.focus_set()

    @staticmethod
    def _down(vk: int) -> bool:
        return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)

    def _on_key(self, e):
        vk = e.keycode  # Windows 에서는 가상 키 코드 (한/영 상태와 무관)
        if vk in MODIFIER_VKS:
            return "break"
        mods = 0
        # Tk 가 이벤트에 담아 주는 수식키 상태를 우선 사용 (키를 이미 뗐을 수 있음)
        st = int(getattr(e, "state", 0) or 0)
        if st & 0x4 or self._down(0x11):
            mods |= MOD_CTRL
        if st & 0x20000 or self._down(0x12):
            mods |= MOD_ALT
        if st & 0x1 or self._down(0x10):
            mods |= MOD_SHIFT
        if self._down(0x5B) or self._down(0x5C):
            mods |= MOD_WIN
        if vk not in VK_NAMES:
            self.msg.config(text="이 키는 쓸 수 없어요. 글자, 숫자, F1~F24 등을 눌러 주세요.")
            return "break"
        self._set(fmt(mods, vk))
        return "break"

    def _set(self, text: str):
        self.value = text
        self.box.config(text=pretty(text))
        problem = validate(text)
        self.msg.config(text=problem or "", fg="#d1242f")
        self.save_btn.config(state="disabled" if problem else "normal")

    def _reset(self):
        self._set(self.default)

    def _save(self):
        if not self.value:
            return
        ok, message = self.on_save(self.value)
        if ok:
            self.close()
        else:
            self.msg.config(text=message, fg="#d1242f")

    def close(self):
        if self.win.winfo_exists():
            self.win.destroy()
        if self.on_close:
            self.on_close()
            self.on_close = None
