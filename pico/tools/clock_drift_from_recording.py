"""Read-only comparison of QuestLHSync QPC clock and Pico MONOTONIC copy times.

Q: PC send/receive seconds and device monotonic seconds.
U F: PC receiving timestamp (ns) and device copied_ns converted to us.
This DOES NOT determine real exposure time.
Python 3.10+, standard library only.
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import median

def pct(values, q):
    a=sorted(values)
    if not a:return None
    k=(len(a)-1)*q; i=int(k)
    return a[i]+(a[min(i+1,len(a)-1)]-a[i])*(k-i)

def analyze(path):
    pings=[];frames=defaultdict(list)
    for line in path.open(encoding="utf-8",errors="replace"):
        r=line.split()
        if len(r)>=5 and r[1]=="Q":
            try:s,e,dev=map(float,r[2:5])
            except ValueError:continue
            if e>=s:pings.append(((s+e)/2,(s+e)/2-dev,1000*(e-s)))
        elif len(r)>=8 and r[1:3]==["U","F"]:
            try:pc=int(r[0])/1e9;cam=int(r[3]);copied=int(r[5])/1e6
            except ValueError:continue
            if cam in (0,3,4,5):frames[cam].append((pc,copied))
    clean=[p for p in pings if p[2]<=10]
    if len(clean)<8:raise ValueError("At least 8 Q pings with RTT <=10ms are required")
    origin=clean[0][0];x=[q[0]-origin for q in clean];y=[q[1] for q in clean]
    xm=sum(x)/len(x);ym=sum(y)/len(y)
    slope=sum((a-xm)*(b-ym) for a,b in zip(x,y))/sum((a-xm)**2 for a in x)
    intercept=ym-slope*xm
    residuals=[abs((b-(intercept+slope*a))*1000) for a,b in zip(x,y)]
    out={"recording":path.name,"valid_pings":len(clean),"qpc_vs_android_drift_ppm":slope*1e6,
         "drift_ms_over_session":slope*(x[-1]-x[0])*1000,
         "median_ping_rtt_ms":median(q[2] for q in clean),
         "clock_fit_median_absolute_residual_ms":median(residuals),
         "copy_to_receive_ms":{}}
    for cam,rows in sorted(frames.items()):
        d=[(pc-(device+intercept+slope*(pc-origin)))*1000 for pc,device in rows]
        out["copy_to_receive_ms"][str(cam)]={"n":len(d),"median":median(d),
            "p10":pct(d,.1),"p90":pct(d,.9),"p99":pct(d,.99)}
    return out

if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument("recording",type=Path)
    a=ap.parse_args();r=analyze(a.recording);print(json.dumps(r,indent=2))
