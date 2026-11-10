import csv, sys, statistics as st, datetime as dt
from collections import defaultdict, Counter
path=sys.argv[1]
TARGET=sys.argv[2] if len(sys.argv)>2 else None   # username to analyse in detail (optional)
rows=list(csv.DictReader(open(path, newline='', encoding='utf-8')))
print("rows",len(rows),"| columns",list(rows[0].keys()))
print("boards:",Counter(r['board'] for r in rows)); print("sources:",Counter(r['source'] for r in rows))
P=lambda s: dt.datetime.fromisoformat(s.replace('Z','')[:19])
hist=[r for r in rows if r['source']=='boards_history' and r['board']=='all_time']
by=defaultdict(dict)
for r in hist:
    try: by[(int(r['player_id']),r['username'])][P(r['sample_ts'])]=(int(r['wifi']),int(r['ble']),int(r['rank']))
    except Exception: pass
print("\nCOVERAGE (all_time hourly history, per player):")
for (pid,n),d in sorted(by.items()):
    ts=sorted(d); span=(ts[-1]-ts[0]).total_seconds()/86400
    gaps=[(ts[i-1],ts[i]) for i in range(1,len(ts)) if (ts[i]-ts[i-1]).total_seconds()>5400]
    print(f"  {n:20} {len(ts):5} samples {ts[0]:%m-%d %H:%M} -> {ts[-1]:%m-%d %H:%M} ({span:.1f}d) gaps>1.5h: {len(gaps)}")
if not TARGET: sys.exit('\nGive a username as the 2nd argument for the per-player breakdown: python3 boards_analysis.py boards_log.csv USERNAME')
k=[(pid,n) for (pid,n) in by if n==TARGET][0]
d=by[k]; ts=sorted(d)
steps=[]
for i in range(1,len(ts)):
    if (ts[i]-ts[i-1]).total_seconds()<=5400:
        steps.append((ts[i],d[ts[i]][0]-d[ts[i-1]][0],d[ts[i]][1]-d[ts[i-1]][1]))
print(f"\n{TARGET}: {len(steps)} contiguous hourly steps")
print("per day (UTC): date | wifi gain | ble gain | total | median hourly ble | hours>5k | hours<1.5k")
days=defaultdict(list)
for t,w,b in steps: days[t.date()].append((w,b))
for dd in sorted(days):
    v=days[dd]; W=sum(x[0] for x in v); B=sum(x[1] for x in v)
    med=st.median(x[1] for x in v); big=sum(1 for x in v if x[0]+x[1]>5000); quiet=sum(1 for x in v if x[0]+x[1]<1500)
    print(f"  {dd} | {W:>9,} | {B:>9,} | {W+B:>9,} | {med:>6.0f} | {big:>2} | {quiet:>2}  ({len(v)}h)")
tot=[w+b for _,w,b in steps]
quiet=[(t,w,b) for t,w,b in steps if w+b<2500]
print(f"\nquiet hours (<2.5k total): {len(quiet)}/{len(steps)}; their median wifi {st.median(w for _,w,b in quiet):.0f} ble {st.median(b for _,w,b in quiet):.0f}; mean ble {st.mean(b for _,w,b in quiet):.0f}; stdev {st.pstdev(b for _,w,b in quiet):.0f}")
big=[(t,w,b) for t,w,b in steps if w+b>=2500]
share_big=sum(w+b for _,w,b in big)/max(1,sum(tot))
print(f"big-upload hours (>=2.5k): {len(big)} = {share_big*100:.0f}% of all gain; trickle share {100-share_big*100:.0f}%")
print("quiet-hour median ble by week:")
wk=defaultdict(list)
for t,w,b in quiet: wk[t.isocalendar()[1]].append(b)
for w_,v in sorted(wk.items()): print(f"  ISO week {w_}: median {st.median(v):.0f}/h, n={len(v)}")
print("quiet-hour median ble by UTC hour of day:")
hh=defaultdict(list)
for t,w,b in quiet: hh[t.hour].append(b)
print("  ",{h:int(st.median(v)) for h,v in sorted(hh.items())})
print("\nlargest 12 hourly steps (ts, wifi, ble):")
for t,w,b in sorted(steps,key=lambda s:-(s[1]+s[2]))[:12]: print(f"  {t:%m-%d %H:%M}  wifi {w:>8,}  ble {b:>8,}")
# overlap: do trickle hours continue during big-upload days / any gaps in trickle?
qs=sorted(t for t,_,_ in quiet)
zero=[(t,w,b) for t,w,b in steps if b<100]
print(f"\nhours with ble gain <100 (trickle absent): {len(zero)}", [f"{t:%m-%d %H:%M}" for t,_,_ in zero[:10]])
print("negative steps (counts dropped):",[(f"{t:%m-%d %H:%M}",w,b) for t,w,b in steps if w<0 or b<0][:10])
# first and last sample totals
a,b_=d[ts[0]],d[ts[-1]]
print(f"\n{TARGET} wifi {a[0]:,}->{b_[0]:,} ble {a[1]:,}->{b_[1]:,} over {(ts[-1]-ts[0]).total_seconds()/86400:.1f}d")
