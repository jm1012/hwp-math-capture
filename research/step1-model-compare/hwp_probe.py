"""한글 2020 수식 삽입 시험 스크립트 (Windows 전용)

준비: pip install pywin32
실행: 한글 2020에서 빈 문서를 열고 커서를 둔 뒤
    python hwp_probe.py insert     -> 커서 위치에 근의 공식 수식 개체를 넣어 봄
    python hwp_probe.py clipboard  -> 한글에서 수식 개체 하나를 선택해 Ctrl+C 한 뒤 실행.
                                      클립보드 형식을 조사해 hwp_clip_dump 폴더에 저장
"""
import sys, os

TEST_EQ = "x = {-b +- sqrt {b ^{2} -4ac}} over {2a}"


def connect_hwp():
    import pythoncom, win32com.client as wc
    # 1) 이미 열려 있는 한글 찾기 (Running Object Table)
    ctx = pythoncom.CreateBindCtx(0)
    rot = pythoncom.GetRunningObjectTable()
    for mk in rot:
        name = mk.GetDisplayName(ctx, None)
        if "HwpObject" in name:
            obj = rot.GetObject(mk)
            print("열려 있는 한글에 연결:", name)
            return wc.Dispatch(obj.QueryInterface(pythoncom.IID_IDispatch))
    # 2) 없으면 새로 실행
    print("열린 한글을 찾지 못해 새 창을 엽니다.")
    hwp = wc.gencache.EnsureDispatch("HWPFrame.HwpObject")
    hwp.XHwpWindows.Item(0).Visible = True
    return hwp


def insert_equation(hwp, script, pt=11):
    ps = hwp.HParameterSet.HEqEdit
    hwp.HAction.GetDefault("EquationCreate", ps.HSet)
    ps.EqFontName = "HancomEQN"
    ps.string = script
    ps.BaseUnit = hwp.PointToHwpUnit(pt)
    ok = hwp.HAction.Execute("EquationCreate", ps.HSet)
    print("EquationCreate 결과:", ok)


def dump_clipboard():
    import win32clipboard as cb
    out = "hwp_clip_dump"; os.makedirs(out, exist_ok=True)
    cb.OpenClipboard()
    try:
        fmt = 0
        while True:
            fmt = cb.EnumClipboardFormats(fmt)
            if fmt == 0:
                break
            try:
                name = cb.GetClipboardFormatName(fmt)
            except Exception:
                name = f"standard_{fmt}"
            try:
                data = cb.GetClipboardData(fmt)
                if isinstance(data, str):
                    data = data.encode("utf-8")
                size = len(data) if isinstance(data, (bytes, bytearray)) else -1
                if size >= 0:
                    safe = "".join(c if c.isalnum() else "_" for c in name)
                    open(os.path.join(out, f"{fmt}_{safe}.bin"), "wb").write(data)
            except Exception as e:
                size = f"읽기 실패: {e}"
            print(f"{fmt:6d}  {name:40s}  {size}")
    finally:
        cb.CloseClipboard()
    print(f"\n'{out}' 폴더에 저장했습니다.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "insert"
    if cmd == "insert":
        insert_equation(connect_hwp(), TEST_EQ)
    elif cmd == "clipboard":
        dump_clipboard()
    else:
        print(__doc__)
