import pandas as pd

class AverageTrueRange:
    def __init__(self, high, low, close, window=14): self.high=high; self.low=low; self.close=close; self.window=window
    def average_true_range(self):
        prev=self.close.shift(1)
        tr=pd.concat([(self.high-self.low),(self.high-prev).abs(),(self.low-prev).abs()],axis=1).max(axis=1)
        return tr.ewm(alpha=1/self.window,adjust=False,min_periods=self.window).mean()

class BollingerBands:
    def __init__(self, close, window=20, window_dev=2): self.close=close; self.window=window; self.dev=window_dev
    def _mid(self): return self.close.rolling(self.window,min_periods=self.window).mean()
    def _std(self): return self.close.rolling(self.window,min_periods=self.window).std(ddof=0)
    def bollinger_pband(self):
        mid=self._mid(); std=self._std(); high=mid+self.dev*std; low=mid-self.dev*std
        return (self.close-low)/(high-low).replace(0,pd.NA)
