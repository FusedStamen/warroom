import json,sys,math,os,urllib.request
os.makedirs('route',exist_ok=True)
S=json.load(open('out/state.json'))
visited=set();known={}
for c in S['cells']:
    i=round(c['b'][0][0]/0.02); j=round(c['b'][0][1]/0.02)
    known[(i,j)]=c['my_aps']
    if c['my_aps']>0: visited.add((i,j))
def osrm(pts):
    co=";".join(f"{lo},{la}" for la,lo in pts)
    u=f"https://router.project-osrm.org/route/v1/driving/{co}?overview=full&geometries=geojson&steps=false"
    r=json.load(urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"curl/8.5.0"}),timeout=60))
    rt=r['routes'][0]; return rt['geometry']['coordinates'],rt['distance']/1609.34,rt['duration']/60
def cells(coords):
    out=[];seen=set()
    for (lo1,la1),(lo2,la2) in zip(coords,coords[1:]):
        n=max(1,int(max(abs(la2-la1),abs(lo2-lo1))/0.002))
        for k in range(n+1):
            la=la1+(la2-la1)*k/n; lo=lo1+(lo2-lo1)*k/n
            c=(math.floor(la/0.02),math.floor(lo/0.02))
            if c not in seen: seen.add(c); out.append(c)
    return out
def gpx(coords,name,path):
    with open(path,'w') as f:
        f.write('<?xml version="1.0"?><gpx version="1.1" creator="route_eval" xmlns="http://www.topografix.com/GPX/1/1"><trk><name>%s</name><trkseg>'%name)
        step=max(1,len(coords)//3000)
        for lo,la in coords[::step]: f.write(f'<trkpt lat="{la:.5f}" lon="{lo:.5f}"/>')
        f.write('</trkseg></trk></gpx>')
W={'Boston':(42.3601,-71.0589),'NB':(40.4862,-74.4518),'Prov':(41.824,-71.4128),'NewHaven':(41.3083,-72.9279),'Stamford':(41.0534,-73.5387),
'Hartford':(41.7658,-72.6734),'Danbury':(41.3948,-73.454),'Tarrytown':(41.0762,-73.8587),'Paterson':(40.9168,-74.1718),'Worcester':(42.2626,-71.8023),
'Springfield':(42.1015,-72.5898),'Philadelphia':(39.9526,-75.1652),'Trenton':(40.2171,-74.7429),'Edison':(40.5187,-74.4121),'Mystic':(41.3543,-71.9665),'OldSaybrook':(41.2918,-72.3762),'Bridgeport':(41.1792,-73.1894)}
R={
 'A_default':['Boston','NB'],
 'B_I95_coast':['Boston','Prov','NewHaven','Stamford','NB'],
 'C_Hartford_I84':['Boston','Hartford','Danbury','Tarrytown','Paterson','NB'],
 'D_Pike_Springfield_I91_I95':['Boston','Worcester','Springfield','NewHaven','Stamford','NB'],
 'E_Shoreline':['Boston','Prov','Mystic','OldSaybrook','Bridgeport','Stamford','NB'],
 'F_NB_to_Philly':['NB','Philadelphia'],
 'G_NB_to_Philly_viaTrenton':['NB','Trenton','Philadelphia'],
 'H_Philly_to_Edison':['Philadelphia','Edison'],
}
for k,v in R.items():
    try:
        co,mi,mn=osrm([W[x] for x in v])
    except Exception as e:
        print(k,'ERR',e); continue
    cs=cells(co)
    new=[c for c in cs if c not in visited]
    unlisted=[c for c in new if c not in known]
    print(f"{k:28s} {mi:5.0f} mi {mn:4.0f} min  cells crossed {len(cs):3d}  NEW presence {len(new):3d} (unlisted {len(unlisted)})  new per hour {len(new)/(mn/60):.0f}")
    gpx(co,k,f"route/{k}.gpx")

# ---- detour candidates: never-visited, ACTIVE (APs exist) cells within 1 cell of chosen legs
import csv
counts={}
for c in S['cells']:
    counts[(round(c['b'][0][0]/0.02),round(c['b'][0][1]/0.02))]=(c['count'],c['status'])
def near(cs,r=1):
    cand={}
    cset=set(cs)
    for (i,j) in cs:
        for di in range(-r,r+1):
            for dj in range(-r,r+1):
                n=(i+di,j+dj)
                if n in cset or n in visited or n not in counts: continue
                d=max(abs(di),abs(dj))
                cand[n]=min(cand.get(n,9),d)
    return cand
legs={'NB_out_A':['Boston','NB'],'NB_to_Philly':['NB','Philadelphia'],'Philly_to_Edison':['Philadelphia','Edison']}
rows=[]
for nm,v in legs.items():
    co,mi,mn=osrm([W[x] for x in v]); cs=cells(co)
    for (i,j),d in near(cs).items():
        cnt,st=counts[(i,j)]
        rows.append((nm,round((i+0.5)*0.02,4),round((j+0.5)*0.02,4),d,cnt,st))
    print(nm,'adjacent never-visited active cells:',sum(1 for r in rows if r[0]==nm))
with open('route/detour_cells.csv','w',newline='') as f:
    w=csv.writer(f); w.writerow(['leg','center_lat','center_lon','cells_off_route','enemy_aps_in_cell','status']); w.writerows(rows)
with open('route/detour_cells.gpx','w') as f:
    f.write('<?xml version="1.0"?><gpx version="1.1" creator="route_eval" xmlns="http://www.topografix.com/GPX/1/1">')
    for r in rows: f.write(f'<wpt lat="{r[1]}" lon="{r[2]}"><name>{r[0]} d{r[3]} aps{r[4]}</name></wpt>')
    f.write('</gpx>')
import collections
print(collections.Counter((r[0],r[3]) for r in rows))
