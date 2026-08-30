import pandas as pd

class RSIIndicator:
    def __init__(self, close, window=14): self.close=close; self.window=window
    def rsi(self):
        d=self.close.diff(); up=d.clip(lower=0); down=-d.clip(upper=0)
        avg_up=up.ewm(alpha=1/self.window,adjust=False,min_periods=self.window).mean()
        avg_down=down.ewm(alpha=1/self.window,adjust=False,min_periods=self.window).mean()
        rs=avg_up/avg_down.replace(0,pd.NA)
        return 100-(100/(1+rs))

class StochasticOscillator:
    def __init__(self, high, low, close, window=14, smooth_window=3): self.high=high; self.low=low; self.close=close; self.window=window; self.smooth=smooth_window
    def stoch(self):
        lo=self.low.rolling(self.window,min_periods=self.window).min(); hi=self.high.rolling(self.window,min_periods=self.window).max()
        return 100*(self.close-lo)/(hi-lo).replace(0,pd.NA)
    def stoch_signal(self): return self.stoch().rolling(self.smooth,min_periods=self.smooth).mean()
