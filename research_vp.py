from pathlib import Path
import pandas as pd
from ict_full_backtest import run, DATA
from config import STRICT_SYMBOLS

def main():
    results=[]
    for lb,bins in [(36,30),(48,40),(60,40),(72,40)]:
        parts=[]
        for p in sorted(DATA.glob('*_15m.csv')):
            sym=p.stem.replace('_15m','')
            d=pd.read_csv(p)
            d['dt']=pd.to_datetime(d.open_time,unit='ms',utc=True)
            d=d.sort_values('dt').reset_index(drop=True)
            t=run(d,(9,26,52),14,.85,65,strict=(sym in STRICT_SYMBOLS),vp_lookback=lb,vp_bins=bins)
            if not t.empty:
                parts.append(t.assign(symbol=sym))
        if parts:
            x=pd.concat(parts,ignore_index=True); rs=x.r_multiple; wins=int((rs>0).sum()); loss=-rs[rs<0].sum(); pf=rs[rs>0].sum()/loss if loss>0 else 99; eq=rs.cumsum(); dd=float((eq.cummax()-eq).max())
            results.append((lb,bins,len(x),wins,wins/len(x),rs.sum(),pf,dd))
    print(pd.DataFrame(results,columns=['lb','bins','trades','wins','winrate','netR','PF','DD']).sort_values(['netR','PF'],ascending=False).to_string(index=False))

if __name__ == '__main__':
    main()
