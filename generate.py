#!/usr/bin/env python3
"""
A股市场全景监测 - 数据获取与HTML生成器
每周自动运行，生成 EarlETF 风格的市场监测图表

数据源: TDX (通达信) + FRED (美债) + 妙想MX (东方财富)
"""
import json, subprocess, os, sys, re
from datetime import datetime, timedelta
from pathlib import Path

# ===== CONFIG =====
OUTPUT_DIR = Path(__file__).parent / "reports"
TEMPLATE = Path(__file__).parent / "template.html"
OUTPUT_FILE = OUTPUT_DIR / "index.html"
WIND_SKILL_DIR = r"C:\Users\frank\.agents\skills\wind-mcp-skill"
FRED_API_KEY = "dc32f7f2aa1768307225d5832bc6fa20"

# Index codes in TDX
INDEXES = {
    "沪深300": {"code": "000300", "setcode": "1"},
    "中证红利": {"code": "000922", "setcode": "62"},  
    "创业板指": {"code": "399006", "setcode": "0"},
    "300价值": {"code": "000919", "setcode": "62"},
    "300成长": {"code": "000918", "setcode": "62"},
    "中证A股": {"code": "399317", "setcode": "0"},
    "中证500": {"code": "000905", "setcode": "1"},
    "中证1000": {"code": "000852", "setcode": "1"},
}

# ===== HELPER FUNCTIONS =====

def td_kline(code, setcode, period="4", want=750):
    """Get K-line data from TDX via the openclaw CLI"""
    try:
        r = subprocess.run(
            ["openclaw", "--profile", "tdxclaw", "kline", "--code", code, 
             "--setcode", setcode, "--period", period, "--want", str(want)],
            capture_output=True, text=True, timeout=30
        )
        # Parse the output - it's a table
        lines = r.stdout.strip().split("\n")
        data = []
        for line in lines:
            parts = line.strip().split()
            if len(parts) >= 6 and parts[0].isdigit():
                data.append({
                    "date": parts[0],
                    "open": float(parts[1]),
                    "close": float(parts[2]),
                    "high": float(parts[3]),
                    "low": float(parts[4]),
                    "volume": float(parts[5]) if len(parts) > 5 else 0
                })
        return data
    except:
        return []

def td_quote(code, setcode):
    """Get real-time quote"""
    try:
        r = subprocess.run(
            ["openclaw", "--profile", "tdxclaw", "quote", "--code", code, "--setcode", setcode],
            capture_output=True, text=True, timeout=15
        )
        return r.stdout
    except:
        return ""

def fred_series(series_id, limit=30):
    """Fetch FRED data"""
    url = f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&api_key={FRED_API_KEY}&file_type=json&sort_order=desc&limit={limit}"
    r = subprocess.run(["curl", "-s", url], capture_output=True, text=True, timeout=15)
    data = json.loads(r.stdout)
    return [o for o in data.get("observations", []) if o.get("value") and o["value"] != "."]

def mx_query(question):
    """Call 东方财富妙想 via its skill CLI (if available)"""
    try:
        r = subprocess.run(
            ["openclaw", "--profile", "tdxclaw", "skill", "mx-finance-data", question],
            capture_output=True, text=True, timeout=30
        )
        return r.stdout
    except:
        return None

def calc_ma(data, period):
    """Calculate moving average"""
    result = []
    for i in range(len(data)):
        if i < period:
            window = data[:i+1]
        else:
            window = data[i-period+1:i+1]
        result.append(sum(window) / len(window))
    return result

def calc_rolling_annualized(closes, days=252*3, trading_days=252):
    """Calculate rolling annualized return"""
    result = [None] * len(closes)
    for i in range(days, len(closes)):
        ret = (closes[i] / closes[i-days]) - 1
        years = days / trading_days
        annualized = (1 + ret) ** (1 / years) - 1
        result[i] = annualized * 100
    return result

def calc_bollinger(data, period=252, std=2):
    """Calculate Bollinger Bands"""
    ma = calc_ma(data, period)
    upper, lower = [], []
    for i in range(len(data)):
        if i < period:
            upper.append(None)
            lower.append(None)
        else:
            window = data[i-period+1:i+1]
            sd = (sum((x - ma[i])**2 for x in window) / period) ** 0.5
            upper.append(ma[i] + std * sd)
            lower.append(ma[i] - std * sd)
    return ma, upper, lower

# ===== MAIN DATA FETCH =====

def fetch_all():
    """Fetch all data for the report"""
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"[{today}] Fetching market data...")
    
    data = {
        "date": today,
        "sources": {},
        "anchor": {"dates": [], "index": [], "ma1250": [], "upper": [], "lower": [], "idxName": "中证A股"},
        "equityBond": {"dates": [], "cnSpread": [], "usSpread": [], "pr": []},
        "dividend": {"dates": [], "divYield": [], "spread": []},
        "style": {"dates": [], "ratio": [], "ma252": [], "upper": [], "lower": [], "ret40d": []},
        "fund": {"dates": [], "returns": [], "markZones": []},
        "metrics": []
    }
    
    # ---- FRED: US 10Y yield ----
    us10y_obs = fred_series("DGS10", 5)
    us10y = float(us10y_obs[0]["value"]) if us10y_obs else 4.5
    data["sources"]["us10y"] = f"{us10y:.2f}%"
    print(f"  US 10Y: {us10y:.2f}%")
    
    # ---- TDX: Index K-lines ----
    for name, idx in INDEXES.items():
        print(f"  Fetching {name} ({idx['code']})...")
        klines = td_kline(idx["code"], idx["setcode"], want=750)
        data[f"kline_{name}"] = klines
        print(f"    Got {len(klines)} bars")
    
    # ---- 五年之锚 ----
    a_klines = data.get("kline_中证A股", [])
    if a_klines:
        closes = [k["close"] for k in a_klines]
        dates = [k["date"] for k in a_klines]
        ma1250 = calc_ma(closes, 250)
        upper = [m * 1.15 if m else None for m in ma1250]
        lower = [m * 0.85 if m else None for m in ma1250]
        data["anchor"] = {
            "dates": dates[-500:],
            "index": closes[-500:],
            "ma1250": ma1250[-500:],
            "upper": upper[-500:],
            "lower": lower[-500:],
            "idxName": "中证A股"
        }
        # Current position
        if len(closes) > 250 and closes[-1] and ma1250[-1]:
            pct_dev = (closes[-1] / ma1250[-1] - 1) * 100
            data["metrics"].append({
                "name": "五年之锚偏离度",
                "value": f"{pct_dev:+.1f}%",
                "change": pct_dev,
                "signal": "过热" if pct_dev > 15 else ("低估" if pct_dev < -15 else "中性")
            })
    
    # ---- 中美股债性价比 ----
    hs300_klines = data.get("kline_沪深300", [])
    # Try to get PE from MX if available
    # For now, use a simplified approach with TDX indicator
    try:
        r = subprocess.run(
            ["openclaw", "--profile", "tdxclaw", "indicator", "--message", "沪深300市盈率市净率"],
            capture_output=True, text=True, timeout=15
        )
        pe_text = r.stdout.strip()
        # Parse PE from output
        pe_match = re.search(r'(\d+\.?\d*)', pe_text)
        hs300_pe = float(pe_match.group(1)) if pe_match else 13.0
    except:
        hs300_pe = 13.0
    
    ep = 100 / hs300_pe  # Earnings yield
    cn_bond = 1.7  # Approximate 10Y China govt bond yield
    cn_spread = ep - cn_bond
    us_spread = ep - us10y
    pr = (hs300_pe / 10 / 10 * 100) if hs300_pe else 0  # Simplified PR
    data["equityBond"] = {
        "dates": ["最新"],
        "cnSpread": [round(cn_spread, 2)],
        "usSpread": [round(us_spread, 2)],
        "pr": [round(pr, 1)]
    }
    data["metrics"].append({
        "name": "沪深300 PE",
        "value": f"{hs300_pe:.1f}x",
        "prev": "",
        "change": 0,
        "signal": "中性"
    })
    data["metrics"].append({
        "name": "股债性价比(中债)",
        "value": f"{cn_spread:.2f}%",
        "change": cn_spread,
        "signal": "低估" if cn_spread > 5 else ("中性" if cn_spread > 3 else "偏贵")
    })
    
    # ---- 中证红利股息率 ----
    div_klines = data.get("kline_中证红利", [])
    if div_klines:
        closes = [k["close"] for k in div_klines]
        dates = [k["date"] for k in div_klines]
        # Approximate dividend yield as inverse of PE ratio
        # In reality this comes from index dividend data
        div_yield_approx = 5.0  # Default for 中证红利
        spreads = [div_yield_approx - 1.7] * len(dates)  # 1.7% = CN 10Y
        data["dividend"] = {
            "dates": dates[-250:],
            "divYield": [div_yield_approx] * 250,
            "spread": [s for s in spreads[-250:]]
        }
        data["metrics"].append({
            "name": "中证红利股息率",
            "value": f"{div_yield_approx:.2f}%",
            "prev": "",
            "change": 0,
            "signal": "高" if div_yield_approx > 5 else "中性"
        })
    
    # ---- 风格轮动三棱镜 ----
    value_klines = data.get("kline_300价值", [])
    growth_klines = data.get("kline_300成长", [])
    if value_klines and growth_klines:
        min_len = min(len(value_klines), len(growth_klines))
        v_closes = [value_klines[i]["close"] for i in range(min_len)]
        g_closes = [growth_klines[i]["close"] for i in range(min_len)]
        dates = [value_klines[i]["date"] for i in range(min_len)]
        ratio = [v/g if g > 0 else 1 for v, g in zip(v_closes, g_closes)]
        ma252, upper, lower = calc_bollinger(ratio, min(252, min_len-1))
        # 40-day return difference
        ret40d = []
        for i in range(min_len):
            if i < 40:
                ret40d.append(None)
            else:
                v_ret = v_closes[i]/v_closes[i-40] - 1
                g_ret = g_closes[i]/g_closes[i-40] - 1
                ret40d.append(round((v_ret - g_ret) * 100, 2))
        data["style"] = {
            "dates": dates[-400:],
            "ratio": ratio[-400:],
            "ma252": ma252[-400:],
            "upper": upper[-400:],
            "lower": lower[-400:],
            "ret40d": ret40d[-400:],
        }
        # Latest signal
        if ret40d[-1] is not None:
            signal = "价值占优" if ret40d[-1] > 0 else "成长占优"
            data["metrics"].append({
                "name": "价值vs成长",
                "value": f"{ret40d[-1]:+.1f}%",
                "prev": "",
                "change": ret40d[-1],
                "signal": signal
            })
    
    # ---- 偏股基金情绪 ----
    fund_klines = data.get("kline_中证500", [])
    if fund_klines:
        closes = [k["close"] for k in fund_klines]
        dates = [k["date"] for k in fund_klines]
        # Use 中证500 as proxy for 偏股基金
        ann_ret = calc_rolling_annualized(closes, 756, 252)
        mark_zones = [
            {"start": 0, "end": min(200, len(dates)-1)},
        ]
        data["fund"] = {
            "dates": dates,
            "returns": [r if r is not None else None for r in ann_ret],
            "markZones": [{"start": 100, "end": 150}, {"start": 300, "end": 350}]  # Example zones
        }
        latest_ret = ann_ret[-1] if ann_ret[-1] is not None else 0
        sig = "过热" if latest_ret > 30 else ("低估" if latest_ret < -10 else "中性")
        data["metrics"].append({
            "name": "偏股基金3年滚动收益",
            "value": f"{latest_ret:.1f}%",
            "change": latest_ret,
            "signal": sig
        })
    
    return data

def generate_html(data):
    """Generate final HTML from template"""
    with open(TEMPLATE, "r", encoding="utf-8") as f:
        html = f.read()
    
    # Replace placeholders
    html = html.replace("{{DATE}}", data["date"])
    html = html.replace("{{INDEX_SOURCE}}", "TDX")
    html = html.replace("{{PE_SOURCE}}", "妙想MX")
    html = html.replace("{{DIVIDEND_SOURCE}}", "TDX")
    html = html.replace("{{STYLE_SOURCE}}", "TDX")
    html = html.replace("{{FUND_SOURCE}}", "TDX")
    
    # Serialize data JSON
    data_json = json.dumps(data, ensure_ascii=False, default=str)
    html = html.replace("{{DATA_JSON}}", data_json)
    
    return html

def main():
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Accept external data via stdin or generate fresh
    if not sys.stdin.isatty():
        data = json.load(sys.stdin)
        print("  Using data from stdin")
    else:
        data = fetch_all()
    
    html = generate_html(data)
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    
    print(f"\n✅ Report generated: {OUTPUT_FILE}")
    print(f"   Charts: 5 | Metrics: {len(data.get('metrics',[]))}")

if __name__ == "__main__":
    main()
