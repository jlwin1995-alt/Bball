"""Does a rotation player's absence redistribute minutes the way the team-240 rescale assumes?

    python -m pipeline.absence_test [--raw data/raw] [--every 2]

Walk-forward over the season. For each day, rotation players (15+ min, play 60%+ of games) who did not play are
treated as known Out, then the model is scored with RESCALE_STRENGTH = 1.0 (full rescale) down to 0.0 (none), with the
absences known and unknown. Finding on 2025-26: a weaker rescale wins on both minutes and fantasy points, in both halves;
an extra usage bump on top of it makes things worse. Hence RESCALE_STRENGTH = 0.25.
"""
import argparse
import pandas as pd, numpy as np, sys
from pipeline import config as C
from pipeline.model import project, _prep, fantasy
ap=argparse.ArgumentParser(); ap.add_argument("--raw",default="data/raw"); ap.add_argument("--every",type=int,default=2); A=ap.parse_args()
games=pd.read_csv(f"{A.raw}/games.csv",dtype={"pid":str}); C.SEASON=int(games["season"].max())
g=_prep(games); days=sorted(g["date"].unique())[40::A.every]
# fix absent sets once (from the kappa=1 pass)
C.RESCALE_STRENGTH=1.0
cache={}
for d in days:
    today=g[g.date==d]; slate=today[["team","opp","home"]].drop_duplicates("team").assign(date=d)
    hist=games[pd.to_datetime(games["date"])<d]
    P0,_=project(hist,slate,None,asof=d)
    ab=P0[(P0.min_s>=15)&(P0.pplay>=0.6)&(~P0.pid.isin(set(today.pid)))]
    cache[d]=(slate,hist,pd.DataFrame({"pid":ab.pid.astype(str),"name":ab["name"],"team":ab.team,"status":"Out"}),today.drop_duplicates("pid").set_index("pid"))
for k in (1.0,0.5,0.25,0.0):
    C.RESCALE_STRENGTH=k; rows=[]
    for d,(slate,hist,inj,act) in cache.items():
        for label,ij in (("known",inj),("unknown",None)):
            P,_=project(hist,slate,ij,asof=d); P=P[(P["min"]>=15)&~P["out"]&P.pid.isin(act.index)]
            a=act.loc[P.pid]
            rows.append(dict(half=int(d>=days[len(days)//2]),mode=label,min=(a["min"].to_numpy()-P["min"].to_numpy()),fp=(fantasy(a).to_numpy()-fantasy(P).to_numpy())))
    out={}
    for m in ("known","unknown"):
        mm=np.concatenate([r["min"] for r in rows if r["mode"]==m]); ff=np.concatenate([r["fp"] for r in rows if r["mode"]==m])
        h=lambda i:(round(np.abs(np.concatenate([r["min"] for r in rows if r["mode"]==m and r["half"]==i])).mean(),3),round(np.abs(np.concatenate([r["fp"] for r in rows if r["mode"]==m and r["half"]==i])).mean(),3))
        out[m]=(round(np.abs(mm).mean(),3),round(np.abs(ff).mean(),3),round(mm.mean(),2),"half1",h(0),"half2",h(1))
    print("kappa",k,"known absences: minMAE,fpMAE,minBias",out["known"],"| unknown:",out["unknown"],flush=True)
