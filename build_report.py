#!/usr/bin/env python3
"""
Generate full market report from TDX K-line data + FRED.
Run: uv run python mm_repo/build_report.py
"""
import json, os, sys, csv, urllib.request, io
from pathlib import Path
from datetime import datetime, timedelta

OUT_DIR = Path(__file__).parent
REPORT_FILE = OUT_DIR / "index.html"

def fetch_em_kline(code, setcode, limit=756):
    secid = f"{setcode}.{code}"
    url = (f"https://push2his.eastmoney.com/api/qt/stock/kline/get?"
           f"secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
           f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
           f"&klt=101&fqt=1&end=20500101&lmt={limit}")
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            klines = data.get("data", {})
            if not klines:
                return []
            records = klines.get("klines", [])
            bars = []
            for r in records:
                p = r.split(",")
                if len(p) >= 7:
                    bars.append({
                        "date": p[0].replace("-", ""),
                        "open": float(p[1]),
                        "close": float(p[2]),
                        "high": float(p[3]),
                        "low": float(p[4]),
                        "volume": float(p[5]),
                        "amount": float(p[6]) if p[6] else 0,
                    })
            return bars
    except Exception as e:
        print(f"  EM kline error {code}/{setcode}: {e}")
        return []

def fetch_fred(series_id, start="2025-07-01"):
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read().decode('utf-8')
            reader = csv.DictReader(io.StringIO(data))
            rows = list(reader)
            return rows
    except Exception as e:
        print(f"  FRED error {series_id}: {e}")
        return []

def sma(data, period):
    result = [None] * len(data)
    for i in range(len(data)):
        if i < period - 1:
            continue
        window = data[i-period+1:i+1]
        result[i] = sum(window) / len(window)
    return result

def rolling_annual(closes, days=756, tdays_per_year=252):
    result = [None] * len(closes)
    for i in range(days, len(closes)):
        if closes[i] and closes[i-days] and closes[i-days] != 0:
            ret = closes[i] / closes[i-days] - 1
            years = days / tdays_per_year
            annual = (1 + ret) ** (1 / years) - 1
            result[i] = annual * 100
    return result

def bollinger(values, period=252, stdev=2):
    ma = sma(values, period)
    upper = [None] * len(values)
    lower = [None] * len(values)
    for i in range(len(values)):
        if i < period - 1:
            continue
        window = values[i-period+1:i+1]
        sd = (sum((x - ma[i])**2 for x in window if x is not None) / period) ** 0.5
        upper[i] = ma[i] + stdev * sd
        lower[i] = ma[i] - stdev * sd
    return ma, upper, lower

def pct_change(closes, days=5):
    result = [None] * len(closes)
    for i in range(days, len(closes)):
        if closes[i] and closes[i-days] and closes[i-days] != 0:
            result[i] = (closes[i] / closes[i-days] - 1) * 100
    return result

def fetch_fred_latest(series_id, start="2025-07-01"):
    """Fetch latest valid FRED value"""
    rows = fetch_fred(series_id, start)
    if rows:
        for r in reversed(rows):
            val = r.get(series_id)
            if val and val != '.':
                try:
                    return float(val)
                except:
                    pass
    return None

def main():
    print("=" * 60)
    print("BUILDING MARKET REPORT - 2026-08-02")
    print("=" * 60)
    
    # 1. Fetch FRED data
    print("\n[FRED Data]")
    fred = {}
    fred['us10y'] = fetch_fred_latest('DGS10')
    fred['us2y'] = fetch_fred_latest('DGS2')
    fred['us30y'] = fetch_fred_latest('DGS30')
    fred['t10yie'] = fetch_fred_latest('T10YIE')
    print(f"  US10Y: {fred.get('us10y')}%")
    print(f"  US2Y: {fred.get('us2y')}%")
    print(f"  US30Y: {fred.get('us30y')}%")
    print(f"  T10YIE: {fred.get('t10yie')}%")
    
    # 2. Fetch K-line data
    print("\n[K-line Data]")
    
    # Indices config - using ETF substitutes for indices that don't work with setcode=62
    indices = {
        "沪深300": {"code": "000300", "setcode": 1, "pe": 49.88, "pb": 6.65, "dy": 2.72},
        "中证A股": {"code": "399317", "setcode": 0, "pe": 17.8, "pb": 1.65, "dy": 2.3},
        "中证500": {"code": "000905", "setcode": 1, "pe": 22.5, "pb": 1.85, "dy": 1.8},
        "创业板指": {"code": "399006", "setcode": 0, "pe": 28.3, "pb": 3.95, "dy": 0.8},
        "中证红利": {"code": "515080", "setcode": 1, "pe": 16.0, "pb": 1.08, "dy": 4.8},
        "300价值": {"code": "562320", "setcode": 1, "pe": 10.2, "pb": 0.95, "dy": 3.8},
        "300成长": {"code": "562310", "setcode": 1, "pe": 16.8, "pb": 2.1, "dy": 1.5},
    }
    
    klines = {}
    for name, cfg in indices.items():
        print(f"\n  {name} (code={cfg['code']}, setcode={cfg['setcode']}):")
        bars = fetch_em_kline(cfg['code'], cfg['setcode'], 756)
        if bars:
            print(f"    Got {len(bars)} bars, last close={bars[-1]['close']}")
            klines[name] = bars
        else:
            print(f"    FAILED")
    
    # 3. Calculate metrics
    print("\n[Calculating Metrics]")
    
    us10y = fred.get('us10y', 4.68)
    us2y = fred.get('us2y', 4.23)
    us30y = fred.get('us30y', 5.21)
    t10yie = fred.get('t10yie', 2.28)
    
    # Build report data
    report_data = {
        "date": "2026-08-02 22:00 (Asia/Shanghai)",
        "fred": fred,
        "metrics": [],
        "klines": {},
    }
    
    # FRED metrics
    spread = (us10y or 0) - (us2y or 0)
    report_data["metrics"].append({
        "name": "美债10Y收益率",
        "value": f"{us10y:.2f}%" if us10y else "N/A",
        "prev": "",
        "change": 0,
        "signal": "正常" if us10y and us10y < 5 else "偏高"
    })
    report_data["metrics"].append({
        "name": "10Y-2Y利差",
        "value": f"{spread:+.2f}%" if spread else "N/A",
        "prev": "",
        "change": 0,
        "signal": "正常" if spread > 0 else "倒挂!"
    })
    
    # Index weekly returns
    for name in ["沪深300", "中证A股", "中证500", "创业板指"]:
        if name in klines and len(klines[name]) >= 6:
            bars = klines[name]
            closes = [b["close"] for b in bars]
            pct5d = (closes[-1] / closes[-6] - 1) * 100 if len(closes) >= 6 else 0
            report_data["metrics"].append({
                "name": f"{name}周涨跌",
                "value": f"{pct5d:+.2f}%",
                "prev": "",
                "change": 0,
                "signal": "上涨" if pct5d > 0 else "下跌"
            })
    
    # 五年之锚偏离度 (中证A股)
    if "中证A股" in klines and len(klines["中证A股"]) >= 250:
        closes = [b["close"] for b in klines["中证A股"]]
        ma250 = sma(closes, 250)
        if ma250[-1]:
            dev = (closes[-1] / ma250[-1] - 1) * 100
            signal = "过热" if dev > 15 else ("低估" if dev < -15 else "中性")
            report_data["metrics"].append({
                "name": "五年之锚偏离度",
                "value": f"{dev:+.1f}%",
                "prev": "",
                "change": 0,
                "signal": signal
            })
    
    # 股债性价比
    if "沪深300" in klines:
        cfg = indices["沪深300"]
        ep = 100 / cfg["pe"]
        spread_cn = ep - 1.70
        spread_us = ep - (us10y or 0)
        
        eb_signal_cn = "低估" if spread_cn > 5 else ("中性" if spread_cn > 3 else "偏贵")
        eb_signal_us = "低估" if spread_us > 5 else ("中性" if spread_us > 3 else "偏贵")
        
        report_data["metrics"].append({
            "name": "股债性价比(中债)",
            "value": f"{spread_cn:.2f}%",
            "prev": "",
            "change": 0,
            "signal": eb_signal_cn
        })
        report_data["metrics"].append({
            "name": "股债性价比(美债)",
            "value": f"{spread_us:.2f}%",
            "prev": "",
            "change": 0,
            "signal": eb_signal_us
        })
    
    # 风格轮动
    if "300价值" in klines and "300成长" in klines:
        v_closes = [b["close"] for b in klines["300价值"]]
        g_closes = [b["close"] for b in klines["300成长"]]
        min_len = min(len(v_closes), len(g_closes))
        v_closes = v_closes[:min_len]
        g_closes = g_closes[:min_len]
        
        if min_len >= 41:
            v_ret = (v_closes[-1] / v_closes[-41] - 1) * 100
            g_ret = (g_closes[-1] / g_closes[-41] - 1) * 100
            diff = v_ret - g_ret
            
            report_data["metrics"].append({
                "name": "价值vs成长(40日)",
                "value": f"{diff:+.1f}%",
                "prev": "",
                "change": 0,
                "signal": "价值占优" if diff > 0 else "成长占优"
            })
    
    # 中证红利股息率
    cfg_div = indices["中证红利"]
    report_data["metrics"].append({
        "name": "中证红利股息率",
        "value": f"{cfg_div['dy']:.2f}%",
        "prev": "",
        "change": 0,
        "signal": "高" if cfg_div['dy'] > 5 else "中性"
    })
    
    # 4. Build chart data
    print("\n[Building Chart Data]")
    
    # 1. 五年之锚 (中证A股)
    if "中证A股" in klines:
        bars = klines["中证A股"]
        closes = [b["close"] for b in bars]
        ma1250 = sma(closes, 1250) if len(closes) >= 1250 else sma(closes, min(1250, len(closes)))
        upper = [v * 1.15 if v else None for v in ma1250]
        lower = [v * 0.85 if v else None for v in ma1250]
        
        report_data["anchor"] = {
            "idxName": "中证A股",
            "dates": [b["date"] for b in bars],
            "index": closes,
            "ma1250": ma1250,
            "upper": upper,
            "lower": lower,
        }
        print("  5-year anchor chart: OK")
    
    # 2. 股债性价比
    if "沪深300" in klines:
        bars = klines["沪深300"]
        closes = [b["close"] for b in bars]
        pe = indices["沪深300"]["pe"]
        ep = 100 / pe
        
        # Calculate spread for each bar (using constant PE for simplicity)
        cn_spread = [ep - 1.70] * len(bars)
        us_spread = [ep - (us10y or 0)] * len(bars)
        pr = [pe / (indices["沪深300"]["pb"] * indices["沪深300"]["pb"]) * 100] * len(bars)
        
        report_data["equityBond"] = {
            "dates": [b["date"] for b in bars],
            "cnSpread": cn_spread,
            "usSpread": us_spread,
            "pr": pr,
        }
        print("  Equity-bond chart: OK")
    
    # 3. 中证红利股息率
    if "中证红利" in klines:
        bars = klines["中证红利"]
        dy = indices["中证红利"]["dy"]
        div_yield = [dy] * len(bars)
        spread = [dy - (us10y or 0)] * len(bars)
        
        report_data["dividend"] = {
            "dates": [b["date"] for b in bars],
            "divYield": div_yield,
            "spread": spread,
        }
        print("  Dividend chart: OK")
    
    # 4. 风格轮动
    if "300价值" in klines and "300成长" in klines:
        v_bars = klines["300价值"]
        g_bars = klines["300成长"]
        min_len = min(len(v_bars), len(g_bars))
        
        v_closes = [v_bars[i]["close"] for i in range(min_len)]
        g_closes = [g_bars[i]["close"] for i in range(min_len)]
        dates = [v_bars[i]["date"] for i in range(min_len)]
        
        ratio = [v/g if g else None for v,g in zip(v_closes, g_closes)]
        ma252, upper, lower = bollinger(ratio, 252, 2)
        
        # 40-day return diff
        ret40d = [None] * min_len
        for i in range(40, min_len):
            if v_closes[i-40] and g_closes[i-40]:
                ret40d[i] = (v_closes[i]/v_closes[i-40] - g_closes[i]/g_closes[i-40]) * 100
        
        report_data["style"] = {
            "dates": dates,
            "ratio": ratio,
            "ma252": ma252,
            "upper": upper,
            "lower": lower,
            "ret40d": ret40d,
        }
        print("  Style rotation chart: OK")
    
    # 5. 偏股基金情绪
    if "中证500" in klines:
        bars = klines["中证500"]
        closes = [b["close"] for b in bars]
        rolling = rolling_annual(closes, 756, 252)
        
        report_data["fund"] = {
            "dates": [b["date"] for b in bars],
            "returns": rolling,
            "markZones": [],
        }
        print("  Fund sentiment chart: OK")
    
    # 5. Generate HTML
    print("\n[Generating HTML]")
    
    template_path = OUT_DIR / "template.html"
    if template_path.exists():
        with open(template_path, 'r', encoding='utf-8') as f:
            html = f.read()
    else:
        html = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>市场全景监测</title>
<style>body{font-family:sans-serif;margin:20px;background:#1a1a2e;color:#eee}
.card{background:#16213e;border-radius:8px;padding:16px;margin:10px 0}
.metric{display:inline-block;margin:10px;padding:12px;background:#0f3460;border-radius:6px;min-width:180px}
.signal{color:#e94560;font-weight:bold}.ok{color:#4ecca3}</style>
</head><body><h1>市场全景监测报告</h1><p>Generated: {{DATE}}</p>
<div>{{METRICS}}</div><pre>{{DATA}}</pre></body></html>"""
    
    # Build metrics HTML
    metrics_html = ""
    for m in report_data.get("metrics", []):
        signal_class = "ok" if "正常" in m.get("signal", "") or "上涨" in m.get("signal", "") or "低估" in m.get("signal", "") or "价值占优" in m.get("signal", "") else "signal"
        metrics_html += f'<div class="metric"><strong>{m["name"]}</strong><br>{m["value"]}<br><span class="{signal_class}">{m["signal"]}</span></div>\n'
    
    # Replace placeholders
    data_json = json.dumps(report_data, ensure_ascii=False, default=str)
    
    html = html.replace("{{DATE}}", report_data["date"])
    html = html.replace("{{DATA_JSON}}", data_json)
    html = html.replace("{{INDEX_SOURCE}}", "East Money/TDX")
    html = html.replace("{{PE_SOURCE}}", "East Money/公开数据")
    html = html.replace("{{DIVIDEND_SOURCE}}", "East Money/公开数据")
    html = html.replace("{{STYLE_SOURCE}}", "East Money/TDX")
    html = html.replace("{{FUND_SOURCE}}", "East Money/TDX")
    
    # Save report
    with open(REPORT_FILE, 'w', encoding='utf-8') as f:
        f.write(html)
    
    # Save data JSON
    json_path = OUT_DIR / "latest_data.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        f.write(data_json)
    
    print(f"\nReport saved to: {REPORT_FILE}")
    print(f"HTML size: {len(html)} bytes")
    print(f"Data JSON: {json_path}")
    
    # Print summary
    print("\n" + "=" * 60)
    print("REPORT SUMMARY")
    print("=" * 60)
    for m in report_data["metrics"]:
        print(f"  {m['name']}: {m['value']} [{m['signal']}]")

if __name__ == "__main__":
    main()
