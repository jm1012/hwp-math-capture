"""한글 2020에서 변환 결과를 실제로 렌더링해 PNG로 저장 (Windows 전용)
사용: python verify_render.py cases_hwp.json   -> render_out/<이름>.png, render_out/report.json
열려 있는 한글에 새 문서를 하나 만들어 그 안에서만 작업하고, 끝나면 저장하지 않고 닫는다.
"""
import base64, json, os, re, sys, time
import pythoncom, win32clipboard as cb, win32com.client as wc

def connect():
    ctx = pythoncom.CreateBindCtx(0); rot = pythoncom.GetRunningObjectTable()
    for mk in rot:
        if "HwpObject" in mk.GetDisplayName(ctx, None):
            return wc.Dispatch(rot.GetObject(mk).QueryInterface(pythoncom.IID_IDispatch))
    h = wc.gencache.EnsureDispatch("HWPFrame.HwpObject"); h.XHwpWindows.Item(0).Visible = True
    return h

def html_clip():
    fmt = cb.RegisterClipboardFormat("HTML Format")
    for _ in range(20):
        try:
            cb.OpenClipboard()
            try:
                return cb.GetClipboardData(fmt).decode("utf-8", "replace") if cb.IsClipboardFormatAvailable(fmt) else ""
            finally:
                cb.CloseClipboard()
        except Exception:
            time.sleep(0.1)
    return ""

def main(path):
    cases = json.load(open(path, encoding="utf-8"))
    out = "render_out"; os.makedirs(out, exist_ok=True)
    hwp = connect()
    hwp.XHwpDocuments.Add(0)  # 새 문서 (현재 문서는 건드리지 않음)
    report = {}
    for name, c in cases.items():
        hwp.HAction.Run("SelectAll"); hwp.HAction.Run("Delete")
        ps = hwp.HParameterSet.HEqEdit
        hwp.HAction.GetDefault("EquationCreate", ps.HSet)
        ps.EqFontName = "HancomEQN"; ps.string = c["hwp"]; ps.BaseUnit = hwp.PointToHwpUnit(14)
        ok = hwp.HAction.Execute("EquationCreate", ps.HSet)
        hwp.HAction.Run("SelectAll"); hwp.HAction.Run("Copy"); time.sleep(0.2)
        html = html_clip()
        m = re.search(r"data:image/png;base64,([A-Za-z0-9+/=]+)", html)
        if m:
            open(os.path.join(out, f"{name}.png"), "wb").write(base64.b64decode(m.group(1)))
        script = re.search(r'"(?:script|EqScript|eqscript|equation)"\s*:\s*"((?:[^"\\]|\\.)*)"', html)
        report[name] = dict(ok=bool(ok), png=bool(m), stored=script.group(1) if script else None)
        print(name, report[name]["ok"], report[name]["png"])
    if not any(r["png"] for r in report.values()):
        open(os.path.join(out, "last_clip.html"), "w", encoding="utf-8").write(html)
    json.dump(report, open(os.path.join(out, "report.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    hwp.XHwpDocuments.Active_XHwpDocument.Close(False)  # 저장하지 않고 닫기
    print("완료:", out)

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "cases_hwp.json")
