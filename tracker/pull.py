import json, os, sys, urllib.request, urllib.parse
import os as _os, sys as _sys
WARROOM_URL = _os.environ.get("WARROOM_URL", "").rstrip("/")
if not WARROOM_URL:
    _sys.exit("Set the WARROOM_URL environment variable to your warroom address first, e.g.  WARROOM_URL=https://warroom.example.com")
BASE=WARROOM_URL
D=sys.argv[1]            # working dir holding .token and watchlist.json; out/ is written here
tok=open(os.path.join(D,".token")).read().strip()
def get(path, **q):
    url=BASE+path+("?"+urllib.parse.urlencode(q) if q else "")
    req=urllib.request.Request(url, headers={"Authorization":"Bearer "+tok,"User-Agent":"curl/8.5.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)
out=os.path.join(D,"out"); os.makedirs(out, exist_ok=True)
def save(name,obj): json.dump(obj, open(os.path.join(out,name),"w"))
save("state.json", get("/api/state"))
for b in ("all_time","week","today","cells","hunters","flock","arcade"):
    save(f"board_{b}.json", get("/api/boards", board=b))
# watchlist.json in the working dir:  {"players": {"123": "name", ...}, "gangs": ["Gang Name", ...]}
# Copy tracker/watchlist.example.json to start. Keep your real list out of the repository.
wl=json.load(open(os.path.join(D,"watchlist.json")))
watch={int(k):v for k,v in wl.get("players",{}).items()}
save("watch.json", watch)
for pid in watch:
    save(f"player_{pid}.json", get("/api/players", id=pid))
    for b in ("all_time","week","cells"):
        try: save(f"hist_{b}_{pid}.json", get("/api/boards", board=b, id=pid))
        except Exception as e: save(f"hist_{b}_{pid}.json", {"error":str(e)})
for g in wl.get("gangs",[]):
    save("gang_"+"".join(c if c.isalnum() else "_" for c in g)+".json", get("/api/gangs", name=g))
print("done")
