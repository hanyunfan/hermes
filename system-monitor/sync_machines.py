import json, os, re
from pathlib import Path

DATA_DIR = Path(__file__).parent / 'data'
pattern = re.compile(r'^metrics_(.+)_(\d{8})\.json$')
seen = {}
files = sorted(os.listdir(DATA_DIR), reverse=True)
for fname in files:
    m = pattern.match(fname)
    if m:
        hostname, datestr = m.group(1), m.group(2)
        if hostname not in seen:
            with open(DATA_DIR / fname) as f:
                r = json.loads(f.readline())
                gpu = r.get('gpu')
                has_gpu = gpu and isinstance(gpu, list) and len(gpu) > 0 and not (isinstance(gpu[0], dict) and gpu[0].get('error'))
                seen[hostname] = {
                    'hostname': hostname,
                    'display_name': r.get('display_name'),
                    'cpu_count': r.get('cpu_count'),
                    'cpu_type': r.get('cpu_type'),
                    'gpu_type': r.get('gpu_type') or ('NVIDIA GPU' if has_gpu else None),
                    'gpu_count': r.get('gpu_count', 0) or (1 if has_gpu else 0)
                }
with open(Path(__file__).parent / 'machines.json', 'w') as f:
    json.dump(list(seen.values()), f, indent=2)
print('machines.json updated')
