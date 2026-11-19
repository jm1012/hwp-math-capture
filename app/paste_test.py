"""개발용: 문제 그림 파일을 지문 인식 → 한글 클립보드 → 열린 한글에 붙여넣기 → 쪽 그림 저장.
python paste_test.py 출력폴더 그림1.png [그림2.png …]   (한글 2020, pywin32 필요)"""
import os
import sys
import time

from PIL import Image

import hwp_clipboard as hc
from latex2hwp import latex_to_hwp
from recognizer import Recognizer


def main(out, files):
    import win32com.client as wc
    os.makedirs(out, exist_ok=True)
    rec = Recognizer()
    rec._load()
    if rec.error:
        raise rec.error
    print("그림 찾기:", "켜짐" if rec.passage.figures is not None else "꺼짐 (모델 없음)")
    hwp = wc.Dispatch("HWPFrame.HwpObject")
    try:
        hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
    except Exception:  # noqa: BLE001
        pass
    hwp.XHwpWindows.Item(0).Visible = True
    for f in files:
        name = os.path.splitext(os.path.basename(f))[0]
        t0 = time.time()
        paras = rec.read_passage(Image.open(f))
        segs_all = []
        for p in paras:
            segs = []
            for k, v in p:
                if k == "text":
                    segs.append(("text", v))
                elif k == "image":
                    segs.append(("pic", hc.figure_for_hwp(v)))
                else:
                    segs.append(("eq", latex_to_hwp(v)))
            segs_all.append(segs)
        hc.set_passage_clipboard(segs_all)
        dt = time.time() - t0
        hwp.HAction.Run("FileNew")
        time.sleep(0.5)
        hwp.HAction.Run("Paste")
        time.sleep(1.0)
        n_pic = 0
        c = hwp.HeadCtrl
        while c:
            n_pic += c.CtrlID == "gso"
            c = c.Next
        img = os.path.join(os.path.abspath(out), name + "_page.png")
        try:
            hwp.CreatePageImage(img, 0, 96, 24, "png")
        except Exception as e:  # noqa: BLE001
            print("쪽 그림 저장 실패:", e)
        print(f"{name}: 인식 {dt:.1f}초, 문단 {len(paras)}, 그림 문단 {sum(k == 'image' for p in paras for k, _ in p)}, "
              f"붙여넣은 문서의 그림 개체 {n_pic}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
