#!/bin/bash
# Diagnostic: is the warroom API token valid, who does it authenticate as, and what does /api/state return?
# Usage: diag.sh <dir containing .token> [player_id]   Output: stdout only (token is never printed).
D="$1"; T=$(cat "$D/.token"); B="${WARROOM_URL:?Set WARROOM_URL to your warroom address first}"
hit(){ printf "%-34s " "$1"; curl -sS -m 60 -o "$D/out/diag_body.tmp" -D "$D/out/diag_hdr.tmp" -w "HTTP %{http_code}  %{size_download} bytes\n" -H "Authorization: Bearer $2" "$B$1"; }
echo "== valid token =="; for p in /api/stats /api/live "/api/players?id=${2:-1}" "/api/boards?board=cells&limit=3" /api/state; do hit "$p" "$T"; done
echo; echo "== bad token (control) =="; hit /api/stats "wr_invalid_control_token"
echo; echo "== no auth (control) =="; printf "%-34s " /api/stats; curl -sS -m 30 -o /dev/null -w "HTTP %{http_code}\n" "$B/api/stats"
echo; echo "== response headers on /api/state (names only, no cookies) =="
curl -sS -m 90 -o "$D/out/diag_state.json" -D "$D/out/diag_hdr.tmp" -H "Authorization: Bearer $T" "$B/api/state"; grep -viE '^(set-cookie|authorization)' "$D/out/diag_hdr.tmp" | head -25
python3 -I - "$D" <<'PY'
import json,sys,os
D=sys.argv[1]
s=json.load(open(os.path.join(D,"out","diag_state.json")))
print("\n== /api/state content ==")
print("authenticates as:",s['meta'].get('username'),"| gang:",s['meta'].get('gang'),"| last_poll:",s['meta'].get('last_poll'))
c=s['cells']; en=[x for x in c if x['status']=='enemy']
print("cells:",len(c),"| enemy:",len(en),"| enemy with owner==0:",sum(1 for x in en if x.get('owner')==0),"| names map size:",len(s['names']))
print("mine cells with real owner:",sum(1 for x in c if x['status']=='mine' and x.get('owner')),"of",sum(1 for x in c if x['status']=='mine'))
print("events:",len(s['events']),"| sample event keys:",sorted(s['events'][0].keys()) if s['events'] else None)
PY
echo; echo "== token management endpoints present in API docs =="; curl -sS -m 30 -H "Authorization: Bearer $T" "$B/openapi.json" | python3 -I -c "import json,sys; print([p for p in json.load(sys.stdin)['paths'] if 'account' in p or 'token' in p])"
