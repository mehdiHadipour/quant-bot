"""V30.9.2 unified backtest: calls the exact live analyze_market() decision function.
Only execution/exit simulation is different; signal logic is shared with live.
"""
from pathlib import Path
import os, json
import pandas as pd
import numpy as np
from concurrent.futures import ProcessPoolExecutor, as_completed

os.environ.setdefault('NEWS_ENABLED','0')
os.environ.setdefault('SMART_CONTEXT_MODE','backtest')

from indicators import analyze_market

ROOT=Path(__file__).resolve().parent
DATA=ROOT/'backtest_data'

def resample(df, rule):
    x=df.copy(); x['dt']=pd.to_datetime(x['open_time'],unit='ms',utc=True)
    x=x.set_index('dt')
    cols=['open','high','low','close','volume','taker_buy_volume']
    r=x[cols].resample(rule,label='right',closed='left').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum','taker_buy_volume':'sum'}).dropna().reset_index()
    r['open_time']=(r['dt'].astype('int64')//10**6).astype('int64')
    return r

def stats(tr):
    if tr.empty: return {}
    rs=tr.r_multiple.astype(float); wins=int((rs>0).sum()); losses=int((rs<0).sum())
    pf=float(rs[rs>0].sum()/(-rs[rs<0].sum())) if losses else float('inf')
    eq=rs.cumsum(); dd=float((eq.cummax()-eq).max())
    return dict(trades=len(tr),wins=wins,losses=losses,win_rate=100*wins/len(tr),net_r=float(rs.sum()),avg_r=float(rs.mean()),pf=pf,max_dd_r=dd)

def run_symbol(p):
    d=pd.read_csv(p).sort_values('open_time').reset_index(drop=True); d['dt']=pd.to_datetime(d.open_time,unit='ms',utc=True)
    h4=resample(d,'4h'); d1=resample(d,'1D')
    for x in (h4,d1):
        x['e50']=x.close.ewm(span=50,adjust=False,min_periods=50).mean(); x['e200']=x.close.ewm(span=200,adjust=False,min_periods=200).mean(); x['bias']=np.where(x.e50>x.e200,'BULL','BEAR')
    h4b=pd.merge_asof(d[['dt']],h4[['dt','bias']],on='dt',direction='backward')['bias']; d1b=pd.merge_asof(d[['dt']],d1[['dt','bias']],on='dt',direction='backward')['bias']
    ph=d.high.shift(1).rolling(20).max(); pl=d.low.shift(1).rolling(20).min(); vm=d.volume.shift(1).rolling(20).mean()
    sweep=((d.low<pl)&(d.close>pl))|((d.high>ph)&(d.close<ph)); breakout=((d.close>ph)&(d.volume>vm*1.8))|((d.close<pl)&(d.volume>vm*1.8))
    candidates=np.where((sweep|breakout)&(h4b==d1b)&pd.notna(h4b))[0]
    trades=[]; last_exit=-1
    for i in candidates:
        if i<250 or i>=len(d)-1 or i<last_exit: continue
        h1=d.iloc[:i+1].copy(); h4s=h4[h4.open_time<=int(d.open_time.iloc[i])].copy(); d1s=d1[d1.open_time<=int(d.open_time.iloc[i])].copy()
        if len(h1)<210 or len(h4s)<210 or len(d1s)<210: continue
        sig=analyze_market(d.iloc[max(0,i-19):i+1].copy(),h1,h4s,d1s,p.stem.replace('_1h',''),funding_rate=None)
        if not sig: continue
        ei=i+1; entry=float(d.open.iloc[ei]); risk=float(sig['atr'])*1.8; sl=entry-risk if sig['direction']=='BUY' else entry+risk; look=d.iloc[max(0,i-40):i]
        tp=max(float(look.high.max()),entry+2*risk) if sig['direction']=='BUY' else min(float(look.low.min()),entry-2*risk); tp=min(tp,entry+4*risk) if sig['direction']=='BUY' else max(tp,entry-4*risk)
        if abs(tp-entry)/risk<1.8: continue
        ex=xp=None; status=None; mfe=mae=0.0
        for j in range(ei,min(len(d),ei+97)):
            hi=float(d.high.iloc[j]); lo=float(d.low.iloc[j])
            if sig['direction']=='BUY': mfe=max(mfe,(hi-entry)/risk); mae=max(mae,(entry-lo)/risk); hs=lo<=sl; ht=hi>=tp
            else: mfe=max(mfe,(entry-lo)/risk); mae=max(mae,(hi-entry)/risk); hs=hi>=sl; ht=lo<=tp
            if hs or ht: xp=sl if hs else tp; status='LOSS' if hs else 'WIN'; ex=j; break
        if ex is None: continue
        r=(xp-entry)/risk if sig['direction']=='BUY' else (entry-xp)/risk
        trades.append({'symbol':p.stem.replace('_1h',''),'direction':sig['direction'],'signal_time':d.dt.iloc[i],'entry_time':d.dt.iloc[ei],'exit_time':d.dt.iloc[ex],'entry':entry,'sl':sl,'tp':tp,'score':sig['buy'] if sig['direction']=='BUY' else sig['sell'],'result':status,'r_multiple':r,'mfe_r':mfe,'mae_r':mae,'session':sig.get('diagnostics',{}).get('session',{}).get('name','')}); last_exit=ex
    return pd.DataFrame(trades)

def main():
    outs=[]
    paths=sorted(DATA.glob('*_1h.csv'))
    with ProcessPoolExecutor(max_workers=min(6, len(paths))) as ex:
        futs={ex.submit(run_symbol,p):p for p in paths}
        for fut in as_completed(futs):
            p=futs[fut]
            t=fut.result(); print(p.name,len(t),flush=True)
            if not t.empty: outs.append(t)
    alltr=pd.concat(outs,ignore_index=True) if outs else pd.DataFrame()
    if not alltr.empty:
        alltr=alltr.sort_values('entry_time').reset_index(drop=True)
        alltr.to_csv(ROOT/'UNIFIED_BACKTEST_TRADES.csv',index=False)
    s=stats(alltr)
    print('RESULT',json.dumps(s,default=str))
    if not alltr.empty:
        print('BY_SYMBOL')
        print(alltr.groupby('symbol').r_multiple.agg(['count','sum','mean']).to_string())
        print('BY_DIRECTION')
        print(alltr.groupby('direction').r_multiple.agg(['count','sum','mean']).to_string())
        print('BY_SESSION')
        print(alltr.groupby('session').r_multiple.agg(['count','sum','mean']).to_string())
if __name__=='__main__': main()
