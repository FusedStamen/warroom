import csv, sys, statistics as st, datetime as dt
from collections import defaultdict
rows=list(csv.DictReader(open(sys.argv[1],newline='',encoding='utf-8')))
P=lambda s: dt.datetime.fromisoformat(s.replace('Z','')[:19])
S=defaultdict(dict); ids={}
for r in rows:
    if r['board']!='all_time': continue
    try:
        S[r['username']][P(r['sample_ts'])]=(int(r['wifi']),int(r['ble'])); ids[r['username']]=int(r['player_id'])
    except Exception: pass
print(f"{'id':>5} {'span d':>6} {'n':>4} | {'%intervals wifi down':>20} {'median down step':>17} {'sum of downs':>13} {'net wifi':>10} | {'%intervals ble down':>19} {'sum ble downs':>14} | start wifi")
for n in sorted(S,key=lambda x:ids[x]):
    ts=sorted(S[n]); 
    if len(ts)<100: continue
    dw=[];db=[]
    for i in range(1,len(ts)):
        h=(ts[i]-ts[i-1]).total_seconds()/3600
        if not 0<h<=12: continue
        dw.append(S[n][ts[i]][0]-S[n][ts[i-1]][0]); db.append(S[n][ts[i]][1]-S[n][ts[i-1]][1])
    down=[x for x in dw if x<0]; bdown=[x for x in db if x<0]
    span=(ts[-1]-ts[0]).total_seconds()/86400
    print(f"{ids[n]:>5} {span:>6.1f} {len(dw):>4} | {100*len(down)/len(dw):>19.0f}% {st.median(down) if down else 0:>17,.0f} {sum(down):>13,} {S[n][ts[-1]][0]-S[n][ts[0]][0]:>10,} | {100*len(bdown)/len(db):>18.0f}% {sum(bdown):>14,} | {S[n][ts[0]][0]:,}")
