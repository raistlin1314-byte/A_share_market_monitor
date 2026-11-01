import json
with open(r'C:\Users\frank\.openclaw-tdxclaw\workspace\mm_repo\latest_data.json', encoding='utf-8') as f:
    data = json.load(f)
print('Date:', data.get('date'))
print()
print('=== METRICS ===')
for m in data.get('metrics', []):
    print(f"  {m['name']}: {m['value']} [{m['signal']}]")
print()
print('=== FRED ===')
fred = data.get('fred', {})
if isinstance(fred, dict):
    for k, v in fred.items():
        print(f"  {k}: {v}")
else:
    print(fred)
