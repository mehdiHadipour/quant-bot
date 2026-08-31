"""Leakage-safe bar-volume profile utilities.
Uses only bars strictly before the signal bar. With OHLCV+taker-buy data this is
an approximation to true volume-at-price; true tick/price-level footprint needs
trade/LOB data and is not fabricated here.
"""
from __future__ import annotations
import numpy as np

def profile_levels(high, low, close, volume, bins=40, value_area=0.70):
    high=np.asarray(high,float); low=np.asarray(low,float); close=np.asarray(close,float); volume=np.asarray(volume,float)
    if len(close)<8: return None
    lo=float(np.nanmin(low)); hi=float(np.nanmax(high))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi<=lo: return None
    edges=np.linspace(lo,hi,bins+1)
    typical=(high+low+close)/3.0
    idx=np.clip(np.searchsorted(edges,typical,side='right')-1,0,bins-1)
    hist=np.bincount(idx,weights=np.nan_to_num(volume,nan=0.0),minlength=bins).astype(float)
    if hist.sum()<=0: return None
    poc=int(np.argmax(hist)); target=hist.sum()*float(value_area)
    included={poc}; total=hist[poc]; left=poc-1; right=poc+1
    while total<target and (left>=0 or right<bins):
        lv=hist[left] if left>=0 else -1; rv=hist[right] if right<bins else -1
        if rv>lv:
            included.add(right); total+=rv; right+=1
        elif lv>rv:
            included.add(left); total+=lv; left-=1
        else:
            # tie: closer row; if equal, above
            if right<bins:
                included.add(right); total+=rv; right+=1
            elif left>=0:
                included.add(left); total+=lv; left-=1
            else: break
    vah=max(included); val=min(included)
    mids=(edges[:-1]+edges[1:])/2
    # HVN/LVN are local volume peaks/valleys, used as context only.
    hvn=float(mids[poc])
    lv_candidates=[j for j in range(1,bins-1) if hist[j]<=hist[j-1] and hist[j]<=hist[j+1]]
    lvn=float(mids[min(lv_candidates,key=lambda j:abs(j-poc))]) if lv_candidates else float(mids[np.argmin(hist)])
    return {'poc':float(mids[poc]),'vah':float(edges[vah+1]),'val':float(edges[val]),'hvn':hvn,'lvn':lvn,'range_low':lo,'range_high':hi,'total_volume':float(hist.sum())}

def context(df,i,lookback=48,bins=40):
    # i is the signal bar; strictly exclude i to avoid look-ahead.
    s=max(0,i-lookback); e=i
    p=profile_levels(df.high.iloc[s:e],df.low.iloc[s:e],df.close.iloc[s:e],df.volume.iloc[s:e],bins=bins)
    if p is None: return {'ok':False}
    c=float(df.close.iloc[i]); rng=max(p['range_high']-p['range_low'],1e-12)
    dist_poc=abs(c-p['poc'])/rng
    return {'ok':True,**p,'close':c,'dist_poc':dist_poc,
            'inside_value':p['val']<=c<=p['vah'],
            'above_value':c>p['vah'],'below_value':c<p['val'],
            'near_val':abs(c-p['val'])<=0.12*rng,'near_vah':abs(c-p['vah'])<=0.12*rng,
            'above_poc':c>=p['poc'],'below_poc':c<=p['poc']}
