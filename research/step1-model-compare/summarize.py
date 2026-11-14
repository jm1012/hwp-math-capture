import json, re, difflib
def norm(s):
    s=s.strip().strip("$")
    s=re.sub(r"\\operatorname\*?\s*\{\s*([a-z ]+)\}", lambda m:"\\"+m.group(1).replace(" ",""), s)
    s=re.sub(r"\\underset\s*\{(.*?)\}\s*\{\s*\\(lim|sum)\s*\}", r"\\\2_{\1}", s)
    s=re.sub(r"\\(left|right|big|Big|displaystyle|textstyle|mathrm|mathop)\b","",s)
    s=re.sub(r"\\[,;!: ]|\\quad|\\qquad","",s)
    s=s.replace("\\prime","'").replace("^{'}","'").replace("^'","'").replace("\\leq","\\le")
    s=re.sub(r"\s+","",s)
    for _ in range(3): s=re.sub(r"\{([^{}\\]?)\}", r"\1", s)
    s=re.sub(r"\{(\\[a-zA-Z]+)\}", r"\1", s)
    return s
out=[]
for m in ["pix2tex","p2t","texify"]:
    d=json.load(open(f"step1/res_{m}.json")); rows=d["rows"]
    ex=[norm(r["pred"])==norm(r["gt"]) for r in rows]
    for r,e in zip(rows,ex): r["sem"]=e
    byfont={f:sum(e for r,e in zip(rows,ex) if r["id"].endswith(f)) for f in ["_cm","_stix","_dv"]}
    out.append((m,sum(ex),len(rows),round(sum(r["sec"] for r in rows)/len(rows),2),byfont))
    json.dump(d,open(f"step1/res_{m}.json","w"),ensure_ascii=False,indent=1)
for o in out: print(o)
