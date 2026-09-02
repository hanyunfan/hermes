"""Generate machines.json from data files.

Delegates to sync_machines.build() to ensure the entry shape is defined in
exactly one place. This script is kept as an entry point for convenience.
"""

from sync_machines import build
import json
from pathlib import Path

if __name__ == '__main__':
    entries = build()
    with open(Path(__file__).parent / 'machines.json', 'w') as f:
        json.dump(entries, f, indent=2)
    print(f'Generated machines.json with {len(entries)} machines')
