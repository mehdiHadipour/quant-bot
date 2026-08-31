"""Configurable market-regime classifier. Shared by live and research paths."""
from __future__ import annotations
import numpy as np
import pandas as pd
from ta.trend import ADXIndicator
from config import REGIME_CFG

def classify(df):
    if df is None or len(df)<60: return {'name':'UNKNOWN','confidence':0.0,'strategy':'none'}
    c=df['close'].astype(float); fast=int(REGIME_CFG.get('ema_fast',50)); slow=int(REGIME_CFG.get('ema_slow',200)); adxp=float(REGIME_CFG.get('trend_adx_min',25)); range_adx=float(REGIME_CFG.get('range_adx_max',20)); look=int(REGIME_CFG.get('slope_lookback',20))
    ef=c.ewm(span=fast,adjust=False,min_periods=fast).mean(); es=c.ewm(span=slow,adjust=False,min_periods=slow).mean()
    adx=ADXIndicator(df['high'],df['low'],c,window=14).adx().iloc[-1]
    mid=c.rolling(20).mean(); std=c.rolling(20).std(); width=((4*std)/mid).iloc[-1]
    if pd.isna(adx) or pd.isna(ef.iloc[-1]) or pd.isna(es.iloc[-1]): return {'name':'UNKNOWN','confidence':0.0,'strategy':'none'}
    slope=(ef.iloc[-1]-ef.iloc[-1-look])/max(abs(ef.iloc[-1-look]),1e-12) if len(ef)>look else 0
    sep=abs(ef.iloc[-1]-es.iloc[-1])/max(c.iloc[-1],1e-12)
    if adx >= adxp and ef.iloc[-1] > es.iloc[-1] and slope>0: name='BULL'
    elif adx >= adxp and ef.iloc[-1] < es.iloc[-1] and slope<0: name='BEAR'
    elif adx <= range_adx and width <= float(REGIME_CFG.get('range_bb_width_max',.06)): name='RANGE'
    else: name='TRANSITION'
    conf=min(99.0, 50.0 + min(30.0,abs(float(adx)-range_adx)) + min(19.0,sep*1000) )
    if name=='RANGE': conf=min(99.0,50+min(35,(range_adx-float(adx))*3)+min(14,float(REGIME_CFG.get('range_bb_width_max',.06)-width)*200))
    strategies=(REGIME_CFG.get('strategy_by_regime',{}) or {}).get(name,['liquidity'])
    return {'name':name,'confidence':round(max(0,min(99,conf)),2),'strategy':strategies[0] if strategies else 'liquidity','strategies':strategies,'adx':float(adx),'bb_width':float(width),'ema_fast':float(ef.iloc[-1]),'ema_slow':float(es.iloc[-1]),'slope':float(slope)}
