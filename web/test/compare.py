"""웹 결과와 파이썬(exe) 결과 비교: 같은 결과 수, 한글 글자 오류(수능 PDF 글자 정보 기준), 다른 문제 목록.

    python web/test/compare.py native.json web.json
"""
import glob, json, re, sys
meta = {}
for f in glob.glob('/mnt/project-files/test-set/meta/*_meta.json'):
    meta.update(json.load(open(f)))


def lev(a, b):
    p = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        c = [i]
        for j, cb in enumerate(b, 1):
            c.append(min(p[j] + 1, c[j - 1] + 1, p[j - 1] + (ca != cb)))
        p = c
    return p[-1]


def cer(name, r):
    g = ''.join(c[0] for c in sorted(meta[name]['hangul'], key=lambda c: (round((c[2] + c[4]) / 2 / 12), c[1])))
    p = ''.join(re.findall('[가-힣]', ''.join(v for para in r['hwp'] for k, v in para)))
    return lev(g, p), len(g)


A, B = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
names = sorted(n for n in A if not n.startswith('_'))
same = ea = eb = n_ = 0
diff = []
for n in names:
    a, b = A[n], B.get(n)
    if b is None or 'error' in b:
        diff.append((n, 'ERROR', b and b.get('error', '')[-200:]))
        continue
    x, tot = cer(n, a)
    y, _ = cer(n, b)
    ea += x; eb += y; n_ += tot
    if a['hwp'] == b['hwp']:
        same += 1
    else:
        diff.append((n, f'한글오류 {x}->{y}', ''))
print(f'같음 {same}/{len(names)}, 한글 글자 오류 exe {ea} / 웹 {eb} (전체 {n_}자)')
sa = sum(A[n]['sec'] for n in names); sb = sum((B[n].get('wall') or B[n].get('sec') or 0) for n in names if n in B)
print(f'시간 exe {sa:.0f}s ({sa/len(names):.1f}s/장) / 웹 {sb:.0f}s ({sb/len(names):.1f}s/장)')
for d in diff:
    print(*d)
if '-v' in sys.argv:
    for n, *_ in diff:
        if n in B and 'md' in B[n]:
            print('=====', n); print('exe:', A[n]['md']); print('web:', B[n]['md'])
