#!/usr/bin/env python3
"""
Generate market monitoring report from pre-collected data.
Usage: uv run python generate_report.py < data.json
"""
import json, sys
from pathlib import Path
from datetime import datetime

OUT_DIR = Path(__file__).parent
REPORT_FILE = OUT_DIR / "index.html"

def sma(data, period):
    result = [None] * len(data)
    for i in range(len(data)):
        if i < period - 1:
            continue
        window = data[i-period+1:i+1]
        result[i] = sum(window) / len(window)
    return result

def generate_html(data):
    """Generate HTML from data dict"""
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
    for m in data.get("metrics", []):
        signal_class = "ok" if "正常" in m.get("signal", "") or "上涨" in m.get("signal", "") or "低估" in m.get("signal", "") or "价值占优" in m.get("signal", "") else "signal"
        metrics_html += f'<div class="metric"><strong>{m["name"]}</strong><br>{m["value"]}<br><span class="{signal_class}">{m["signal"]}</span></div>\n'

    # Replace placeholders
    date_str = data.get("date", datetime.now().strftime("%Y-%m-%d %H:%M"))
    data_json = json.dumps(data, ensure_ascii=False, default=str)
    
    html = html.replace("{{DATE}}", date_str)
    html = html.replace("{{METRICS}}", metrics_html)
    html = html.replace("{{DATA}}", data_json)
    
    return html, data_json

def main():
    # Read data from stdin
    raw = sys.stdin.read()
    if not raw:
        print("No data provided", file=sys.stderr)
        sys.exit(1)
    
    data = json.loads(raw)
    
    # Generate HTML
    html, data_json = generate_html(data)
    
    with open(REPORT_FILE, 'w', encoding='utf-8') as f:
        f.write(html)
    
    # Save data JSON
    json_path = OUT_DIR / "latest_data.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        f.write(data_json)
    
    print(f"Report saved to: {REPORT_FILE}")
    print(f"HTML size: {len(html)} bytes")
    print(f"Data JSON: {json_path}")

if __name__ == "__main__":
    main()
