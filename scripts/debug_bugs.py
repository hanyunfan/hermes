import os

base = 'C:/Users/frank/.openclaw/workspace/projects/TASK-001-allergy-report/school-calendar-portal'
with open(os.path.join(base, 'output/custody_school_calendar.html'), encoding='utf-8', errors='replace') as f:
    content = f.read()

idx = content.find('2025-08-22')
print("2025-08-22 found at:", idx)
if idx >= 0:
    with open(os.path.join(base, 'scripts/aug_section.html'), 'w', encoding='utf-8', errors='replace') as f:
        f.write(content[max(0,idx-500):idx+2000])
    print("Saved section around Aug 22 to aug_section.html")