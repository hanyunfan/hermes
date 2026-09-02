"""Rebuild machines.json from the data/ directory.

Importable: gen_machines.py and regen_machines.py delegate to build() so the
entry shape is defined in exactly one place. Three copies of this dict is how
`latest_date` would silently disappear the next time someone ran the other
script.
"""

import json, os, re
from pathlib import Path

DATA_DIR = Path(__file__).parent / 'data'
pattern = re.compile(r'^metrics_(.+)_(\d{8})\.json$')

def first_record(path):
    """Return the first valid JSON object in the file, or None if none parse.
    Tolerates blank lines and corrupt/placeholder files (e.g. a stray
    '404: Not Found' from a failed download)."""
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        return obj
                except json.JSONDecodeError:
                    return None
    except OSError:
        return None
    return None

def build():
    """Return the machines.json list: one entry per hostname, newest file wins."""
    seen = {}
    # Reverse filename order puts the newest date for each hostname first, so
    # the first match we keep is also that machine's most recent data file.
    for fname in sorted(os.listdir(DATA_DIR), reverse=True):
        m = pattern.match(fname)
        if not m:
            continue
        hostname, datestr = m.group(1), m.group(2)
        if hostname in seen:
            continue
        r = first_record(DATA_DIR / fname)
        if r is None:
            print(f'skipping unreadable {fname}')
            continue
        gpu = r.get('gpu')
        has_gpu = gpu and isinstance(gpu, list) and len(gpu) > 0 and not (isinstance(gpu[0], dict) and gpu[0].get('error'))
        seen[hostname] = {
            'hostname': hostname,
            'display_name': r.get('display_name'),
            'cpu_count': r.get('cpu_count'),
            'cpu_type': r.get('cpu_type'),
            'gpu_type': r.get('gpu_type') or ('NVIDIA GPU' if has_gpu else None),
            'gpu_count': r.get('gpu_count', 0) or (1 if has_gpu else 0),
            # YYYYMMDD of this machine's most recent data file. Lets the
            # dashboard sort by freshness and show it in the dropdown instead
            # of probing 365 days per machine to find out.
            'latest_date': datestr,
        }
    return list(seen.values())


if __name__ == '__main__':
    entries = build()
    with open(Path(__file__).parent / 'machines.json', 'w') as f:
        json.dump(entries, f, indent=2)
    print(f'machines.json updated ({len(entries)} machines)')
