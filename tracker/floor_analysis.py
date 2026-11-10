import csv, sys, statistics as st, datetime as dt
from collections import defaultdict
rows=list(csv.DictReader(open(sys.argv[1],newline='',encoding='utf-8')))
NAMES=sys.argv[2:]   # usernames to compare; the first one also gets the daily breakdown
if not NAMES: sys.exit('Usage: python3 floor_analysis.py boards_log.csv USERNAME [USERNAME ...]')
P=lambda s: dt.datetime.fromisoformat(s.replace('Z','')[:19])
series=defaultdict(dict)   # name -> {ts:(wifi,ble)}
for r in rows:
    if r['board']!='all_time': continue
    try: series[r['username']][P(r['sample_ts'])]=(int(r['wifi']),int(r['ble']))
    except Exception: pass
def intervals(name):
    d=series[name]; ts=sorted(d); out=[]
    for i in range(1,len(ts)):
        h=(ts[i]-ts[i-1]).total_seconds()/3600
        if h<=0 or h>12: continue
        w=d[ts[i]][0]-d[ts[i-1]][0]; b=d[ts[i]][1]-d[ts[i-1]][1]
        out.append((ts[i],h,w,b))
    return out
def pct(v,p): v=sorted(v); return v[min(len(v)-1,int(len(v)*p))]
print("samples per player, span:")
for n in NAMES:
    iv=intervals(n); ts=sorted(series[n])
    print(f"  {n:16} {len(ts)} samples, median spacing {st.median((ts[i]-ts[i-1]).total_seconds()/3600 for i in range(1,len(ts))):.1f}h, {ts[0]:%m-%d}->{ts[-1]:%m-%d}")
print("\nPER-INTERVAL HOURLY RATE (total gain / hours), floor vs typical, by player:")
for n in NAMES:
    iv=intervals(n); r=[(w+b)/h for _,h,w,b in iv]; rb=[b/h for _,h,w,b in iv]; rw=[w/h for _,h,w,b in iv]
    print(f"  {n:16} n={len(iv):3}  rate/h: min {min(r):8,.0f} p10 {pct(r,.1):8,.0f} median {st.median(r):8,.0f} p90 {pct(r,.9):9,.0f}  | ble/h p10 {pct(rb,.1):7,.0f} wifi/h p10 {pct(rw,.1):6,.0f}")
iv=intervals(NAMES[0])
print("\n"+NAMES[0]+" daily (UTC date): wifi gain, ble gain, total | floor (p10 hourly rate that day) | n intervals")
day=defaultdict(list)
for t,h,w,b in iv: day[t.date()].append((h,w,b))
for d_ in sorted(day):
    v=day[d_]; W=sum(x[1] for x in v); B=sum(x[2] for x in v)
    rates=[(x[1]+x[2])/x[0] for x in v]; wr=[x[1]/x[0] for x in v]
    print(f"  {d_}  wifi {W:>8,} ble {B:>9,} total {W+B:>9,} | floor {min(rates):>6,.0f}/h (wifi floor {min(wr):>5,.0f}/h) | {len(v)}")
tot=sum(w+b for _,_,w,b in iv); hrs=sum(h for _,h,_,_ in iv)
fl=[(w+b)/h for _,h,w,b in iv]
quiet=[x for x in iv if (x[2]+x[3])/x[1]<2500]
print(f"\n{NAMES[0]} overall: {tot:,} gain over {hrs/24:.1f}d = {tot/hrs*24*7:,.0f}/week average")
print(f"intervals with rate < 2.5k/h: {len(quiet)}/{len(iv)}; their gain share: {100*sum(w+b for _,_,w,b in quiet)/tot:.0f}% of total; median ble/h {st.median(b/h for _,h,w,b in quiet):.0f}, wifi/h {st.median(w/h for _,h,w,b in quiet):.0f}")
print("quiet-interval median ble/h by calendar week (UTC):")
wk=defaultdict(list)
for t,h,w,b in quiet: wk[t.isocalendar()[1]].append(b/h)
for w_,v in sorted(wk.items()): print(f"  wk {w_}: median {st.median(v):6.0f}/h  min {min(v):6.0f}  max {max(v):6.0f}  n={len(v)}")
print("\nlargest 10 intervals (end ts, hours, wifi, ble):")
for t,h,w,b in sorted(iv,key=lambda x:-(x[2]+x[3]))[:10]: print(f"  {t:%m-%d %H:%M}  {h:.1f}h  wifi {w:>8,}  ble {b:>8,}")
