"""ICT Full Context strategy for research/backtesting.

Deterministic, no look-ahead. Uses OHLCV/taker-buy proxy for footprint/orderflow
and a depth-free Hyper-Liquidity proxy. Fundamental/news is neutral unless a
TIMESTAMPED sidecar is supplied; no future news is fabricated.
"""
from __future__ import annotations
import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd

LONDON=ZoneInfo('Europe/London'); NEW_YORK=ZoneInfo('America/New_York'); TOKYO=ZoneInfo('Asia/Tokyo')

def _ema(s,n): return s.ewm(span=n, adjust=False, min_periods=n).mean()
def _atr(df,n=14):
    pc=df.close.shift(1); tr=pd.concat([(df.high-df.low),(df.high-pc).abs(),(df.low-pc).abs()],axis=1).max(axis=1)
    return tr.ewm(alpha=1/n,adjust=False,min_periods=n).mean()

def htf_bias(df15):
    """Resample completed 15m bars into 4H/1D; asof current bar only."""
    x=df15.set_index('dt')[['open','high','low','close','volume']]
    out=[]
    for rule in ['4h','1D']:
        r=x.resample(rule, label='right', closed='left').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'}).dropna()
        r['e50']=_ema(r.close,50); r['e200']=_ema(r.close,200)
        out.append(r)
    return out

def session(dt):
    l=dt.astimezone(LONDON); n=dt.astimezone(NEW_YORK); t=dt.astimezone(TOKYO)
    # Session definitions in local clock; DST handled by zoneinfo.
    # London 08:00-17:00 local; NY 08:00-17:00 local.
    london=8<=l.hour<17
    ny=8<=n.hour<17
    asia=9<=t.hour<18
    overlap=london and ny
    if overlap: return 'LONDON_NY_OVERLAP',1.0
    if asia and london: return 'ASIA_EUROPE_OVERLAP',0.86
    if london: return 'LONDON',0.88
    if ny: return 'NEW_YORK',0.92
    if asia: return 'ASIA',0.72
    return 'OFF_SESSION',0.0

def _asof_bias(htf, dt):
    vals=[]
    for r in htf:
        q=r.loc[r.index<=dt]
        if len(q)<200: vals.append(None)
        else:
            row=q.iloc[-1]
            vals.append('BULL' if row.e50>row.e200 else 'BEAR')
    return vals

def _fvg(df,i):
    if i<2: return None
    if df.low.iloc[i] > df.high.iloc[i-2]: return ('bullish',df.high.iloc[i-2],df.low.iloc[i])
    if df.high.iloc[i] < df.low.iloc[i-2]: return ('bearish',df.high.iloc[i],df.low.iloc[i-2])
    return None

def _sweep(df,i,look=20):
    if i<look+2: return None
    ph=df.high.iloc[i-look:i].max(); pl=df.low.iloc[i-look:i].min()
    if df.low.iloc[i] < pl and df.close.iloc[i] > pl: return ('bullish',pl,float(df.low.iloc[i]))
    if df.high.iloc[i] > ph and df.close.iloc[i] < ph: return ('bearish',ph,float(df.high.iloc[i]))
    return None

def _mss(df,i,direction,look=8):
    if i<look+3: return False
    # Structure shift is close through the most recent local extreme after sweep.
    if direction=='BUY': return df.close.iloc[i] > df.high.iloc[i-look:i].max()
    return df.close.iloc[i] < df.low.iloc[i-look:i].min()

def _displacement(df,i,atr):
    if i<1 or not np.isfinite(atr) or atr<=0: return 0.0
    body=abs(df.close.iloc[i]-df.open.iloc[i]); rng=df.high.iloc[i]-df.low.iloc[i]
    if rng<=0: return 0.0
    return (body/atr) * (body/rng)

def _footprint(df,i):
    vol=max(float(df.volume.iloc[i]),1e-12); tb=float(df.taker_buy_volume.iloc[i])
    delta=2*(tb/vol)-1
    # cumulative delta divergence proxy over 8 bars
    start=max(0,i-7); d_now=sum(2*(df.taker_buy_volume.iloc[j]/max(df.volume.iloc[j],1e-12))-1 for j in range(start,i+1))
    return delta,d_now

def _hli_series(df, atrs):
    vm=df.volume.rolling(20).mean().shift(1); vs=df.volume.rolling(20).std().shift(1)
    vz=(df.volume-vm)/vs.replace(0,np.nan)
    rv=(df.high-df.low)/atrs.replace(0,np.nan)
    return (50+12*vz.fillna(0)+18*(rv.fillna(1)-1)).clip(0,100)

def signal_at(df,i,htf4,htf1, atrs=None, hli_s=None, fundamental=0.0):
    """Find a confirmed ICT setup ending at bar i.
    Sweep is allowed up to 4 bars before confirmation; this avoids the
    unrealistic requirement that sweep/MSS/FVG all occur in one candle.
    """
    dt=df.dt.iloc[i]; s,ss=session(dt)
    if ss<=0 or i<250: return None
    b4=htf4.iloc[i]['bias']; b1=htf1.iloc[i]['bias']
    if pd.isna(b4) or pd.isna(b1) or b4!=b1: return None
    bias=b4
    atr=float(atrs.iloc[i])
    if not np.isfinite(atr) or atr<=0:return None
    sw=None; sw_i=None
    for k in range(i,max(i-4,20)-1,-1):
        z=_sweep(df,k,20)
        if z:
            # must be same HTF bias direction
            if (z[0]=='bullish' and bias=='BULL') or (z[0]=='bearish' and bias=='BEAR'):
                sw=z; sw_i=k; break
    if not sw or sw_i==i:return None
    direction='BUY' if sw[0]=='bullish' else 'SELL'
    # Premium/discount at confirmation relative to prior dealing range.
    hi=df.high.iloc[i-40:i].max(); lo=df.low.iloc[i-40:i].min(); mid=(hi+lo)/2; c=float(df.close.iloc[i])
    if direction=='BUY' and c>=mid:return None
    if direction=='SELL' and c<=mid:return None
    # Fibonacci retracement confirmation: use only the completed 40-bar
    # dealing range before the signal. OTE = 61.8%-78.6%.
    fib_rng=hi-lo
    if fib_rng<=0:return None
    if direction=='BUY':
        f618=hi-fib_rng*0.618; f786=hi-fib_rng*0.786
        fib_ote=(f786<=c<=f618)
        fib_mid=(hi-fib_rng*0.50<=c<f618)
    else:
        f618=lo+fib_rng*0.618; f786=lo+fib_rng*0.786
        fib_ote=(f618<=c<=f786)
        fib_mid=(f618<c<=lo+fib_rng*0.50)
    disp=max(_displacement(df,j,float(atrs.iloc[j])) for j in range(sw_i+1,i+1))
    if disp<0.65:return None
    if not _mss(df,i,direction,8):return None
    fv=None
    for j in range(max(2,sw_i+1),i+1):
        z=_fvg(df,j)
        if z and ((direction=='BUY' and z[0]=='bullish') or (direction=='SELL' and z[0]=='bearish')): fv=z
    if not fv:return None
    delta,cvd=_footprint(df,i); hli=float(hli_s.iloc[i])
    fp_ok=(delta>=0.03 and cvd>0) if direction=='BUY' else (delta<=-0.03 and cvd<0)
    if direction=='BUY' and fundamental<=-3:return None
    if direction=='SELL' and fundamental>=3:return None
    score=15+15+12+10+10+8+8+5+(10 if fib_ote else 0)+(4 if fib_mid else 0)+(8 if hli>=60 else 0)+(5 if fp_ok else 0)
    if ss>=0.92: score+=3
    if (direction=='BUY' and fundamental>1) or (direction=='SELL' and fundamental<-1): score+=5
    if score<65:return None
    buf=0.10*atr
    sl=(sw[2]-buf) if direction=='BUY' else (sw[2]+buf)
    entry=float(df.close.iloc[i]); risk=abs(entry-sl)
    if risk<=0:return None
    opp=hi if direction=='BUY' else lo
    tp=max(opp,entry+2*risk) if direction=='BUY' else min(opp,entry-2*risk)
    max_tp=entry+4*risk if direction=='BUY' else entry-4*risk
    tp=min(tp,max_tp) if direction=='BUY' else max(tp,max_tp)
    rr=abs(tp-entry)/risk
    if rr<1.8:return None
    return {'direction':direction,'entry':entry,'sl':float(sl),'tp':float(tp),'risk':risk,'score':score,'session':s,'fundamental':fundamental,'footprint_delta':delta,'hli':hli,'sweep':sw[0],'sweep_time':df.dt.iloc[sw_i],'fvg':fv[0],'fib_ote':fib_ote,'fib_zone':'OTE' if fib_ote else ('MID' if fib_mid else 'NONE'),'bias':bias,'rr':rr}

def simulate(df, htf4, htf1, fundamental_series=None):
    trades=[]; i=250
    atrs=_atr(df); hli_s=_hli_series(df,atrs)
    # precompute as-of HTF biases aligned to 15m bars
    for r in (htf4, htf1):
        r['bias']=np.where(r.e50>r.e200,'BULL','BEAR')
    idx=pd.DatetimeIndex(df.dt)
    htf4=htf4.reindex(htf4.index.union(idx)).sort_index().ffill().reindex(idx)
    htf1=htf1.reindex(htf1.index.union(idx)).sort_index().ffill().reindex(idx)
    while i<len(df)-1:
        f=0.0
        if fundamental_series is not None:
            q=fundamental_series.loc[fundamental_series.index<=df.dt.iloc[i]]
            if len(q): f=float(q.iloc[-1])
        sig=signal_at(df,i,htf4,htf1,atrs,hli_s,f)
        if not sig: i+=1; continue
        # Enter at next 15m open to avoid same-bar lookahead.
        ei=i+1; entry=float(df.open.iloc[ei]); direction=sig['direction']; sl=sig['sl']; tp=sig['tp']; risk=abs(entry-sl)
        if risk<=0:i+=1;continue
        mfe=0.0; mae=0.0; exit_i=None; exit_price=None; status='OPEN'
        for j in range(ei,min(len(df),ei+97)):
            hi=float(df.high.iloc[j]); lo=float(df.low.iloc[j])
            if direction=='BUY':
                fav=(hi-entry)/risk; adv=(entry-lo)/risk
                hit_sl=lo<=sl; hit_tp=hi>=tp
            else:
                fav=(entry-lo)/risk; adv=(hi-entry)/risk
                hit_sl=hi>=sl; hit_tp=lo<=tp
            mfe=max(mfe,fav); mae=max(mae,adv)
            if hit_sl or hit_tp:
                # conservative ambiguity
                if hit_sl:
                    exit_price=sl; status='LOSS'
                else:
                    exit_price=tp; status='WIN'
                exit_i=j; break
        if exit_i is None:
            i+=1; continue
        r=((exit_price-entry)/risk) if direction=='BUY' else ((entry-exit_price)/risk)
        trades.append({**sig,'entry':entry,'entry_time':df.dt.iloc[ei],'exit_time':df.dt.iloc[exit_i],'exit_price':exit_price,'result':status,'r_multiple':r,'mfe_r':mfe,'mae_r':mae})
        i=exit_i+1
    return pd.DataFrame(trades)
