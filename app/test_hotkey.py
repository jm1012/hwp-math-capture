"""단축키 기능 자동 시험 (Windows). 사용: .venv\\Scripts\\python test_hotkey.py"""
import ctypes, threading, time, tkinter as tk
from hotkey import HotkeyManager, HotkeyDialog, validate

u = ctypes.windll.user32
fired = []

def press(*vks):
    for vk in vks: u.keybd_event(vk, 0, 0, 0)
    for vk in reversed(vks): u.keybd_event(vk, 0, 2, 0)
    time.sleep(0.3)

def taken(mods, vk):
    """다른 스레드에서 같은 조합 등록을 시도 → 실패하면 우리가 등록 중."""
    r = []
    def t():
        ok = u.RegisterHotKey(None, 99, mods, vk); r.append(not ok)
        if ok: u.UnregisterHotKey(None, 99)
    th = threading.Thread(target=t); th.start(); th.join(); return r[0]

m = HotkeyManager("ctrl+shift+q", lambda: fired.append(time.time()))
print("1 기본 등록:", m.first_result, "점유:", taken(6, 0x51))
press(0x11, 0x10, 0x51); print("2 Ctrl+Shift+Q 눌림 감지:", len(fired) == 1)
print("3 Ctrl+Alt+E 로 변경:", m.change("ctrl+alt+e"), "| 옛 키 해제:", not taken(6, 0x51), "| 새 키 점유:", taken(3, 0x45))
press(0x11, 0x12, 0x45); print("4 Ctrl+Alt+E 감지:", len(fired) == 2)
press(0x11, 0x10, 0x51); print("5 옛 키는 무시:", len(fired) == 2)
m.suspend(); print("6 일시중지 중 해제:", not taken(3, 0x45)); m.resume(); print("  재개 후 점유:", taken(3, 0x45))
print("7 검증:", validate("ctrl+v"), "|", validate("shift+a"), "|", validate("f9"))

# 설정 창: 키 조합을 눌러 값이 잡히는지
root = tk.Tk(); root.withdraw(); saved = []
def on_save(v): saved.append(v); return True, ""
d = HotkeyDialog(root, "ctrl+alt+e", "ctrl+shift+q", on_save)
def drive():
    d.win.focus_force(); d.box.focus_force(); root.update(); time.sleep(0.5)
    press(0x11, 0x10, 0x77)  # Ctrl+Shift+F8
    root.update(); time.sleep(0.2); root.update()
    print("8 설정 창이 잡은 값:", d.value, "| 저장 버튼:", d.save_btn["state"])
    d._save(); print("9 저장 콜백 값:", saved)
    root.destroy()
root.after(500, drive); root.mainloop()
