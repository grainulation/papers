import re,sys,glob,statistics as st
R=sys.argv[1]
def ms(s):
    s=s.strip()
    if s.endswith('μs'): return float(s[:-2])/1000
    if s.endswith('ms'): return float(s[:-2])
    if s.endswith('s'): return float(s[:-1])*1000
def parse_stress(f):
    out={};topic=None
    for l in open(f):
        m=re.search(r'Topic: (.*)',l)
        if m: topic=m.group(1).strip()
        if l.strip().startswith('│') and topic:
            c=[x.strip() for x in l.strip().strip('│').split('│')]
            if c[0] in('N',''): continue
            out[(topic,c[0])]=c
    return out
runs=[parse_stress(f) for f in sorted(glob.glob(R+'/stress-*.txt'))]
print("STRESS medians over",len(runs),"runs")
for k in runs[0]:
    rows=[r[k] for r in runs]
    nontime=set(tuple(r[:-1]) for r in rows)
    t=[ms(r[-1]) for r in rows]
    print(f"{k[0][:30]:30} N={k[1]:>7} claims={rows[0][1]:>7} slots={rows[0][3]:>3} FP={rows[0][5]} prec={rows[0][4]:>5} median={st.median(t):8.2f}ms min={min(t):.2f} max={max(t):.2f} stable={len(nontime)==1}")
def parse_pt(f):
    out={};topic=None
    for l in open(f):
        m=re.match(r'\s+(\w+) — ',l)
        if m: topic=m.group(1)
        if l.strip().startswith('│') and topic:
            c=[x.strip() for x in l.strip().strip('│').split('│')]
            if c[0]=='N': continue
            out[(topic,c[0])]=c
    return out
runs=[parse_pt(f) for f in sorted(glob.glob(R+'/pass-timing-*.txt'))]
print("\nPASS-TIMING medians (P1+P2,P3,P4,P5,P6,Total)")
for k in runs[0]:
    rows=[r[k] for r in runs]
    med=[st.median(ms(r[i]) for r in rows) for i in range(1,7)]
    print(f"{k[0]:10} N={k[1]:>7} "+" ".join(f"{x:8.2f}" for x in med))
