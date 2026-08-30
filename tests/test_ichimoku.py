import pandas as pd, numpy as np
from ichimoku import ichimoku

def test_ichimoku_columns_and_no_early_cloud():
    n=150; d=pd.DataFrame({'high':np.arange(n)+2.0,'low':np.arange(n)*1.0,'close':np.arange(n)+1.0})
    x=ichimoku(d)
    assert {'tenkan','kijun','cloud_top','cloud_bottom','bull','bear'}.issubset(x.columns)
    assert x.cloud_top.iloc[:77].isna().all()

def test_chikou_is_not_future_data():
    d=pd.DataFrame({'high':np.arange(100,dtype=float)+2,'low':np.arange(100,dtype=float),'close':np.arange(100,dtype=float)+1})
    x=ichimoku(d)
    assert bool(x.chikou_bull.iloc[80]) is True
