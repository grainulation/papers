import re,sys,glob,statistics as st
R=sys.argv[1]
per={}
for f in sorted(glob.glob(R+'/pass-timing-schulze-log-*.txt')):
    topic=None; buf=[]
    for l in open(f):
        m=re.match(r'\s+(\w+) — ',l)
        if m: topic=m.group(1); buf=[]
        m=re.match(r'SCHULZE n=(\d+) ns=(\d+)',l)
        if m: buf.append((int(m.group(1)),int(m.group(2)))); continue
        if l.strip().startswith('│') and topic:
            c=[x.strip() for x in l.strip().strip('│').split('│')]
            if c[0]=='N': continue
            per.setdefault((topic,c[0]),[]).append((buf,c)); buf=[]
for k,v in per.items():
    if k[1]!='10,000': continue
    tot=[sum(ns for _,ns in b)/1e6 for b,_ in v]
    print(k, "sets(n):",[n for n,_ in v[0][0]], "schulze ms per run:",[round(t,1) for t in tot],"median",round(st.median(tot),1))
    print("   per-set ms (run1):",[round(ns/1e6,1) for _,ns in v[0][0]])
    print("   rows:",[c for _,c in v])
