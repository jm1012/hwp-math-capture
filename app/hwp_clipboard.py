"""Put a Hancom Hangul (2020) equation on the clipboard so that a plain Ctrl+V in Hangul
pastes a real, editable equation object.

The clipboard gets only "HTML Format" (plus CF_UNICODETEXT if asked). It holds
Hangul's data-hwpjson payload, the format Hangul itself writes when copying.
Never set "Hwp_Native_Info": its presence makes Hangul's Paste fail.
"""
import copy
import itertools
import json
import time

import win32clipboard as cb

# Captured from Hangul 11.0.0.1623 (equation copy) with the preview PNG (pi/bi/bidt) removed.
# The equation script sits at cs/<id>/eq/sc and is the placeholder "__SCRIPT__".
JSON_TEMPLATE = '{\r"documentPr": {\r"di": "",\r"dp": {\r"dn": "test.hwp",\r"ta": 1,\r"d1": 5,\r"d2": 1,\r"dv": 0,\r"dr": 1,\r"do": 1,\r"vj": "1.1",\r"an": "Hancom Office Hangul",\r"av": "11, 0, 0, 1623",\r"ao": "WIN",\r"ab": "32",\r"ar": "LE",\r"as": "Windows_8"\r},\r"dis": false,\r"ds": {\r"ti": "",\r"la": "ko",\r"cr": "",\r"su": "",\r"de": "",\r"cd": "2026-11-13T03:51:28.355Z",\r"md": "2026-11-13T03:51:31.511Z",\r"pd": "1601-01-01T09:00:00.000Z",\r"ke": ""\r}\r},\r"dh": {\r"do": {\r"pa": 1,\r"fo": 1,\r"en": 1,\r"pi": 1,\r"tb": 1,\r"eq": 1\r},\r"fo": [ ],\r"cd": {\r"tp": 0,\r"lc": {\r"af": false,\r"ui": false,\r"fu": false,\r"dn": false,\r"ul": false,\r"el": false,\r"at": false,\r"tq": false,\r"da": false,\r"dw": false,\r"dj": false,\r"bc": false,\r"bu": false,\r"al": false,\r"ab": false,\r"ap": false,\r"an": false,\r"aa": false,\r"ds": false,\r"de": false,\r"as": false,\r"cp": false,\r"ao": false,\r"et": false,\r"ay": false,\r"am": false,\r"a1": false,\r"bt": false,\r"av": false,\r"dh": false,\r"dp": false,\r"d1": false,\r"mf": false,\r"bl": false,\r"ag": false,\r"dg": false,\r"ae": false,\r"df": false,\r"do": false,\r"dl": false,\r"di": false,\r"d2": false,\r"d3": false,\r"ob": false,\r"d4": false,\r"ev": false,\r"d5": false,\r"d6": false,\r"a2": false,\r"dc": false\r}\r},\r"ld": {\r"pa": "",\r"pi": true,\r"fo": false\r}\r},\r"bf": {\r"01DD72D6D548357000000004": {\r"id": 1,\r"td": false,\r"sh": false,\r"st": 0,\r"sc": 0,\r"si": false,\r"bt": 0,\r"bi": false,\r"cl": 0,\r"bc": false,\r"lt": 0,\r"lw": 0,\r"lc": 0,\r"rt": 0,\r"rw": 0,\r"rc": 0,\r"tt": 0,\r"tw": 0,\r"tc": 0,\r"bbt": 0,\r"bbw": 0,\r"bbc": 0,\r"dt": 1,\r"dw": 0,\r"dc": 0,\r"fi": { }\r},\r"01DD72D6D5485C8000000005": {\r"id": 2,\r"td": false,\r"sh": false,\r"st": 0,\r"sc": 0,\r"si": false,\r"bt": 0,\r"bi": false,\r"cl": 0,\r"bc": false,\r"lt": 0,\r"lw": 0,\r"lc": 0,\r"rt": 0,\r"rw": 0,\r"rc": 0,\r"tt": 0,\r"tw": 0,\r"tc": 0,\r"bbt": 0,\r"bbw": 0,\r"bbc": 0,\r"dt": 1,\r"dw": 0,\r"dc": 0,\r"fi": {\r"wb": {\r"fc": 4294967295,\r"hc": 10066329,\r"al": 0,\r"hs": -1\r}\r}\r}\r},\r"cp": {\r"01DD72D6D5485C8000000006": {\r"id": 0,\r"he": 1000,\r"tc": 0,\r"sc": 4294967295,\r"uf": false,\r"uk": false,\r"sm": 0,\r"bf": "01DD72D6D548357000000004",\r"f1": "한컴바탕",\r"t1": 1,\r"f2": "한컴바탕",\r"t2": 1,\r"f3": "함초롬바탕",\r"t3": 1,\r"f4": "한컴바탕",\r"t4": 1,\r"f5": "한컴바탕",\r"t5": 1,\r"f6": "한컴바탕",\r"t6": 1,\r"f7": "한컴바탕",\r"t7": 1,\r"r1": 100,\r"r2": 100,\r"r3": 100,\r"r4": 100,\r"r5": 100,\r"r6": 100,\r"r7": 100,\r"s1": 0,\r"s2": 0,\r"s3": 0,\r"s4": 0,\r"s5": 0,\r"s6": 0,\r"s7": 0,\r"e1": 100,\r"e2": 100,\r"e3": 100,\r"e4": 100,\r"e5": 100,\r"e6": 100,\r"e7": 100,\r"o1": 0,\r"o2": 0,\r"o3": 0,\r"o4": 0,\r"o5": 0,\r"o6": 0,\r"o7": 0,\r"it": false,\r"bo": false,\r"ut": 0,\r"us": 1,\r"uc": 0,\r"st": false,\r"ss": 1,\r"so": 0,\r"ot": 0,\r"ht": 0,\r"hc": 0,\r"hx": 0,\r"hy": 0,\r"em": false,\r"en": false,\r"su": false,\r"sb": false\r},\r"01DD72D6D5485C8000000007": {\r"id": 1,\r"he": 1000,\r"tc": 0,\r"sc": 4294967295,\r"uf": false,\r"uk": false,\r"sm": 0,\r"bf": "01DD72D6D5485C8000000005",\r"f1": "함초롬바탕",\r"t1": 1,\r"f2": "함초롬바탕",\r"t2": 1,\r"f3": "함초롬바탕",\r"t3": 1,\r"f4": "함초롬바탕",\r"t4": 1,\r"f5": "함초롬바탕",\r"t5": 1,\r"f6": "함초롬바탕",\r"t6": 1,\r"f7": "함초롬바탕",\r"t7": 1,\r"r1": 100,\r"r2": 100,\r"r3": 100,\r"r4": 100,\r"r5": 100,\r"r6": 100,\r"r7": 100,\r"s1": 0,\r"s2": 0,\r"s3": 0,\r"s4": 0,\r"s5": 0,\r"s6": 0,\r"s7": 0,\r"e1": 100,\r"e2": 100,\r"e3": 100,\r"e4": 100,\r"e5": 100,\r"e6": 100,\r"e7": 100,\r"o1": 0,\r"o2": 0,\r"o3": 0,\r"o4": 0,\r"o5": 0,\r"o6": 0,\r"o7": 0,\r"it": false,\r"bo": false,\r"ut": 0,\r"us": 1,\r"uc": 0,\r"st": false,\r"ss": 1,\r"so": 0,\r"ot": 0,\r"ht": 0,\r"hc": 0,\r"hx": 0,\r"hy": 0,\r"em": false,\r"en": false,\r"su": false,\r"sb": false\r}\r},\r"tp": {\r"01DD72D6D5485C8000000008": {\r"id": 0,\r"al": false,\r"ar": false,\r"tp": [ ]\r}\r},\r"nu": { },\r"bu": { },\r"pp": {\r"01DD72D6D5485C8000000009": {\r"id": 0,\r"ah": 0,\r"av": 0,\r"ht": 0,\r"hi": "",\r"hl": 0,\r"tp": "01DD72D6D5485C8000000008",\r"kb": 0,\r"kn": true,\r"ko": false,\r"kk": false,\r"kl": false,\r"kp": false,\r"kw": 0,\r"co": 0,\r"fl": false,\r"st": true,\r"sl": false,\r"ae": false,\r"aa": false,\r"mi": 0,\r"ml": 0,\r"mr": 0,\r"mp": 0,\r"mn": 0,\r"lt": 0,\r"lv": 160,\r"bf": "01DD72D6D548357000000004",\r"bl": 0,\r"br": 0,\r"bt": 0,\r"bb": 0,\r"bc": false,\r"bi": false\r},\r"01DD72D6D5485C800000000A": {\r"id": 1,\r"ah": 0,\r"av": 0,\r"ht": 0,\r"hi": "",\r"hl": 0,\r"tp": "01DD72D6D5485C8000000008",\r"kb": 0,\r"kn": true,\r"ko": false,\r"kk": false,\r"kl": false,\r"kp": false,\r"kw": 0,\r"co": 0,\r"fl": false,\r"st": true,\r"sl": false,\r"ae": false,\r"aa": false,\r"mi": 0,\r"ml": 0,\r"mr": 0,\r"mp": 0,\r"mn": 0,\r"lt": 0,\r"lv": 160,\r"bf": "01DD72D6D5485C8000000005",\r"bl": 0,\r"br": 0,\r"bt": 0,\r"bb": 0,\r"bc": false,\r"bi": false\r}\r},\r"st": {\r"01DD72D6D5485C800000000B": {\r"id": 0,\r"ty": 0,\r"na": "바탕글",\r"en": "Normal",\r"pp": "01DD72D6D5485C800000000A",\r"cp": "01DD72D6D5485C8000000007",\r"ns": "01DD72D6D5485C800000000B",\r"li": 1042,\r"lf": false\r}\r},\r"mp": { },\r"ro": {\r"hp": "01DD72D6D548357000000003",\r"01DD72D6D548357000000003": {\r"np": "",\r"id": 0,\r"pp": "01DD72D6D5485C8000000009",\r"si": "01DD72D6D5485C800000000B",\r"bf": 3,\r"ru": [\r{\r"cp": "01DD72D6D5485C8000000006",\r"ch": [\r{\r"cc": 2,\r"ci": 1936024420,\r"co": "01DD72D6D548357000000000"\r}\r,\r{\r"cc": 2,\r"ci": 1668246628,\r"co": "01DD72D6D548357000000001"\r}\r,\r{\r"cc": 11,\r"ci": 1701930340,\r"co": "01DD72D6D548357000000002"\r}\r,\r{\r"t": ""\r}\r]\r}\r]\r}\r},\r"sl": { },\r"cs": {\r"01DD72D6D548357000000000": {\r"cc": 2,\r"ci": 1936024420,\r"td": 0,\r"tv": false,\r"sc": 1134,\r"ts": 8000,\r"ms": "",\r"os": "",\r"gl": 0,\r"gc": 0,\r"gw": false,\r"ns": 0,\r"np": 0,\r"ni": 0,\r"nt": 0,\r"ne": 0,\r"hh": false,\r"hf": false,\r"hm": false,\r"fb": false,\r"hb": false,\r"fi": false,\r"hi": false,\r"hp": false,\r"he": false,\r"sl": false,\r"lr": 0,\r"lc": 0,\r"ld": 0,\r"ls": 0,\r"pp": {\r"ls": false,\r"wi": 59528,\r"he": 84188,\r"gt": 0,\r"ml": 8504,\r"mr": 8504,\r"mt": 5668,\r"mb": 4252,\r"mh": 4252,\r"mf": 4252,\r"mg": 0\r},\r"fn": {\r"at": 0,\r"au": "",\r"ap": "",\r"ac": ")",\r"as": false,\r"ll": -1,\r"lt": 1,\r"lw": 1,\r"lc": 0,\r"sa": 850,\r"sb": 567,\r"st": 283\r,\r"nt": 0,\r"nn": 1,\r"pp": 0,\r"pb": false\r},\r"en": {\r"at": 0,\r"au": "",\r"ap": "",\r"ac": ")",\r"as": false,\r"ll": -4,\r"lt": 1,\r"lw": 1,\r"lc": 0,\r"sa": 850,\r"sb": 567,\r"st": 0\r,\r"nt": 0,\r"nn": 1,\r"pp": 0,\r"pb": false\r},\r"pb": [\r{\r"ty": 0,\r"bf": "01DD72D6D548357000000004",\r"tb": true,\r"hi": false,\r"fi": false,\r"fa": 0,\r"ol": 1417,\r"or": 1417,\r"ot": 1417,\r"ob": 1417\r},\r{\r"ty": 1,\r"bf": "01DD72D6D548357000000004",\r"tb": true,\r"hi": false,\r"fi": false,\r"fa": 0,\r"ol": 1417,\r"or": 1417,\r"ot": 1417,\r"ob": 1417\r},\r{\r"ty": 2,\r"bf": "01DD72D6D548357000000004",\r"tb": true,\r"hi": false,\r"fi": false,\r"fa": 0,\r"ol": 1417,\r"or": 1417,\r"ot": 1417,\r"ob": 1417\r}\r],\r"mp": [ ]\r}\r,\r"01DD72D6D548357000000001": {\r"cc": 2,\r"ci": 1668246628,\r"ty": 0,\r"la": 0,\r"co": 1,\r"ss": true,\r"sg": 0,\r"lt": 0,\r"lw": 0,\r"lc": 0,\r"cs": [ ]\r}\r,\r"01DD72D6D548357000000002": {\r"cc": 11,\r"ci": 1701930340,\r"id": 1245838674,\r"zo": 0,\r"nt": 3,\r"tw": 1,\r"tf": 0,\r"lo": false,\r"swi": 9460,\r"she": 2933,\r"swr": 4,\r"shr": 2,\r"spr": false,\r"pta": true,\r"pal": false,\r"pvr": 2,\r"phr": 3,\r"pva": 0,\r"ph1": 0,\r"pvo": 0,\r"ph2": 0,\r"pfw": true,\r"pao": false,\r"pha": false,\r"ole": 56,\r"ori": 56,\r"oto": 0,\r"obo": 0,\r"ca": { },\r"sc": "수식입니다."\r,\r"eq": {\r"ve": "Equation Version 60",\r"bl": 70,\r"tc": 0,\r"bu": 1100,\r"lm": false,\r"sc": "__SCRIPT__",\r"pi": "01DD72D6D5485C800000000C.png"\r}\r}\r},\r"bi": [ ],\r"bidt": {\r"01DD72D6D5485C800000000C.png": "iVBORw0KGgoAAAANSUhEUgAAAH8AAAAoCAIAAABYVLILAAAABnRSTlMA/wD/AP83WBt9AAAACXBIWXMAAA7DAAAOwwHHb6hkAAAD+UlEQVRoge2aP5KqQBDGP7beUcCA8gRwAjQxMjWDEBOzDc1MZkI2M92IROYEeoIpAqbvMi/APyzKExUX5PmLYIpquj6bnrZ7oPtJ4qOD+MlPL/+07dBzEJmttDbbduMaH2078BREhnHnpUdP1X8V8XupfqX4JALXMAzDMNxA/LZXl+ih+pXii9XSXmuttVZTOeqE/i3UIyWUSpjv+IlqxlzC2MFStWXFWHK2+Pt0IPZN04KEbVVnauIBp5rWipFfZZkExqF3j6+F9wRubZ8q6YD6gEoxbWibLKWdc8tERKZnPvg2EYy+HrMAoBvqi1gOB08Rv2yZiEzTNAEQ5/fnfeKZzZz7vTzSAfVFLId2FriG4QbisY/5gvgFy8RnlpXXPIaVDu5OPWKD8bi8uK+n3CAopCQSXJAIKius9tWnTEJisNhqNZXLzcFxERhHrPnX3DrdVlYrJfHLls1we9rwonvFFzwbhKUvlbhrjfCptF7bUu5zHfFgY4We6U2mE6vC2NP28390WortDsUcZ1+kFC5/oph/cV1rrVVyLGkK1U5dy7d6eyyWihYVc3C4Sfz944o55a7OOc/r83iR1tHVp2jzPfzc5qGk0t1wclv+F3y1nAM68vLILwT0bZbreQuxwTgsr63mOz/J3yQyexLmi9/Txfaauba7bCod5u6C+FKydQ0FinhhhNSIReR5JfEftXwRytI0DgIAkLsdVgEmi0H85TCVv1nE6SDKHzxt9/lWf9Fey+pTJgGCBxHMTqF6E97EH8UiQkn8BiyfY4bR/kckLiUWUWgSXyL/rkgES0y2xLkKx4DMCJ5JnKtxeZs4cS01PRnFfAeAc5bY6ybi/FHfPzNQabkBp5OD6URpxXyWKKWUUszJl3KnHABXdhtDa91EVLQKcXeG9bY6xLpKL9QHCQHPeznxa9X7xdK7RCcahYD5itIDh7yvmJMnqfzieqX6pgk+AID4ZrDWaprO3BnWikFmD7fv3tTh9ENc/0NYh24eJuga++RyUr9a/BuKvzc3cax5ClUbER7tf7+pxQdx1+UE2nzvAIAEDzZtO/Xf8AcY4nvlppO1ms4s49tPttE78H+LtlPfE9j3GJ7TZWiU9qcrDUPcnWGx1VprNZVzq4HZ9/Ponfoq3e1SRQBghp8+dqlq26Vqeqe+F2kdFfoOjn2c6l0cvbZK79QvImLJ1vvO58XRa+u0vfE8jR/D4Iuj1/bpq/oJK54fTPzT3/KkG4cItdY9Vb94uCFJEp34pyFThyK/hxUnIATCw5iLeJxZlEnkM+589Oo9dJCtSXqnPvHlaFQ4h4WBaY6nvg0iIlg2ZMzVw2doG6Ifk8VXpXex/1K81W+TvwYBT6S/1ZF5AAAAAElFTkSuQmCC"\r}\r}'

_PLACEHOLDER = '"sc": "__SCRIPT__"'

_HEADER = ("Version:1.0\r\nStartHTML:{:010d}\r\nEndHTML:{:010d}\r\n"
           "StartFragment:{:010d}\r\nEndFragment:{:010d}\r\n")


def build_json(script: str) -> str:
    return JSON_TEMPLATE.replace(_PLACEHOLDER, '"sc": ' + json.dumps(script, ensure_ascii=False))


def build_html(script: str) -> bytes:
    """Return CF_HTML bytes for one equation with the given Hangul equation script."""
    # Hangul's convention: fragment offsets point at the START of the marker comments.
    return _wrap_html(build_json(script).encode("utf-8"))


_ids = itertools.count(0x100)


def _new_id() -> str:
    return f"01DD72D6D5485C80{next(_ids):08X}"


def build_passage_json(paras) -> str:
    """paras: [[("text", "함수 "), ("eq", "f(x)=x^2"), ...], ...] (eq 는 한글 수식 스크립트).
    한글이 글자+수식을 복사할 때와 같은 구조: 문단(ro)의 ch 목록에 {"t": 글자} 와 수식 컨트롤 참조가 차례로 들어감."""
    d = json.loads(JSON_TEMPLATE.replace(_PLACEHOLDER, '"sc": ""'))
    ro = d["ro"]
    head_id = ro["hp"]
    head = ro[head_id]
    secd, cold, eq_ref = head["ru"][0]["ch"][:3]
    eq_tpl = d["cs"].pop(eq_ref["co"])
    cp = head["ru"][0]["cp"]
    paras = [p for p in paras if p] or [[("text", "")]]
    pids = [head_id] + [_new_id() for _ in paras[1:]]
    for i, segs in enumerate(paras):
        ch = [secd, cold] if i == 0 else []
        for kind, val in segs:
            if kind == "text":
                if ch and "t" in ch[-1]:
                    ch[-1] = {"t": ch[-1]["t"] + val}
                else:
                    ch.append({"t": val})
            else:
                cid = _new_id()
                c = copy.deepcopy(eq_tpl)
                c["eq"]["sc"] = val
                c["id"] = eq_tpl["id"] + len(d["cs"])
                d["cs"][cid] = c
                ch.append({"cc": 11, "ci": eq_ref["ci"], "co": cid})
        if "t" not in ch[-1]:
            ch.append({"t": ""})
        p = copy.deepcopy(head)
        p["ru"] = [{"cp": cp, "ch": ch}]
        p["np"] = pids[i + 1] if i + 1 < len(pids) else ""
        if i > 0:
            # 첫 문단의 bf=3 은 구역/단 나누기 표시. 그대로 복사하면 문단마다 새 쪽이 시작됨
            p["bf"] = 0
        ro[pids[i]] = p
    return json.dumps(d, ensure_ascii=False)


def _wrap_html(jb: bytes) -> bytes:
    html = (b"<html><body><!--StartFragment-->"
            b"<div id='hwpEditorBoardContent' class='hwp_editor_board_content' data-hjsonver='1.0' "
            b"data-jsonlen='" + str(len(jb)).encode("ascii") + b"'><!--[data-hwpjson]" + jb +
            b"--></div><!--EndFragment--></body></html>")
    hlen = len(_HEADER.format(0, 0, 0, 0).encode("ascii"))
    sf = html.index(b"<!--StartFragment-->")
    ef = html.index(b"<!--EndFragment-->")
    return _HEADER.format(hlen, hlen + len(html), hlen + sf, hlen + ef).encode("ascii") + html


def _open_clipboard(retries: int = 50, delay: float = 0.02):
    for i in range(retries):
        try:
            cb.OpenClipboard()
            return
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(delay)


def set_equation_clipboard(script: str, plain_text: "str | None" = None) -> None:
    """Replace the clipboard with an equation for Hangul (and optional plain text for other apps)."""
    _set_html(build_html(script), plain_text)


def set_passage_clipboard(paras, plain_text: "str | None" = None) -> None:
    """글자 + 수식이 섞인 여러 문단을 클립보드에 넣는다 (한글에서 Ctrl+V)."""
    _set_html(_wrap_html(build_passage_json(paras).encode("utf-8")), plain_text)


def _set_html(data: bytes, plain_text: "str | None") -> None:
    fmt = cb.RegisterClipboardFormat("HTML Format")
    _open_clipboard()
    try:
        cb.EmptyClipboard()
        cb.SetClipboardData(fmt, data)
        if plain_text is not None:
            cb.SetClipboardData(cb.CF_UNICODETEXT, plain_text)
    finally:
        cb.CloseClipboard()
