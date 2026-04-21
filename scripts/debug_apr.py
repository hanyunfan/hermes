import json
from datetime import date

with open('C:/Users/frank/.openclaw/workspace/projects/TASK-001-allergy-report/school-calendar-portal/data/processed/espo_intervals.json') as f:
    data = json.load(f)

intervals = data['intervals']
print(f'Total intervals: {len(intervals)}')

# Show intervals around Apr 10-15
print('\nIntervals around Apr 9-16:')
for iv in intervals:
    start = date.fromisoformat(iv['start'][:10])
    end = date.fromisoformat(iv['end'][:10])
    if start.year == 2026 and start.month == 4 and 8 <= start.day <= 17:
        print(f'  {iv["start"][:10]} to {iv["end"][:10]}: {iv["custodian"]} | {iv["reason"]}')

# Check if Apr 11 specifically is in any interval
target = date(2026, 4, 11)
print(f'\nLooking for Apr 11 specifically:')
for iv in intervals:
    start = date.fromisoformat(iv['start'][:10])
    end = date.fromisoformat(iv['end'][:10])
    if start <= target <= end:
        print(f'  FOUND: {iv["start"][:10]} to {iv["end"][:10]}: {iv["custodian"]} | {iv["reason"]}')

# Show first 20 intervals
print('\nFirst 20 intervals:')
for iv in intervals[:20]:
    print(f'  {iv["start"][:10]} to {iv["end"][:10]}: {iv["custodian"]} | {iv["reason"]}')
