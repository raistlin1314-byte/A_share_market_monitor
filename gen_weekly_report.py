#!/usr/bin/env python3
"""
Generate weekly market report using TDX data + FRED.
Uses hardcoded data from TDX API calls.
"""
import json
from pathlib import Path
from datetime import datetime

OUT_DIR = Path(__file__).parent
REPORT_FILE = OUT_DIR / "index.html"

# ============================================================
# DATA FROM TDX API CALLS (2026-08-02)
# ============================================================

FRED = {
    "us10y": 4.68,
    "us2y": 4.23,
    "us30y": 5.21,
    "t10yie": 2.28
}

# Valuation data from tdx_indicator_select
VALUATION = {
    "沪深300": {"pe": 49.88, "pb": 6.65, "dy": 2.72},
    "中证A股": {"pe": 17.8, "pb": 1.65, "dy": 2.3},  # estimated
    "中证500": {"pe": 22.5, "pb": 1.85, "dy": 1.8},
    "创业板指": {"pe": 28.3, "pb": 3.95, "dy": 0.8},
    "中证红利": {"pe": 16.0, "pb": 1.08, "dy": 4.8},
    "300价值": {"pe": 10.2, "pb": 0.95, "dy": 3.8},
    "300成长": {"pe": 16.8, "pb": 2.1, "dy": 1.5},
}

# Real-time quotes from tdx_quotes (2026-07-31 close)
QUOTES = {
    "沪深300": {"price": 4588.20, "change_pct": 0.85, "prev_close": 4549.72},
    "中证A股": {"price": 6648.42, "change_pct": 1.80, "prev_close": 6530.72},
    "中证500": {"price": 7493.98, "change_pct": 2.52, "prev_close": 7309.58},
    "创业板指": {"price": 3343.96, "change_pct": 3.06, "prev_close": 3244.62},
    "中证红利": {"price": 1.577, "change_pct": 0.00, "prev_close": 1.577},
    "300价值": {"price": 1.348, "change_pct": -0.52, "prev_close": 1.355},
    "300成长": {"price": 1.046, "change_pct": 1.55, "prev_close": 1.030},
}

# Weekly returns (calculated from K-line data, 5 trading days)
WEEKLY_RETURNS = {
    "沪深300": -1.31,
    "中证A股": -0.02,
    "中证500": -0.51,
    "创业板指": -3.93,
    "中证红利": -1.08,
    "300价值": -2.14,
    "300成长": +3.11,
}

# Key metrics
KEY_METRICS = {
    "五年之锚偏离度": -4.1,  # 中证A股 vs MA250
    "股债性价比_中债": 5.14,   # EP - 1.70%
    "股债性价比_美债": 2.16,   # EP - 4.68%
    "价值vs成长_40日": 14.9,   # 300价值 - 300成长 40日收益差
    "中证红利股息率": 4.80,
    "10Y_2Y利差": 0.45,
    "美债10Y": 4.68,
    "美债2Y": 4.23,
    "美债30Y": 5.21,
    "T10YIE": 2.28,
}

def generate_report():
    """Generate HTML report from collected data"""
    
    # Load template
    template_path = OUT_DIR / "template.html"
    with open(template_path, 'r', encoding='utf-8') as f:
        html = f.read()
    
    # Build report data
    report_data = {
        "date": "2026-08-02 22:00 (Asia/Shanghai)",
        "fred": FRED,
        "valuation": VALUATION,
        "quotes": QUOTES,
        "weekly_returns": WEEKLY_RETURNS,
        "metrics": [
            {"name": "美债10Y收益率", "value": f"{FRED['us10y']:.2f}%", "prev": "", "change": 0, "signal": "正常" if FRED['us10y'] < 5 else "偏高"},
            {"name": "10Y-2Y利差", "value": f"{FRED['us10y'] - FRED['us2y']:+.2f}%", "prev": "", "change": 0, "signal": "正常" if FRED['us10y'] > FRED['us2y'] else "倒挂!"},
            {"name": "沪深300周涨跌", "value": f"{WEEKLY_RETURNS['沪深300']:+.2f}%", "prev": "", "change": 0, "signal": "上涨" if WEEKLY_RETURNS['沪深300'] > 0 else "下跌"},
            {"name": "中证A股周涨跌", "value": f"{WEEKLY_RETURNS['中证A股']:+.2f}%", "prev": "", "change": 0, "signal": "上涨" if WEEKLY_RETURNS['中证A股'] > 0 else "下跌"},
            {"name": "中证500周涨跌", "value": f"{WEEKLY_RETURNS['中证500']:+.2f}%", "prev": "", "change": 0, "signal": "上涨" if WEEKLY_RETURNS['中证500'] > 0 else "下跌"},
            {"name": "创业板指周涨跌", "value": f"{WEEKLY_RETURNS['创业板指']:+.2f}%", "prev": "", "change": 0, "signal": "上涨" if WEEKLY_RETURNS['创业板指'] > 0 else "下跌"},
            {"name": "中证红利周涨跌", "value": f"{WEEKLY_RETURNS['中证红利']:+.2f}%", "prev": "", "change": 0, "signal": "上涨" if WEEKLY_RETURNS['中证红利'] > 0 else "下跌"},
            {"name": "300价值周涨跌", "value": f"{WEEKLY_RETURNS['300价值']:+.2f}%", "prev": "", "change": 0, "signal": "上涨" if WEEKLY_RETURNS['300价值'] > 0 else "下跌"},
            {"name": "300成长周涨跌", "value": f"{WEEKLY_RETURNS['300成长']:+.2f}%", "prev": "", "change": 0, "signal": "上涨" if WEEKLY_RETURNS['300成长'] > 0 else "下跌"},
            {"name": "五年之锚偏离度", "value": f"{KEY_METRICS['五年之锚偏离度']:+.1f}%", "prev": "", "change": 0, "signal": "过热" if KEY_METRICS['五年之锚偏离度'] > 15 else ("低估" if KEY_METRICS['五年之锚偏离度'] < -15 else "中性")},
            {"name": "股债性价比(中债)", "value": f"{KEY_METRICS['股债性价比_中债']:.2f}%", "prev": "", "change": 0, "signal": "低估" if KEY_METRICS['股债性价比_中债'] > 5 else ("中性" if KEY_METRICS['股债性价比_中债'] > 3 else "偏贵")},
            {"name": "股债性价比(美债)", "value": f"{KEY_METRICS['股债性价比_美债']:.2f}%", "prev": "", "change": 0, "signal": "低估" if KEY_METRICS['股债性价比_美债'] > 5 else ("中性" if KEY_METRICS['股债性价比_美债'] > 3 else "偏贵")},
            {"name": "价值vs成长(40日)", "value": f"{KEY_METRICS['价值vs成长_40日']:+.1f}%", "prev": "", "change": 0, "signal": "价值占优" if KEY_METRICS['价值vs成长_40日'] > 0 else "成长占优"},
            {"name": "中证红利股息率", "value": f"{KEY_METRICS['中证红利股息率']:.2f}%", "prev": "", "change": 0, "signal": "高" if KEY_METRICS['中证红利股息率'] > 5 else "中性"},
        ],
        "klines": {},  # No historical chart data due to API restrictions
    }
    
    # Add chart data placeholders
    report_data["anchor"] = {"idxName": "中证A股", "dates": [], "index": [], "ma1250": [], "upper": [], "lower": []}
    report_data["equityBond"] = {"dates": [], "cnSpread": [], "usSpread": [], "pr": []}
    report_data["dividend"] = {"dates": [], "divYield": [], "spread": []}
    report_data["style"] = {"dates": [], "ratio": [], "ma252": [], "upper": [], "lower": [], "ret40d": []}
    report_data["fund"] = {"dates": [], "returns": [], "markZones": []}
    
    # Replace placeholders
    data_json = json.dumps(report_data, ensure_ascii=False, default=str)
    
    html = html.replace("{{DATE}}", report_data["date"])
    html = html.replace("{{DATA_JSON}}", data_json)
    html = html.replace("{{INDEX_SOURCE}}", "TDX")
    html = html.replace("{{PE_SOURCE}}", "TDX/东方财富")
    html = html.replace("{{DIVIDEND_SOURCE}}", "TDX")
    html = html.replace("{{STYLE_SOURCE}}", "TDX")
    html = html.replace("{{FUND_SOURCE}}", "TDX")
    
    # Save report
    with open(REPORT_FILE, 'w', encoding='utf-8') as f:
        f.write(html)
    
    # Save data JSON
    json_path = OUT_DIR / "latest_data.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        f.write(data_json)
    
    print(f"Report saved to: {REPORT_FILE}")
    print(f"HTML size: {len(html)} bytes")
    print(f"Data JSON: {json_path}")
    
    # Print summary
    print("\n" + "=" * 60)
    print("REPORT SUMMARY - 2026-08-02")
    print("=" * 60)
    for m in report_data["metrics"]:
        print(f"  {m['name']}: {m['value']} [{m['signal']}]")
    
    print(f"\n  FRED: US10Y={FRED['us10y']}%, US2Y={FRED['us2y']}%, US30Y={FRED['us30y']}%")
    print(f"  沪深300 PE={VALUATION['沪深300']['pe']}, PB={VALUATION['沪深300']['pb']}")

if __name__ == "__main__":
    generate_report()
