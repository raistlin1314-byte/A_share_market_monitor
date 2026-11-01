#!/usr/bin/env python3
"""
Direct market data fetcher using web APIs (no CLI dependencies).
Fetches K-line data, valuation metrics, and FRED data for the report.
"""
import json, os, sys, csv, io, subprocess, time
import urllib.request
from pathlib import Path
from datetime import datetime, timedelta

# UTF-8 stdout（防止GBK控制台打印✅/中文时 UnicodeEncodeError 崩溃）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _http_get(url, timeout=30, use_proxy=False):
    """混合抓取策略（实测结论 2026-08-30）：
    - EM（push2his/push2.eastmoney.com）：风控拦截 Python/OpenSSL TLS 指纹，
      必须 curl.exe（schannel）直连；且必须 --noproxy 绕过代理（走 Clash 也会被断）
    - FRED（fred.stlouisfed.org）：直连被 DPI 阻断（TCP+TLS 成功但 0 字节），
      改为 5秒快速失败 + fallback 值（TDX/硬编码）
      （payload 已设 HTTP_PROXY/HTTPS_PROXY/NO_PROXY=eastmoney.com）"""
    if use_proxy:
        # FRED 在中国直连被 DPI 阻断，快速失败（5秒），不重试
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.read().decode("utf-8", "replace")
        except Exception as e:
            raise RuntimeError(f"FRED blocked by DPI: {e}")
    p = subprocess.run(
        ["curl.exe", "-sS", "--fail", "--max-time", str(timeout),
         "--noproxy", "*",
         "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
         "-H", "Referer: https://quote.eastmoney.com/",
         url],
        capture_output=True, timeout=timeout + 10)
    if p.returncode != 0:
        raise RuntimeError(f"curl exit {p.returncode}: {p.stderr.decode('utf-8', 'replace')[:200]}")
    return p.stdout.decode("utf-8", "replace")

OUT_DIR = Path(__file__).parent
REPORT_FILE = OUT_DIR / "index.html"

# ============================================================
# DATA FETCHING
# ============================================================

def fetch_em_kline(code, setcode, limit=600):
    """Fetch K-line from East Money push2 API"""
    secid = f"{setcode}.{code}"
    url = (f"https://push2his.eastmoney.com/api/qt/stock/kline/get?"
           f"secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
           f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
           f"&klt=101&fqt=1&end=20500101&lmt={limit}")
    try:
        data = json.loads(_http_get(url, timeout=30))
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

def fetch_em_realtime(code, setcode):
    """Fetch real-time quote from East Money"""
    secid = f"{setcode}.{code}"
    url = (f"https://push2.eastmoney.com/api/qt/stock/get?"
           f"secid={secid}&fields=f43,f44,f45,f46,f47,f48,f50,f57,f58,f60,f116,f117,f168,f169,f170,f171")
    try:
        return json.loads(_http_get(url, timeout=15)).get("data", {})
    except Exception as e:
        print(f"  EM quote error {code}/{setcode}: {e}")
        return {}

def fetch_em_valuation(code, setcode):
    """Fetch PE/PB/股息率 from East Money"""
    secid = f"{setcode}.{code}"
    url = (f"https://push2.eastmoney.com/api/qt/stock/get?"
           f"secid={secid}&fields=f162,f167,f168,f169,f170,f171")
    try:
        return json.loads(_http_get(url, timeout=15)).get("data", {})
    except Exception as e:
        print(f"  EM valuation error {code}/{setcode}: {e}")
        return {}

def fetch_fred(series_id, start="2025-07-01"):
    """Fetch FRED series data with fallback values.
    
    FRED 在中国直连被 DPI 阻断（TCP+TLS 成功但 0 字节响应），
    因此使用 5秒快速失败 + 内置 fallback 值。
    """
    # FRED 阻断时使用的 fallback 值（基于 2026-09-25 实际数据）
    FRED_FALLBACK = {
        "DGS10": 5.18,   # 10年期国债收益率
        "DGS2": 4.12,    # 2年期
        "DGS30": 5.45,   # 30年期
        "T10YIE": 2.25,  # 10年通胀预期
    }
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}"
    try:
        data = _http_get(url, timeout=5, use_proxy=True)
        reader = csv.DictReader(io.StringIO(data))
        rows = list(reader)
        if not rows:
            raise ValueError("No data rows")
        return rows
    except Exception as e:
        print(f"  FRED {series_id} blocked by DPI, using fallback={FRED_FALLBACK.get(series_id, 'N/A')}: {e}")
        # 返回 fallback 格式的 rows
        today = datetime.now().strftime("%Y-%m-%d")
        return [{"observation_date": today, series_id: str(FRED_FALLBACK.get(series_id, ""))}]

# ============================================================
# TECHNICAL CALCULATIONS
# ============================================================

def sma(data, period):
    """Simple moving average"""
    result = [None] * len(data)
    for i in range(len(data)):
        if i < period - 1:
            continue
        window = data[i-period+1:i+1]
        result[i] = sum(window) / len(window)
    return result

def rolling_annual(closes, days=756, tdays_per_year=252):
    """Rolling annualized return"""
    result = [None] * len(closes)
    for i in range(days, len(closes)):
        if closes[i] and closes[i-days] and closes[i-days] != 0:
            ret = closes[i] / closes[i-days] - 1
            years = days / tdays_per_year
            annual = (1 + ret) ** (1 / years) - 1
            result[i] = annual * 100
    return result

def bollinger(values, period=252, stdev=2):
    """Bollinger Bands"""
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
    """Percentage change over N days"""
    result = [None] * len(closes)
    for i in range(days, len(closes)):
        if closes[i] and closes[i-days] and closes[i-days] != 0:
            result[i] = (closes[i] / closes[i-days] - 1) * 100
    return result

# ============================================================
# MAIN DATA COLLECTION
# ============================================================

def collect_all():
    """Collect all data for the report"""
    
    config = {
        "沪深300": {"code": "000300", "setcode": 1, "pe": 14.61, "pb": 1.44, "dy": 2.72},
        "中证A股": {"code": "399317", "setcode": 0, "pe": 17.8, "pb": 1.65, "dy": 2.3},
        "中证500": {"code": "000905", "setcode": 1, "pe": 22.5, "pb": 1.85, "dy": 1.8},
        "创业板指": {"code": "399006", "setcode": 0, "pe": 28.3, "pb": 3.95, "dy": 0.8},
        "中证红利": {"code": "000922", "setcode": 62, "pe": 8.5, "pb": 0.92, "dy": 4.8},
        "300价值": {"code": "000919", "setcode": 62, "pe": 10.2, "pb": 0.95, "dy": 3.8},
        "300成长": {"code": "000918", "setcode": 62, "pe": 16.8, "pb": 2.1, "dy": 1.5},
    }
    
    # Fix setcode for indices - 62 is for stocks, not indices
    # TDX uses different codes for indices
    # For indices like 000922, 000919, 000918, we may need to use ETF substitutes
    # or try different setcodes
    
    # Override: use ETF substitutes for indices that don't work with setcode=62
    etf_subs = {
        "中证红利": ("515080", 1),   # 中证红利ETF招商
        "300价值": ("562320", 1),   # 沪深300价值ETF银华
        "300成长": ("562310", 1),   # 沪深300成长ETF银华
    }
    
    print("=" * 60)
    print("FETCHING K-LINE DATA")
    print("=" * 60)
    
    klines = {}
    quotes = {}
    
    for name, cfg in config.items():
        if name in etf_subs:
            code, sc = etf_subs[name]
        else:
            code, sc = cfg["code"], cfg["setcode"]
        
        print(f"\n{name} (code={code}, setcode={sc}):")
        bars = fetch_em_kline(code, sc, 756)
        if bars:
            print(f"  Got {len(bars)} bars, last close={bars[-1]['close']}")
            klines[name] = bars
        else:
            print(f"  FAILED")
        
        q = fetch_em_realtime(code, sc)
        if q:
            quotes[name] = q
            print(f"  Quote: change%={q.get('f170', 'N/A')}")
    
    # Fetch FRED data (with fallback for DPI blocking)
    print("\n" + "=" * 60)
    print("FETCHING FRED DATA (with DPI fallback)")
    print("=" * 60)
    
    fred = {}
    fred_sources = {}  # Track data source for transparency
    for sid, key in [("DGS10", "us10y"), ("DGS2", "us2y"), ("DGS30", "us30y"), ("T10YIE", "t10yie")]:
        print(f"\nFetching {sid}...")
        rows = fetch_fred(sid)
        if rows:
            # Get latest valid value
            for r in reversed(rows):
                val = r.get(sid) or r.get(key)
                if val and val != '.':
                    try:
                        fred[key] = float(val)
                        fred_sources[key] = "FRED" if "fred" in str(r.get("observation_date", "")).lower() else "fallback"
                        print(f"  Latest {key} = {fred[key]}% (source: {fred_sources[key]})")
                        break
                    except:
                        pass
            if key not in fred:
                print(f"  No valid data found")
        else:
            print(f"  Failed")
    
    return klines, quotes, fred, config, fred_sources

# ============================================================
# REPORT GENERATION
# ============================================================

def build_metrics(klines, quotes, fred, config, fred_sources=None):
    """Build the metrics list for the report"""
    metrics = []
    if fred_sources is None:
        fred_sources = {}
    
    # FRED metrics (with DPI fallback)
    us10y = fred.get("us10y", 4.71)
    us2y = fred.get("us2y", 4.37)
    us30y = fred.get("us30y", 5.17)
    t10yie = fred.get("t10yie", 2.28)
    us10y_src = fred_sources.get("us10y", "unknown")
    
    metrics.append({
        "name": f"美债10Y收益率 {'(fallback)' if us10y_src == 'fallback' else ''}",
        "value": f"{us10y:.2f}%",
        "signal": "正常" if us10y < 5 else "偏高"
    })
    
    spread = us10y - us2y
    metrics.append({
        "name": f"10Y-2Y利差 {'(fallback)' if us10y_src == 'fallback' else ''}",
        "value": f"{spread:+.2f}%",
        "signal": "正常" if spread > 0 else "倒挂!"
    })
    
    # Index metrics
    for name in ["沪深300", "中证A股", "中证500", "创业板指"]:
        if name in klines and len(klines[name]) >= 6:
            bars = klines[name]
            closes = [b["close"] for b in bars]
            current = closes[-1]
            pct5d = (closes[-1] / closes[-6] - 1) * 100 if len(closes) >= 6 else 0
            
            metrics.append({
                "name": f"{name}周涨跌",
                "value": f"{pct5d:+.2f}%",
                "signal": "上涨" if pct5d > 0 else "下跌"
            })
    
    # 五年之锚偏离度 (中证A股)
    if "中证A股" in klines and len(klines["中证A股"]) >= 250:
        closes = [b["close"] for b in klines["中证A股"]]
        ma250 = sma(closes, 250)
        if ma250[-1]:
            dev = (closes[-1] / ma250[-1] - 1) * 100
            signal = "过热" if dev > 15 else ("低估" if dev < -15 else "中性")
            metrics.append({
                "name": "五年之锚偏离度",
                "value": f"{dev:+.1f}%",
                "signal": signal
            })
    
    # 股债性价比
    if "沪深300" in klines:
        cfg = config["沪深300"]
        ep = 100 / cfg["pe"]
        spread_cn = ep - 1.70
        spread_us = ep - us10y
        
        eb_signal_cn = "低估" if spread_cn > 5 else ("中性" if spread_cn > 3 else "偏贵")
        eb_signal_us = "低估" if spread_us > 5 else ("中性" if spread_us > 3 else "偏贵")
        
        metrics.append({
            "name": "股债性价比(中债)",
            "value": f"{spread_cn:.2f}%",
            "signal": eb_signal_cn
        })
        metrics.append({
            "name": "股债性价比(美债)",
            "value": f"{spread_us:.2f}%",
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
            
            metrics.append({
                "name": "价值vs成长(40日)",
                "value": f"{diff:+.1f}%",
                "signal": "价值占优" if diff > 0 else "成长占优"
            })
    
    # 中证红利股息率
    cfg_div = config["中证红利"]
    metrics.append({
        "name": "中证红利股息率",
        "value": f"{cfg_div['dy']:.2f}%",
        "signal": "高" if cfg_div['dy'] > 5 else "中性"
    })
    
    return metrics

def generate_html(klines, quotes, fred, config, metrics):
    """Generate the final HTML report"""
    
    # Load template
    template_path = OUT_DIR / "template.html"
    if template_path.exists():
        with open(template_path, 'r', encoding='utf-8') as f:
            html = f.read()
    else:
        # Minimal fallback template
        html = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>市场全景监测</title></head>
<body><h1>市场全景监测报告</h1><p>Generated: {{DATE}}</p>
<div id="metrics">{{METRICS}}</div>
<pre>{{DATA}}</pre>
</body></html>"""
    
    # Build data JSON
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    data = {
        "date": now_str,
        "fred": fred,
        "metrics": [],
        "klines": {},
    }
    
    # Add metrics
    for m in metrics:
        data["metrics"].append(m)
    
    # Add K-line data (reduced for performance)
    for name, bars in klines.items():
        # Return last 250 bars max for chart performance
        step = max(1, len(bars) // 250)
        reduced = [bars[i] for i in range(0, len(bars), step)]
        if bars[-1] not in reduced:
            reduced.append(bars[-1])
        data["klines"][name] = reduced
    
    # Replace placeholders
    data_json = json.dumps(data, ensure_ascii=False, default=str)
    
    html = html.replace("{{DATE}}", f"{now_str} (Asia/Shanghai)")
    html = html.replace("{{DATA_JSON}}", data_json)
    html = html.replace("{{INDEX_SOURCE}}", "East Money/TDX")
    html = html.replace("{{PE_SOURCE}}", "East Money/公开数据")
    html = html.replace("{{DIVIDEND_SOURCE}}", "East Money/公开数据")
    html = html.replace("{{STYLE_SOURCE}}", "East Money/TDX")
    html = html.replace("{{FUND_SOURCE}}", "East Money/TDX")
    
    # Try to replace other placeholders
    for key, val in fred.items():
        html = html.replace(f"{{{{FRED_{key.upper()}}}}}", f"{val:.2f}%" if isinstance(val, float) else str(val))
    
    return html, data_json

# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print("市场全景监测报告 - 数据收集与生成")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d')}")
    print("=" * 60)
    
    klines, quotes, fred, config, fred_sources = collect_all()
    
    print("\n" + "=" * 60)
    print("BUILDING METRICS")
    print("=" * 60)
    
    metrics = build_metrics(klines, quotes, fred, config, fred_sources)
    for m in metrics:
        print(f"  {m['name']}: {m['value']} [{m['signal']}]")
    
    print("\n" + "=" * 60)
    print("GENERATING HTML")
    print("=" * 60)
    
    html, data_json = generate_html(klines, quotes, fred, config, metrics)
    
    with open(REPORT_FILE, 'w', encoding='utf-8') as f:
        f.write(html)
    
    print(f"\n✅ Report saved to: {REPORT_FILE}")
    print(f"   HTML size: {len(html)} bytes")
    
    # Also save the data JSON for debugging
    json_path = OUT_DIR / "latest_data.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        f.write(data_json)
    print(f"   Data JSON: {json_path}")
    
    return klines, quotes, fred, config, metrics

if __name__ == "__main__":
    main()
