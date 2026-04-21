import urllib.request, re

url = 'https://hanyunfan.github.io/school-calendar-portal/custody_school_calendar.html'
r = urllib.request.urlopen(url)
content = r.read().decode('utf-8', errors='replace')

idx = content.find('ESPO_INTERVALS')
esp_section = content[idx + 16:idx + 50000]
esp_end = esp_section.find('];')
esp_data = esp_section[:esp_end]

pattern = r'"start": "([\d-]+)", "end": "([\d-]+)", "custodian": "(\w+)", "reason": "(\w+)"'
matches = re.findall(pattern, esp_data)

print('April 2026 intervals in embedded JS:')
for s, e, c, rsn in matches:
    if '2026-04-' in s:
        print(f'  {s} to {e}: {c} ({rsn})')

# Now check what CSS the HTML applies
idx2 = content.find('.day.dad')
idx3 = content.find('.day.mom')
print('\nday.dad CSS at:', idx2)
print('day.mom CSS at:', idx3)
print(repr(content[idx2:idx2+50]))
print(repr(content[idx3:idx3+50]))
