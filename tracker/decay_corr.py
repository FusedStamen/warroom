import os as _os, sys as _sys
WARROOM_URL = _os.environ.get("WARROOM_URL", "").rstrip("/")
if not WARROOM_URL:
    _sys.exit("Set the WARROOM_URL environment variable to your warroom address first, e.g.  WARROOM_URL=https://warroom.example.com")
import csv, sys, json, urllib.request, statistics as st, datetime as dt, os
from collections import defaultdict
D=sys.argv[1]; log=sys.argv[2]
tok=open(os.path.join(D,".token")).read().strip()
def get(p):
    r=urllib.request.Request(WARROOM_URL+p,headers={"Authorization":"Bearer "+tok,"User-Agent":"curl/8.5.0"})
    return json.load(urllib.request.urlopen(r,timeout=60))
P=lambda s: dt.datetime.fromisoformat(s.replace('Z','')[:19])
rows=list(csv.DictReader(open(log,newline='',encoding='utf-8')))
S=defaultdict(dict)
for r in rows:
    if r['board']=='all_time':
        try: S[int(r['player_id'])][P(r['sample_ts'])]=int(r['wifi'])
        except Exception: pass
cut=dt.datetime(2026,10,23)
out=[]
for pid,d in S.items():
    ts=sorted(t for t in d if t>=cut)
    if len(ts)<100: continue
    downs=sum(min(0,d[ts[i]]-d[ts[i-1]]) for i in range(1,len(ts)))
    ups=sum(max(0,d[ts[i]]-d[ts[i-1]]) for i in range(1,len(ts)))
    try: h=sorted(get(f"/api/players?id={pid}")['history'],key=lambda x:x['ts'])
    except Exception as e: continue
    h=[x for x in h if P(x['ts'])>=cut]
    if len(h)<20: continue
    out.append((pid,downs,ups,h[-1]['cells']-h[0]['cells'],h[-1]['aps']-h[0]['aps'],h[0]['cells'],h[-1]['gang']))
print(f"{'id':>5} {'board wifi downs':>16} {'board wifi ups':>14} {'d held cells':>12} {'d held aps':>11} {'cells':>6}  gang")
for o in sorted(out,key=lambda x:x[1])[:60]: print(f"{o[0]:>5} {o[1]:>16,} {o[2]:>14,} {o[3]:>12,} {o[4]:>11,} {o[5]:>6}  {str(o[6])[:24]}")
import math
xs=[o[1] for o in out]; ys=[o[4] for o in out]; zs=[o[3] for o in out]
def corr(a,b):
    ma,mb=st.mean(a),st.mean(b); 
    return sum((x-ma)*(y-mb) for x,y in zip(a,b))/math.sqrt(sum((x-ma)**2 for x in a)*sum((y-mb)**2 for y in b))
print(f"\ncorr(board wifi downs, d held aps) = {corr(xs,ys):.2f} ; corr(board wifi downs, d held cells) = {corr(xs,zs):.2f}; n={len(out)}")
