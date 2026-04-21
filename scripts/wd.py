from datetime import date
import calendar as calmod

# Test what date() does with day=28 when month=12
try:
    d = date(2025, 12, 28)
    print("date(2025, 12, 28):", d)
except Exception as e:
    print("Error:", e)

# Check if Dec 18 is in Christmas break
br_start = date(2025, 12, 18)
br_end = date(2026, 1, 2)
d = date(2025, 12, 18)
print("br_start <= d <= br_end:", br_start <= d <= br_end)

# Check the split logic
split = date(br_start.year, 12, 28)
print("split:", split)
print("is_first_half:", d <= split)

# What br_start.year is for br_start = Dec 18, 2025
print("br_start.year:", br_start.year)
print("date(br_start.year, 12, 28):", date(br_start.year, 12, 28))
