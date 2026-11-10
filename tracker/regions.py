import json, sys, os, statistics
from collections import Counter, defaultdict
D=os.path.join(sys.argv[1],"out")
L=lambda n: json.load(open(os.path.join(D,n)))
st=L("state.json"); names=st['names']; cells=st['cells']
byname={v:int(k) for k,v in names.items() if v}
# players to study: top all_time + top week + watched
ids=[]
for b in ("all_time","week"):
    for e in L(f"board_{b}.json")['entries'][:12]:
        if e['player_id'] not in ids: ids.append(e['player_id'])
for k in L("watch.json"):
    if int(k) not in ids: ids.append(int(k))
by=defaultdict(list)
for c in cells:
    if c.get('owner') is not None: by[c['owner']].append(c)
def region(lat,lon):
    if -170<lon<-50 and 15<lat<72:
        return "N.America"
    if -12<lon<45 and 34<lat<72: return "Europe"
    if 60<lon<150 and -12<lat<55: return "Asia"
    if 110<lon<180 and -50<lat<-8: return "Oceania"
    return "other"
def cl(lat,lon): return (round(lat*2)/2, round(lon*2)/2)   # ~0.5 degree (~50 km) blocks
print(f"{'player':22}{'tot cells':>9}{'visible':>8}{'vis%':>6}{'med held/cell':>14}{'p90':>8}  regions (visible cells) | top 50km blocks")
for pid in ids:
    n=names.get(str(pid)) or str(pid)
    try: tot=L(f"player_{pid}.json")['current']['cells']
    except Exception:
        tot=None
    cs=by.get(pid,[])
    if not cs and tot is None: continue
    counts=[c['count'] for c in cs if c.get('count')]
    reg=Counter()
    blk=Counter()
    for c in cs:
        lat=(c['b'][0][0]+c['b'][1][0])/2; lon=(c['b'][0][1]+c['b'][1][1])/2
        reg[region(lat,lon)]+=1; blk[cl(lat,lon)]+=1
    med=statistics.median(counts) if counts else 0
    p90=sorted(counts)[int(len(counts)*0.9)] if counts else 0
    vp=f"{100*len(cs)/tot:.0f}%" if tot else "n/a"
    print(f"{n[:21]:22}{(tot if tot is not None else '-'):>9}{len(cs):>8}{vp:>6}{med:>14,.0f}{p90:>8,}  {dict(reg)} | {[(k,v) for k,v in blk.most_common(4)]}")
