import json, os, tempfile, unittest
import pandas as pd
from smart_context import session_context, pullback_score, candle_orderflow_score, load_whale_bias, fundamental_score

class TestSmartContext(unittest.TestCase):
    def _df(self, n=80, slope=0.2):
        c=pd.Series([100+i*slope for i in range(n)], dtype=float)
        return pd.DataFrame({'open':c,'high':c+1,'low':c-1,'close':c,'volume':1000.0,'taker_buy_volume':600.0})
    def test_session_overlap(self):
        x=session_context(pd.Timestamp('2026-08-25T14:00:00Z'))
        self.assertEqual(x['session'],'LONDON_NY_OVERLAP'); self.assertEqual(x['score'],2)
    def test_orderflow_buy(self):
        score,_=candle_orderflow_score(self._df(),'BUY'); self.assertGreaterEqual(score,1)
    def test_pullback_function_is_bounded(self):
        score,_=pullback_score(self._df(),'BUY'); self.assertIn(score,(-2,-1,0,1,2))
    def test_whale_json_bridge(self):
        old=os.environ.get('WHALE_BIAS_JSON')
        os.environ['WHALE_BIAS_JSON']=json.dumps({'SOLUSDT':{'long':.8,'short':.2,'quality':1}})
        try:
            score,reason=load_whale_bias('SOLUSDT','BUY'); self.assertEqual(score,2); self.assertEqual(reason,'whale-aligned')
        finally:
            if old is None: os.environ.pop('WHALE_BIAS_JSON',None)
            else: os.environ['WHALE_BIAS_JSON']=old
    def test_news_scoring(self):
        score,_=fundamental_score('SOLUSDT','BUY',['SOL ETF approval and adoption'])
        self.assertGreater(score,0)
        score,_=fundamental_score('SOLUSDT','BUY',['SOL exploit hack and lawsuit'])
        self.assertLess(score,0)
if __name__=='__main__': unittest.main()
