#!/usr/bin/env python3
"""
Fetch all K-line data and save as JSON for the market monitor report.
Run this before build_report.py
"""
import json, os, sys, subprocess, csv
from pathlib import Path
from datetime import datetime, timedelta

OUT_DIR = Path(__file__).parent / "kline_data"
OUT_DIR.mkdir(parents=True, exist_ok=True)

INDICES = {
    # Index name -> (code, setcode, is_etf)
    "沪深300": ("000300", 1, False),
    "中证A股": ("399317", 0, False),
    "中证500": ("000905", 1, False),
    "创业板指": ("399006", 0, False),
    "中证红利": ("515080", 1, True),    # ETF substitute
    "300价值": ("562320", 1, True),    # ETF substitute  
    "300成长": ("562310", 1, True),    # ETF substitute
}

def fetch_kline(code, setcode, wantnum=600):
    """Fetch K-line data using openclaw CLI and return as list of dicts"""
    cmd = f'openclaw --profile tdxclaw kline code={code} setcode={setcode} period=4 wantNum={wantnum} tqFlag=11'
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
        output = result.stdout + result.stderr
        return parse_kline_output(output)
    except Exception as e:
        print(f"  Error fetching {code}: {e}")
        return []

def parse_kline_output(output):
    """Parse K-line output from openclaw CLI into list of {date, open, high, low, close, volume}"""
    bars = []
    # Look for JSON data in output
    # Format: {"Setcode": 1, "Code": "000300", "ListItem": [{"Item": ["20240129", "0", "open", "high", "low", "close", ...]}, ...]}
    
    # Find the JSON object
    start = output.find('{"Setcode"')
    if start == -1:
        # Try alternate format
        start = output.find('{"Code"')
    if start == -1:
        return bars
    
    # Find matching closing brace
    brace_count = 0
    end = start
    for i, c in enumerate(output[start:], start):
        if c == '{':
            brace_count += 1
        elif c == '}':
            brace_count -= 1
            if brace_count == 0:
                end = i + 1
                break
    
    try:
        data = json.loads(output[start:end])
        items = data.get("ListItem", [])
        for item in items:
            vals = item.get("Item", [])
            if len(vals) >= 6:
                bars.append({
                    "date": vals[0],
                    "second": vals[1],
                    "open": float(vals[2]) if vals[2] else None,
                    "high": float(vals[3]) if vals[3] else None,
                    "low": float(vals[4]) if vals[4] else None,
                    "close": float(vals[5]) if vals[5] else None,
                    "volume": float(vals[8]) if len(vals) > 8 and vals[8] else None,
                })
    except Exception as e:
        print(f"  Parse error: {e}")
    
    return bars

def fetch_via_csv(code, setcode, wantnum=600):
    """Alternative: fetch from TDX CSV export"""
    # TDX daily CSV format
    url = f"https://push2.eastmoney.com/api/qt/stock/kline/get?secid={setcode}.{code}&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&klt=101&fqt=1&end=20500101&lmt={wantnum}"
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            klines = data.get("data", {}).get("klines", [])
            bars = []
            for k in klines:
                parts = k.split(",")
                if len(parts) >= 6:
                    bars.append({
                        "date": parts[0].replace("-", ""),
                        "open": float(parts[1]),
                        "close": float(parts[2]),
                        "high": float(parts[3]),
                        "low": float(parts[4]),
                        "volume": float(parts[5]) if parts[5] else None,
                    })
            return bars
    except Exception as e:
        print(f"  CSV fetch error for {code}: {e}")
        return []

def main():
    all_data = {}
    
    for name, (code, setcode, is_etf) in INDICES.items():
        print(f"\nFetching {name} ({code}, setcode={setcode})...")
        
        # Try CSV API first (faster, more reliable)
        bars = fetch_via_csv(code, setcode, 600)
        
        if bars:
            print(f"  Got {len(bars)} bars via CSV API")
        else:
            print(f"  CSV failed, trying openclaw CLI...")
            bars = fetch_kline(code, setcode, 600)
            print(f"  Got {len(bars)} bars via CLI")
        
        if bars:
            # Save to file
            outfile = OUT_DIR / f"{code}.json"
            with open(outfile, 'w', encoding='utf-8') as f:
                json.dump(bars, f, ensure_ascii=False, indent=2)
            print(f"  Saved to {outfile}")
            all_data[name] = bars
        else:
            print(f"  FAILED to get data for {name}")
    
    # Summary
    print(f"\n{'='*50}")
    for name, (code, _, _) in INDICES.items():
        outfile = OUT_DIR / f"{code}.json"
        if outfile.exists():
            with open(outfile, 'r') as f:
                data = json.load(f)
            print(f"  {name}: {len(data)} bars, last close={data[-1]['close']}")
        else:
            print(f"  {name}: MISSING")
    
    return all_data

if __name__ == "__main__":
    main()
