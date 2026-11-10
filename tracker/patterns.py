import os as _os, sys as _sys
WARROOM_URL = _os.environ.get("WARROOM_URL", "").rstrip("/")
if not WARROOM_URL:
    _sys.exit("Set the WARROOM_URL environment variable to your warroom address first, e.g.  WARROOM_URL=https://warroom.example.com")
import json, os, sys, urllib.request, datetime as dt
D=sys.argv[1]; out=os.path.join(D,"out")
tok=open(os.path.join(D,".token")).read().strip()
def get(path):
    r=urllib.request.Request(WARROOM_URL+path, headers={"Authorization":"Bearer "+tok,"User-Agent":"curl/8.5.0"})
    return json.load(urllib.request.urlopen(r,timeout=60))
at=json.load(open(os.path.join(out,"board_all_time.json")))['entries']
wk=json.load(open(os.path.join(out,"board_week.json")))['entries']
ids=[]; 
for e in at[:10]+wk[:10]:
    if e['player_id'] not in ids: ids.append(e['player_id'])
name={e['player_id']:e['username'] for e in at+wk}
wkv={e['player_id']:e['value'] for e in wk}
print(f"{'player':16}{'week board':>11}{'2d wifi':>9}{'2d ble':>9}{'ble%':>6}{'top3 steps %':>13}{'active hrs/48':>14}{'max step':>10}")
for pid in ids:
    try: h=get(f"/api/boards?board=all_time&id={pid}")['history']
    except Exception as e: print(name[pid],'err',e); continue
    h=sorted(h,key=lambda x:x['ts'])
    if len(h)<10: print(f"{str(name[pid])[:15]:16} only {len(h)} samples"); continue
    steps=[(h[i]['wifi']-h[i-1]['wifi'], h[i]['ble']-h[i-1]['ble']) for i in range(1,len(h))]
    tot=[a+b for a,b in steps]
    gain=sum(t for t in tot if t>0)
    dw=sum(a for a,b in steps); db=sum(b for a,b in steps)
    top3=sum(sorted(tot,reverse=True)[:3])
    active=sum(1 for t in tot if t>50)
    print(f"{str(name[pid])[:15]:16}{wkv.get(pid,0):>11,}{dw:>9,}{db:>9,}{100*db/max(1,dw+db):>5.0f}%{100*top3/max(1,gain):>12.0f}%{active:>10}/{len(tot)}{max(tot):>10,}")
