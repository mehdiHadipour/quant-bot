from pathlib import Path
import pandas as pd, itertools, json
from multiprocessing import Pool
from ict_full_backtest import run
DATA=Path('backtest_data')
FILES=sorted(DATA.glob('*_15m.csv'))
CONFIGS=list(itertools.product([(9,26,52),(10,30,60)], [14,20], [.65,.85], [65,70]))

def one(cfg):
    ichi,atr_n,disp,thr=cfg; parts=[]
    for p in FILES:
        d=pd.read_csv(p); d['dt']=pd.to_datetime(d.open_time,unit='ms',utc=True); d=d.sort_values('dt').reset_index(drop=True)
        t=run(d,ichi=ichi,atr_n=atr_n,disp_min=disp,score_thr=thr)
        if not t.empty: parts.append(t.assign(symbol=p.stem.replace('_15m','')))
    all_t=pd.concat(parts,ignore_index=True) if parts else pd.DataFrame()
    if all_t.empty:return dict(tenkan=ichi[0],kijun=ichi[1],senkou_b=ichi[2],atr_n=atr_n,disp_min=disp,score_thr=thr,trades=0,wins=0,winrate=0,netR=-999,avgR=0,pf=0,dd=0)
    r=all_t.r_multiple; eq=r.cumsum(); dd=float((eq.cummax()-eq).max()); pf=float(r[r>0].sum()/(-r[r<0].sum())) if (r<0).any() else 99
    return dict(tenkan=ichi[0],kijun=ichi[1],senkou_b=ichi[2],atr_n=atr_n,disp_min=disp,score_thr=thr,trades=len(all_t),wins=int((r>0).sum()),winrate=float((r>0).mean()*100),netR=float(r.sum()),avgR=float(r.mean()),pf=pf,dd=dd)
if __name__=='__main__':
    with Pool(processes=4) as pool: rows=pool.map(one,CONFIGS)
    out=pd.DataFrame(rows).sort_values(['netR','pf'],ascending=False); out.to_csv('V30_PARAMETER_SEARCH.csv',index=False)
    best=out.iloc[0].to_dict(); Path('V30_SELECTED_CONFIG.json').write_text(json.dumps({k:(int(v) if k in ['tenkan','kijun','senkou_b','atr_n','score_thr'] else float(v)) for k,v in best.items() if k in ['tenkan','kijun','senkou_b','atr_n','disp_min','score_thr']},indent=2))
    print(out.to_string(index=False)); print('BEST',best)
