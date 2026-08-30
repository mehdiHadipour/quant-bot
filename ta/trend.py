import pandas as pd
import numpy as np

class EMAIndicator:
    def __init__(self, close, window=14): self.close=close; self.window=window
    def ema_indicator(self): return self.close.ewm(span=self.window, adjust=False, min_periods=self.window).mean()

class MACD:
    def __init__(self, close, window_fast=12, window_slow=26, window_sign=9):
        self.close=close; self.fast=window_fast; self.slow=window_slow; self.sign=window_sign
    def macd(self):
        return self.close.ewm(span=self.fast, adjust=False, min_periods=self.fast).mean() - self.close.ewm(span=self.slow, adjust=False, min_periods=self.slow).mean()
    def macd_signal(self): return self.macd().ewm(span=self.sign, adjust=False, min_periods=self.sign).mean()

class ADXIndicator:
    def __init__(self, high, low, close, window=14): self.high=high; self.low=low; self.close=close; self.window=window
    def adx(self):
        h,l,c=self.high,self.low,self.close
        up=h.diff(); down=-l.diff()
        plus_dm=up.where((up>down)&(up>0),0.0); minus_dm=down.where((down>up)&(down>0),0.0)
        prev=c.shift(1)
        tr=pd.concat([(h-l),(h-prev).abs(),(l-prev).abs()],axis=1).max(axis=1)
        atr=tr.ewm(alpha=1/self.window,adjust=False,min_periods=self.window).mean()
        pdi=100*plus_dm.ewm(alpha=1/self.window,adjust=False,min_periods=self.window).mean()/atr.replace(0,np.nan)
        mdi=100*minus_dm.ewm(alpha=1/self.window,adjust=False,min_periods=self.window).mean()/atr.replace(0,np.nan)
        dx=100*(pdi-mdi).abs()/(pdi+mdi).replace(0,np.nan)
        return dx.ewm(alpha=1/self.window,adjust=False,min_periods=self.window).mean()
