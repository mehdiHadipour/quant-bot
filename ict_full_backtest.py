from pathlib import Path
import os
import pandas as pd, numpy as np
from zoneinfo import ZoneInfo
import os
from ichimoku import ichimoku
from config import ASIA_ENABLED, SESSION_WEIGHTS, STRICT_SYMBOLS, STRICT_MIN_HLI, STRICT_MIN_SCORE, NEGATIVE_SESSIONS, NEGATIVE_SESSION_MIN_HLI, NEGATIVE_SESSION_MIN_SCORE, FIB_LOOKBACK, FIB_OTE_LOW, FIB_OTE_HIGH, MANUAL_SETTINGS, SESSION_CFG, REGIME_CFG
from volume_profile import context as vp_context

def macd(df, fast=None, slow=None, signal=None):
 fast=int((MANUAL_SETTINGS.get('parameters',{}) or {}).get('MACD_FAST',12) if fast is None else fast); slow=int((MANUAL_SETTINGS.get('parameters',{}) or {}).get('MACD_SLOW',26) if slow is None else slow); signal=int((MANUAL_SETTINGS.get('parameters',{}) or {}).get('MACD_SIGNAL',9) if signal is None else signal); emaf=df.close.ewm(span=fast,adjust=False,min_periods=fast).mean(); emas=df.close.ewm(span=slow,adjust=False,min_periods=slow).mean(); line=emaf-emas; sig=line.ewm(span=signal,adjust=False,min_periods=signal).mean(); return line,sig,line-sig
DATA=Path(os.getenv('BACKTEST_DATA_DIR','backtest_data')); ROOT=Path(__file__).resolve().parent
LONDON=ZoneInfo('Europe/London'); NY=ZoneInfo('America/New_York')

def atr(df,n=None):
 n=int((MANUAL_SETTINGS.get('parameters',{}) or {}).get('ATR_PERIOD',14) if n is None else n); pc=df.close.shift(1); tr=pd.concat([df.high-df.low,(df.high-pc).abs(),(df.low-pc).abs()],axis=1).max(axis=1)
 return tr.ewm(alpha=1/n,adjust=False,min_periods=n).mean()

def htf(df,rule):
 x=df.set_index('dt')[['open','high','low','close','volume']]
 r=x.resample(rule,label='right',closed='left').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'}).dropna()
 r['e50']=r.close.ewm(span=50,adjust=False,min_periods=50).mean(); r['e200']=r.close.ewm(span=200,adjust=False,min_periods=200).mean(); r['bias']=np.where(r.e50>r.e200,'BULL','BEAR')
 return r

def run(df, ichi=(9,26,52), atr_n=14, disp_min=.85, score_thr=65, fib_lookback=FIB_LOOKBACK, fib_ote_lo=FIB_OTE_LOW, fib_ote_hi=FIB_OTE_HIGH, macd_gate=False, strict=False, vp_lookback=60, vp_bins=40, asset_class='CRYPTO'):
 df=df.copy(); a=atr(df,atr_n); rng=df.high-df.low; body=(df.close-df.open).abs(); disp=(body/a)*(body/rng.replace(0,np.nan))
 P=MANUAL_SETTINGS.get('parameters',{}) or {}; sweep_lb=int(P.get('SWEEP_LOOKBACK',20)); mss_lb=int(P.get('MSS_LOOKBACK',8)); prior_bars=int(P.get('PRIOR_SWEEP_BARS',4)); mid_lb=int(P.get('MID_LOOKBACK',40)); disp_min=float(P.get('DISPLACEMENT_MIN',disp_min)); ph=df.high.shift(1).rolling(sweep_lb).max(); pl=df.low.shift(1).rolling(sweep_lb).min()
 bull_sweep=(df.low<pl)&(df.close>pl); bear_sweep=(df.high>ph)&(df.close<ph)
 mss_up=df.close > df.high.shift(1).rolling(mss_lb).max(); mss_dn=df.close < df.low.shift(1).rolling(mss_lb).min()
 bull_fvg=df.low > df.high.shift(2); bear_fvg=df.high < df.low.shift(2)
 bull_ob=(df.close.shift(1)<df.open.shift(1)) & (df.close>df.high.shift(1)); bear_ob=(df.close.shift(1)>df.open.shift(1)) & (df.close<df.low.shift(1))
 bpr=(bull_fvg & bear_fvg.shift(1)) | (bear_fvg & bull_fvg.shift(1))
 for rname,r in [('b4',htf(df,'4h')),('b1',htf(df,'1D'))]:
  df[rname]=pd.merge_asof(df[['dt']],r[['bias']].reset_index().rename(columns={'index':'dt'}),on='dt',direction='backward')['bias'].values
 dts=df.dt; l=dts.dt.tz_convert(LONDON); n=dts.dt.tz_convert(NY); t=dts.dt.tz_convert('Asia/Tokyo')
 london=(l.dt.hour>=8)&(l.dt.hour<17); ny=(n.dt.hour>=8)&(n.dt.hour<17); tokyo=((ASIA_ENABLED.strip().lower() not in {'0','false','no','off'}))&(t.dt.hour>=9)&(t.dt.hour<18); overlap=london&ny; asia_europe=tokyo&london
 sess=np.select([overlap,asia_europe,london,ny,tokyo],[SESSION_WEIGHTS.get('LONDON_NY_OVERLAP',1.0),SESSION_WEIGHTS.get('ASIA_EUROPE_OVERLAP',.86),SESSION_WEIGHTS.get('LONDON',.88),SESSION_WEIGHTS.get('NEW_YORK',.92),SESSION_WEIGHTS.get('ASIA',.72)],default=0.0)
 prior_b=bull_sweep.shift(1).rolling(prior_bars).max().fillna(False).astype(bool); prior_s=bear_sweep.shift(1).rolling(prior_bars).max().fillna(False).astype(bool)
 common=(sess>0)&df.b4.notna()&df.b1.notna()
 trend_buy=(df.b4=='BULL')&(df.b1=='BULL')
 trend_sell=(df.b4=='BEAR')&(df.b1=='BEAR')
 counter_buy=(df.b4=='BULL')&(df.b1=='BEAR')
 counter_sell=(df.b4=='BEAR')&(df.b1=='BULL')
 mid40=(df.high.shift(1).rolling(mid_lb).max()+df.low.shift(1).rolling(mid_lb).min())/2
 # Leakage-safe higher-timeframe Ichimoku regime filter.
 h4=htf(df,'4h'); h1=htf(df,'1D')
 i4=ichimoku(h4,*ichi); i1=ichimoku(h1,*ichi)
 def _map_bool(htf_df, vals):
  z=pd.DataFrame({'dt':htf_df.index, 'v':vals.values})
  return pd.merge_asof(df[['dt']],z,on='dt',direction='backward')['v'].astype('boolean').fillna(False).astype(bool)
 ich4b=_map_bool(h4,i4.bull); ich4s=_map_bool(h4,i4.bear)
 ich1b=_map_bool(h1,i1.bull); ich1s=_map_bool(h1,i1.bear)
 ich_buy=ich4b | ich1b; ich_sell=ich4s | ich1s
 c_buy=common&(df.b4=='BULL')&prior_b&(disp>=disp_min)&mss_up&bull_fvg.rolling(3).max().fillna(False).astype(bool)
 c_sell=common&(df.b4=='BEAR')&prior_s&(disp>=disp_min)&mss_dn&bear_fvg.rolling(3).max().fillna(False).astype(bool)
 vol=df.volume.replace(0,np.nan); delta=2*(df.taker_buy_volume/vol)-1; cvd=delta.rolling(8).sum(); fp_buy=(delta>=.03)&(cvd>0); fp_sell=(delta<=-.03)&(cvd<0)
 vm=df.volume.shift(1).rolling(20).mean(); vs=df.volume.shift(1).rolling(20).std(); vz=(df.volume-vm)/vs.replace(0,np.nan); rv=rng/a; hli=(50+12*vz.fillna(0)+18*(rv.fillna(1)-1)).clip(0,100)
 pd_buy=df.close<mid40; pd_sell=df.close>mid40
 # Fibonacci retracement as a confirmation/location layer. The swing is
 # defined only from bars strictly before the signal bar, so it cannot look
 # into the future. OTE is the 61.8%-78.6% retracement zone.
 fib_hi=df.high.shift(1).rolling(fib_lookback).max()
 fib_lo=df.low.shift(1).rolling(fib_lookback).min()
 fib_rng=(fib_hi-fib_lo).replace(0,np.nan)
 fib_buy_618=fib_hi-fib_rng*fib_ote_lo
 fib_buy_786=fib_hi-fib_rng*fib_ote_hi
 fib_sell_618=fib_lo+fib_rng*fib_ote_lo
 fib_sell_786=fib_lo+fib_rng*fib_ote_hi
 fib_buy_ote=(df.close>=fib_buy_786)&(df.close<=fib_buy_618)
 fib_sell_ote=(df.close>=fib_sell_618)&(df.close<=fib_sell_786)
 fib_buy_mid=(df.close>=fib_hi-fib_rng*.50)&(df.close<fib_buy_618)
 fib_sell_mid=(df.close<=fib_lo+fib_rng*.50)&(df.close>fib_sell_618)
 ob_buy=bull_ob.rolling(4).max().fillna(False).astype(bool); ob_sell=bear_ob.rolling(4).max().fillna(False).astype(bool)
 ichi_score_buy=8*ich_buy.astype(int); ichi_score_sell=8*ich_sell.astype(int)
 ml,ms,mh=macd(df); macd_buy=((ml>ms)|((mh>0)&(mh>mh.shift(1)))).fillna(False); macd_sell=((ml<ms)|((mh<0)&(mh<mh.shift(1)))).fillna(False)
 macd_score_buy=6*macd_buy.astype(int); macd_score_sell=6*macd_sell.astype(int)
 fib_weight=float((MANUAL_SETTINGS.get('tools',{}).get('fibonacci',{}) or {}).get('weight',13)); fib_score_buy=fib_weight*fib_buy_ote.astype(int)+(fib_weight*0.4)*fib_buy_mid.astype(int)
 fib_score_sell=fib_weight*fib_sell_ote.astype(int)+(fib_weight*0.4)*fib_sell_mid.astype(int)
 session_bonus=np.select([sess==SESSION_WEIGHTS.get('LONDON_NY_OVERLAP',1.0),sess==SESSION_WEIGHTS.get('ASIA_EUROPE_OVERLAP',.86),sess==SESSION_WEIGHTS.get('LONDON',.88),sess==SESSION_WEIGHTS.get('NEW_YORK',.92),sess==SESSION_WEIGHTS.get('ASIA',.72)],[float((SESSION_CFG.get('LONDON_NY_OVERLAP',{}) or {}).get('score_bonus',5.0)),float((SESSION_CFG.get('ASIA_EUROPE_OVERLAP',{}) or {}).get('score_bonus',4.0)),float((SESSION_CFG.get('LONDON',{}) or {}).get('score_bonus',3.0)),float((SESSION_CFG.get('NEW_YORK',{}) or {}).get('score_bonus',2.0)),float((SESSION_CFG.get('ASIA',{}) or {}).get('score_bonus',0.0))],default=0.0)
 score_orderflow = 0
 vol=df.volume.replace(0,np.nan); delta=2*(df.taker_buy_volume/vol)-1; cvd=delta.rolling(8).sum(); dmean=delta.shift(1).rolling(20).mean(); dstd=delta.shift(1).rolling(20).std().replace(0,np.nan); delta_z=((delta-dmean)/dstd).clip(-5,5)
 wick_up=df.high-df[['open','close']].max(axis=1); wick_dn=df[['open','close']].min(axis=1)-df.low; bar_rng=rng.replace(0,np.nan)
 absorption_buy=(delta<=-.12)&(wick_dn/bar_rng>=.30)&(df.close>df.low+.55*bar_rng); absorption_sell=(delta>=.12)&(wick_up/bar_rng>=.30)&(df.close<df.low+.45*bar_rng)
 fp_buy=((delta>=.03)&(cvd>0))|absorption_buy; fp_sell=((delta<=-.03)&(cvd<0))|absorption_sell
 score_buy=15+15+12+10+10+5*pd_buy.astype(int)+5*ob_buy.astype(int)+3*bpr.astype(int)+ichi_score_buy+fib_score_buy+(8*(hli>=60).astype(int))+(5*fp_buy.astype(int))+session_bonus+macd_score_buy+(4*absorption_buy.astype(int))
 score_sell=15+15+12+10+10+5*pd_sell.astype(int)+5*ob_sell.astype(int)+3*bpr.astype(int)+ichi_score_sell+fib_score_sell+(8*(hli>=60).astype(int))+(5*fp_sell.astype(int))+session_bonus+macd_score_sell+(4*absorption_sell.astype(int))
 sess_thr=np.select([sess==SESSION_WEIGHTS.get('LONDON_NY_OVERLAP',1.0),sess==SESSION_WEIGHTS.get('ASIA_EUROPE_OVERLAP',.86),sess==SESSION_WEIGHTS.get('LONDON',.88),sess==SESSION_WEIGHTS.get('NEW_YORK',.92),sess==SESSION_WEIGHTS.get('ASIA',.72)],[float((SESSION_CFG.get('LONDON_NY_OVERLAP',{}) or {}).get('min_score',65.0)),float((SESSION_CFG.get('ASIA_EUROPE_OVERLAP',{}) or {}).get('min_score',68.0)),float((SESSION_CFG.get('LONDON',{}) or {}).get('min_score',65.0)),float((SESSION_CFG.get('NEW_YORK',{}) or {}).get('min_score',72.0)),float((SESSION_CFG.get('ASIA',{}) or {}).get('min_score',76.0))],default=999.0)
 # TradFi uses the underlying-market liquidity windows more strictly than crypto.
 if asset_class in {'STOCK','ETF','INDEX'}:
  asset_thr=np.select([sess==SESSION_WEIGHTS.get('LONDON_NY_OVERLAP',1.0),sess==SESSION_WEIGHTS.get('NEW_YORK',.92),sess==SESSION_WEIGHTS.get('LONDON',.88),sess==SESSION_WEIGHTS.get('ASIA_EUROPE_OVERLAP',.86),sess==SESSION_WEIGHTS.get('ASIA',.72)],[78.0,74.0,72.0,80.0,999.0],default=999.0)
  sess_thr=np.maximum(sess_thr,asset_thr)
 elif asset_class in {'METAL','ENERGY','FOREX'}:
  asset_thr=np.select([sess==SESSION_WEIGHTS.get('LONDON_NY_OVERLAP',1.0),sess==SESSION_WEIGHTS.get('NEW_YORK',.92),sess==SESSION_WEIGHTS.get('LONDON',.88),sess==SESSION_WEIGHTS.get('ASIA_EUROPE_OVERLAP',.86),sess==SESSION_WEIGHTS.get('ASIA',.72)],[76.0,74.0,70.0,76.0,82.0],default=999.0)
  sess_thr=np.maximum(sess_thr,asset_thr)
 c_buy &= score_buy>=np.maximum(sess_thr, float(score_thr)); c_sell &= score_sell>=np.maximum(sess_thr, float(score_thr))
 if strict:
  c_buy &= fib_buy_ote & macd_buy & fp_buy & (hli>=STRICT_MIN_HLI) & (score_buy>=STRICT_MIN_SCORE)
  c_sell &= fib_sell_ote & macd_sell & fp_sell & (hli>=STRICT_MIN_HLI) & (score_sell>=STRICT_MIN_SCORE)
 # Counter-trend setups require materially stronger confluence.
 c_buy &= (~counter_buy) | (fib_buy_ote & macd_buy & (hli>=70) & (score_buy>=78))
 c_sell &= (~counter_sell) | (fib_sell_ote & macd_sell & (hli>=70) & (score_sell>=78))
 # Negative sessions require materially stronger confirmation.
 negative_session_mask=np.isin(np.round(sess, 4), [round(SESSION_WEIGHTS.get(x, -99),4) for x in NEGATIVE_SESSIONS])
 c_buy &= (~negative_session_mask) | (fib_buy_ote & macd_buy & (hli>=NEGATIVE_SESSION_MIN_HLI) & (score_buy>=NEGATIVE_SESSION_MIN_SCORE))
 c_sell &= (~negative_session_mask) | (fib_sell_ote & macd_sell & (hli>=NEGATIVE_SESSION_MIN_HLI) & (score_sell>=NEGATIVE_SESSION_MIN_SCORE))
 # User policy: every backtest entry must satisfy directional Fibonacci OTE.
 if os.getenv('REQUIRE_FIB_OTE', '1' if bool(MANUAL_SETTINGS.get('gates',{}).get('fib_ote', False)) else '0').strip().lower() not in {'0','false','no','off'}:
  c_buy &= fib_buy_ote; c_sell &= fib_sell_ote
 if macd_gate: c_buy &= macd_buy; c_sell &= macd_sell
 rows=[]
 for i in np.where(c_buy|c_sell)[0]:
  if i+1>=len(df): continue
  direction='BUY' if c_buy.iloc[i] else 'SELL'; w=(bull_sweep if direction=='BUY' else bear_sweep).iloc[max(0,i-4):i]
  swidx=np.where(w.values)[0]
  if len(swidx)==0: continue
  sw=max(0,i-4)+swidx[-1]; entry=float(df.open.iloc[i+1]); aa=float(a.iloc[i])
  if not np.isfinite(aa) or aa<=0: continue
  if direction=='BUY': ext=float(df.low.iloc[sw]); sl=ext-.10*aa; opp=float(df.high.iloc[i-40:i].max()); rmin=float(P.get('TP_MIN_R',2.0)); rmax=float(P.get('TP_MAX_R',4.0)); tp=max(opp,entry+rmin*abs(entry-sl)); tp=min(tp,entry+rmax*abs(entry-sl))
  else: ext=float(df.high.iloc[sw]); sl=ext+.10*aa; opp=float(df.low.iloc[i-40:i].min()); rmin=float(P.get('TP_MIN_R',2.0)); rmax=float(P.get('TP_MAX_R',4.0)); tp=min(opp,entry-rmin*abs(entry-sl)); tp=max(tp,entry-rmax*abs(entry-sl))
  risk=abs(entry-sl)
  if risk<=0: continue
  rr=abs(tp-entry)/risk
  if rr<float(P.get('MIN_BACKTEST_RR',1.8)): continue
  vp=vp_context(df,i,lookback=int(P.get('VP_LOOKBACK',vp_lookback)),bins=int(P.get('VP_BINS',vp_bins)))
  if not vp.get('ok'): continue
  # Volume Profile is a location/auction filter, not a standalone trigger.
  # BUY: prefer reclaim/acceptance around VAL/POC after a downside sweep.
  # SELL: prefer rejection around VAH/POC after an upside sweep.
  vp_buy = bool(vp['near_val'] or vp['below_value'] or (vp['inside_value'] and vp['below_poc']))
  vp_sell = bool(vp['near_vah'] or vp['above_value'] or (vp['inside_value'] and vp['above_poc']))
  if (direction=='BUY' and not vp_buy) or (direction=='SELL' and not vp_sell): continue
  vp_score=5 if ((direction=='BUY' and vp['near_val']) or (direction=='SELL' and vp['near_vah'])) else (3 if vp['inside_value'] else 2)
  rows.append(dict(idx=i+1,signal_idx=i,direction=direction,entry=entry,sl=sl,tp=tp,risk=risk,rr=rr,signal_time=df.dt.iloc[i],entry_time=df.dt.iloc[i+1],score=float(score_buy.iloc[i] if direction=='BUY' else score_sell.iloc[i])+vp_score,hli=float(hli.iloc[i]),delta=float(delta.iloc[i]),delta_z=float(delta_z.iloc[i]),cvd=float(cvd.iloc[i]),absorption=bool(absorption_buy.iloc[i] if direction=='BUY' else absorption_sell.iloc[i]),vp_poc=vp['poc'],vp_vah=vp['vah'],vp_val=vp['val'],vp_hvn=vp['hvn'],vp_lvn=vp['lvn'],vp_context='NEAR_VAL' if direction=='BUY' and vp['near_val'] else 'NEAR_VAH' if direction=='SELL' and vp['near_vah'] else 'VALUE' if vp['inside_value'] else 'OUTSIDE_VALUE',vp_ok=True,ichimoku_bull=bool(ich_buy.iloc[i]),ichimoku_bear=bool(ich_sell.iloc[i]),fib_ote=bool(fib_buy_ote.iloc[i] if direction=='BUY' else fib_sell_ote.iloc[i]),fib_zone='OTE' if bool(fib_buy_ote.iloc[i] if direction=='BUY' else fib_sell_ote.iloc[i]) else ('MID' if bool(fib_buy_mid.iloc[i] if direction=='BUY' else fib_sell_mid.iloc[i]) else 'NONE'),macd_line=float(ml.iloc[i]),macd_signal=float(ms.iloc[i]),macd_hist=float(mh.iloc[i]),macd_ok=bool(macd_buy.iloc[i] if direction=='BUY' else macd_sell.iloc[i]),session=('OVERLAP' if sess[i]==SESSION_WEIGHTS.get('LONDON_NY_OVERLAP',1.0) else 'ASIA_EUROPE_OVERLAP' if sess[i]==SESSION_WEIGHTS.get('ASIA_EUROPE_OVERLAP',.86) else 'LONDON' if sess[i]==SESSION_WEIGHTS.get('LONDON',.88) else 'NEW_YORK' if sess[i]==SESSION_WEIGHTS.get('NEW_YORK',.92) else 'ASIA')))
 trades=[]; next_free=-1
 for z in rows:
  if z['idx']<next_free: continue
  entry_i=z['idx']; end=min(len(df),entry_i+int(P.get('MAX_HOLD_BARS',96))); mfe=mae=0.; initial_adverse=False; ex=xp=None; status=None
  for j in range(entry_i,end):
   hi=float(df.high.iloc[j]); lo=float(df.low.iloc[j])
   if z['direction']=='BUY': fav=(hi-z['entry'])/z['risk']; adv=(z['entry']-lo)/z['risk']; mfe=max(mfe,fav); mae=max(mae,adv); hs=lo<=z['sl']; ht=hi>=z['tp']
   else: fav=(z['entry']-lo)/z['risk']; adv=(hi-z['entry'])/z['risk']; mfe=max(mfe,fav); mae=max(mae,adv); hs=hi>=z['sl']; ht=lo<=z['tp']
   if j==entry_i and adv>=.25: initial_adverse=True
   if hs or ht:
    ex=j; xp=z['sl'] if hs else z['tp']; status='LOSS' if hs else 'WIN'; break
  if ex is None: continue
  r=((xp-z['entry'])/z['risk']) if z['direction']=='BUY' else ((z['entry']-xp)/z['risk'])
  z.update(exit_time=df.dt.iloc[ex],exit_price=xp,result=status,r_multiple=r,mfe_r=mfe,mae_r=mae,initial_adverse=initial_adverse)
  trades.append(z); next_free=ex+1
 return pd.DataFrame(trades)

def main():
    ichi=(9,26,52); atr_n=14; disp_min=.85; score_thr=65
    cfg=ROOT/'V30_SELECTED_CONFIG.json'
    c={}
    if cfg.exists():
        import json
        c=json.loads(cfg.read_text()); ichi=(int(c.get('tenkan',9)),int(c.get('kijun',26)),int(c.get('senkou_b',52))); atr_n=int(c.get('atr_n',14)); disp_min=float(c.get('disp_min',.85)); score_thr=float(c.get('score_thr',65))
    outs=[]
    strict_syms=set(STRICT_SYMBOLS)
    for p in sorted(DATA.glob('*_15m.csv')):
        sym=p.stem.replace('_15m',''); d=pd.read_csv(p); d['dt']=pd.to_datetime(d.open_time,unit='ms',utc=True); d=d.sort_values('dt').reset_index(drop=True); t=run(d,ichi,atr_n,disp_min,score_thr,fib_lookback=int(c.get('fib_lookback', FIB_LOOKBACK)),fib_ote_lo=float(c.get('fib_ote_low', FIB_OTE_LOW)),fib_ote_hi=float(c.get('fib_ote_high', FIB_OTE_HIGH)),strict=(sym in strict_syms),vp_lookback=int((MANUAL_SETTINGS.get('parameters',{}) or {}).get('VP_LOOKBACK',60)),vp_bins=int((MANUAL_SETTINGS.get('parameters',{}) or {}).get('VP_BINS',40)))
        if not t.empty:t.insert(0,'symbol',sym); outs.append(t)
        print(sym,len(t),flush=True)
    all=pd.concat(outs,ignore_index=True) if outs else pd.DataFrame(); all=all.sort_values('entry_time').reset_index(drop=True); all.to_csv(ROOT/'BACKTEST_V30_RESULTS.csv',index=False)
    if all.empty: print('NO TRADES'); return
    rs=all.r_multiple; wins=(rs>0).sum(); pf=rs[rs>0].sum()/(-rs[rs<0].sum()) if (rs<0).any() else 99; eq=rs.cumsum(); dd=float((eq.cummax()-eq).max()); ratio=all.mfe_r/all.rr
    print('\n=== V30 RESULT ==='); print(f'Trades {len(all)} | Wins {wins} | Losses {len(all)-wins} | WinRate {wins/len(all)*100:.2f}% | NetR {rs.sum():.2f} | AvgR {rs.mean():.3f} | PF {pf:.3f} | MaxDD {dd:.2f}R')
    for n,m in [('<=30%',ratio<=.30),('30-50%',(ratio>.30)&(ratio<=.50)),('50-70%',(ratio>.50)&(ratio<=.70)),('70-<100%',(ratio>.70)&(ratio<1)),('TP full',ratio>=1)]: print(n,int(m.sum()))
    print('Initial adverse >=0.25R on entry candle',int(all.initial_adverse.sum()))
    all.groupby('symbol').agg(trades=('r_multiple','size'),wins=('result',lambda x:(x=='WIN').sum()),netR=('r_multiple','sum'),avgR=('r_multiple','mean')).to_csv(ROOT/'V30_BY_SYMBOL.csv')
if __name__=='__main__': main()
