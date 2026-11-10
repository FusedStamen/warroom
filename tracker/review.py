import json, sys, os
D=os.path.join(sys.argv[1],"out")
L=lambda n: json.load(open(os.path.join(D,n)))
watch={int(k):v for k,v in L("watch.json").items()}
st=L("state.json"); print("STATE meta:",{k:st['meta'][k] for k in ('gang','footprint_cells','my_aps_total','last_poll')})
def board(b):
    d=L(f"board_{b}.json"); return d, {e['player_id']:e for e in d['entries']}
for b in ("cells","all_time","week","today"):
    d,m=board(b)
    print(f"\n== board {b} sampled {d.get('sampled_at')} (top {len(d['entries'])}) ==")
    for pid,n in watch.items():
        e=m.get(pid)
        if e: print(f"  {n:20} rank {e['rank']:>3} value {e['value']:>10,}  wifi {e.get('wifi')} ble {e.get('ble')}")
        else: print(f"  {n:20} not in top {len(d['entries'])}")
print("\n== held cells/APs (players history) ==")
for pid,n in watch.items():
    p=L(f"player_{pid}.json"); c=p['current']; h=sorted(p['history'],key=lambda x:x['ts'])
    a,b=h[0],h[-1]; days=max(1e-9,(__import__('datetime').datetime.fromisoformat(b['ts'])-__import__('datetime').datetime.fromisoformat(a['ts'])).total_seconds()/86400)
    print(f"  {n:20} gang={str(c.get('gang'))[:22]:22} cells {a['cells']}->{b['cells']} aps {a['aps']:,}->{b['aps']:,} (+{b['aps']-a['aps']:,} over {days:.1f}d = {(b['aps']-a['aps'])/days:,.0f}/day)")
print("\n== board history (hourly ~2d), all_time ==")
import datetime as dt
for pid,n in watch.items():
    h=L(f"hist_all_time_{pid}.json")
    hh=h.get('history') if isinstance(h,dict) else None
    if not hh: print(f"  {n:20} no history"); continue
    hh=sorted(hh,key=lambda x:x['ts']); a,b=hh[0],hh[-1]
    days=(dt.datetime.fromisoformat(b['ts'])-dt.datetime.fromisoformat(a['ts'])).total_seconds()/86400
    dw=(b['wifi']-a['wifi']); dbl=(b['ble']-a['ble'])
    steps=[(hh[i]['wifi']-hh[i-1]['wifi'], hh[i]['ble']-hh[i-1]['ble'], hh[i]['ts']) for i in range(1,len(hh))]
    big=sorted(steps,key=lambda s:-(s[0]+s[1]))[:2]
    print(f"  {n:20} {a['ts'][5:16]}->{b['ts'][5:16]} ({days:.1f}d) wifi +{dw:,} ble +{dbl:,} => {dw/days:,.0f} wifi/d, {dbl/days:,.0f} ble/d; biggest steps {[(s[2][5:16],s[0],s[1]) for s in big]}")
d,_=board("week")
print("\n== week board top 10 ==")
for e in d['entries'][:10]: print(f"  {e['rank']:>2} {str(e['username']):22} {e['value']:>10,} wifi {e.get('wifi')} ble {e.get('ble')}")
print("\n== all_time top 10 ==")
d,_=board("all_time")
for e in d['entries'][:10]: print(f"  {e['rank']:>2} {str(e['username']):22} {e['value']:>12,} wifi {e.get('wifi'):,} ble {e.get('ble'):,}")
import glob
for gf in sorted(glob.glob(os.path.join(D,"gang_*.json"))):
    g=json.load(open(gf))['history'][0]; print("\n"+os.path.basename(gf)[5:-5]+":",g)
