#!/usr/bin/env python3
import argparse, time
from pathlib import Path
import requests

URL='https://api-contract.weex.com/capi/v3/market/historyKlines'

def fetch(symbol, interval, start_ms, end_ms=None):
    rows=[]; end=end_ms
    while True:
        p={'symbol':symbol,'interval':interval,'limit':100,'startTime':start_ms}
        if end is not None: p['endTime']=end
        r=requests.get(URL,params=p,timeout=20); r.raise_for_status(); batch=r.json()
        if not batch: break
        rows.extend(batch)
        if len(batch)<100: break
        last=int(batch[-1][0]); start_ms=last+1
        if end is not None and start_ms>=end: break
        time.sleep(.15)
    return rows

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--symbols',required=True); ap.add_argument('--days',type=int,default=365); ap.add_argument('--interval',default='15m'); ap.add_argument('--out-dir',default='backtest_data')
    a=ap.parse_args(); out=Path(a.out_dir); out.mkdir(parents=True,exist_ok=True)
    end=int(time.time()*1000); start=end-a.days*86400000
    for s in [x.strip().upper() for x in a.symbols.split(',') if x.strip()]:
        rows=fetch(s,a.interval,start,end)
        lines=['close_time,open,high,low,close,volume']
        for x in rows:
            lines.append(','.join([str(x[0]),x[1],x[2],x[3],x[4],x[5]]))
        (out/f'{s}_{a.interval}.csv').write_text('\n'.join(lines)+'\n')
        print(s,len(rows))
if __name__=='__main__': main()
