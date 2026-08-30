import unittest
import pandas as pd
from volume_profile import profile_levels, context

class VolumeProfileTests(unittest.TestCase):
    def test_profile_has_poc_and_value_area(self):
        p=profile_levels([11,12,13,12,11,12,13,12],[9,10,11,10,9,10,11,10],[10,11,12,11,10,11,12,11],[100,200,500,200,100,200,500,200],bins=10)
        self.assertIsNotNone(p)
        self.assertLessEqual(p['val'], p['poc'])
        self.assertLessEqual(p['poc'], p['vah'])

    def test_context_excludes_current_bar(self):
        df=pd.DataFrame({'open':[10,11,12,13,14,15,16,17,18,19], 'high':[11,12,13,14,15,16,17,18,19,20], 'low':[9,10,11,12,13,14,15,16,17,18], 'close':[10.5,11.5,12.5,13.5,14.5,15.5,16.5,17.5,18.5,19.5], 'volume':[100]*10})
        x=context(df,9,lookback=8,bins=8)
        self.assertTrue(x['ok'])

if __name__=='__main__': unittest.main()
