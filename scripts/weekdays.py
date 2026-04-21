from datetime import date

print('May 2026 weekdays:')
for day in range(18, 26):
    wd = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][date(2026,5,day).weekday()]
    print(f"  May {day} = {wd}")

print('\nAug 2025 weekdays:')
for day in range(12, 32):
    wd = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][date(2025,8,day).weekday()]
    print(f"  Aug {day} = {wd}")

print('\nDec 2025 weekdays:')
for day in range(15, 26):
    wd = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][date(2025,12,day).weekday()]
    print(f"  Dec {day} = {wd}")
