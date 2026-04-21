import re

base = 'C:/Users/frank/.openclaw/workspace/projects/TASK-001-allergy-report/school-calendar-portal/src'
with open(base + '/custody_calculator.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the _get_custodian method and replace it entirely
# Pattern: from "def _get_custodian" to the next method "def _no_extended_weekend"
pattern = r'(    def _get_custodian\(self, d: date\) -> tuple:.*?)(    def _no_extended_weekend\(self, d: date\) -> tuple:)'

replacement = '''    def _get_custodian(self, d: date) -> tuple:
        """
        Determine custodian for a single date.
        Priority order (per §153.314):
          1. Parents day — checked FIRST, overrides everything
          2. Last school day BEFORE a break = that break day 1
          3. School breaks (thanksgiving, christmas, spring, summer)
          4. Extended Weekend Rule: if Thu is dad's, Fri-Sat-Sun also belong to dad
          5. Regular school day Thu / 1st-3rd-5th Fri rules
          6. Fallback: managing conservator (mom)
        """
        rules = self.rules
        is_odd_year = d.year % 2 == 1

        # 1. Parents day
        fd = self._fathers_day(d.year)
        if fd:
            fri_before_fd = fd - timedelta(days=2)
            if fri_before_fd <= d <= fd:
                return rules["fathers_day"]["parent"], "fathers_day"

        md = self._mothers_day(d.year)
        if md:
            fri_before_md = md - timedelta(days=2)
            if fri_before_md <= d <= md:
                return rules["mothers_day"]["parent"], "mothers_day"

        # 2. Special: last school day BEFORE a break = that break day 1
        # Check each break; if d is the last school day before it starts, it's break day 1
        for sy in self.school_years:
            for br_name, br in sy.get("breaks", {}).items():
                br_start = date.fromisoformat(br["start"])
                # Walk backward from br_start-1 to find last school day
                prev = br_start - timedelta(days=1)
                for _ in range(90):
                    if prev.weekday() < 5:  # Mon-Fri
                        noschool = {date.fromisoformat(n["date"]) for n in sy.get("noschool_days", [])}
                        if prev in noschool:
                            prev -= timedelta(days=1)
                            continue
                        # Not in another break?
                        in_other = any(
                            date.fromisoformat(b2["start"]) <= prev <= date.fromisoformat(b2["end"])
                            for n2, b2 in sy.get("breaks", {}).items()
                            if n2 != br_name
                        )
                        if not in_other:
                            break
                        prev -= timedelta(days=1)
                    else:
                        prev -= timedelta(days=1)
                else:
                    prev = br_start - timedelta(days=1)

                if d == prev:
                    # d is the last school day before this break — it's break day 1
                    br_data = {"start": br["start"], "end": br["end"], "label": br.get("label", {})}
                    return self._break_custodian(br_name, br_data, d, is_odd_year)

        # 3. School breaks (normal case)
        break_name, break_data = self._in_which_break(d)
        if break_name:
            return self._break_custodian(break_name, break_data, d, is_odd_year)

        # 4. Extended Weekend Rule (per §153.314(e))
        # If Thu is dad's, Fri-Sat-Sun form one continuous weekend belonging to dad
        if d.weekday() == 4:  # Friday
            thu = d - timedelta(days=1)
            thu_custodian, _ = self._no_extended_weekend(thu)
            if thu_custodian == "dad":
                return "dad", "weekend"

        if d.weekday() in (5, 6):  # Saturday or Sunday
            fri = d - timedelta(days=d.weekday() - 4)  # preceding Friday
            thu = fri - timedelta(days=1)
            thu_custodian, _ = self._no_extended_weekend(thu)
            if thu_custodian == "dad":
                return "dad", "weekend"

        # 5. Regular school day rules: Thursday + 1st-3rd-5th Friday
        if d.weekday() == 3:  # Thursday
            return rules["thursday"]["parent"], "thursday"

        if d.weekday() == 4:  # Friday
            fridays = sorted(self._all_fridays(d.year, d.month))
            if d in fridays:
                fri_rank = fridays.index(d) + 1
                if fri_rank in [1, 3, 5]:
                    return rules["weekend"]["parent"], "weekend"

        # 6. Fallback: managing conservator (mom)
        return rules["parents"]["managing"], "default_custody"

    def _no_extended_weekend(self, d: date) -> tuple:
        """
        Internal custodian check that does NOT apply the extended weekend rule.
        Used only by the extended weekend check to avoid infinite recursion.
        """
        rules = self.rules
        is_odd_year = d.year % 2 == 1
        fd = self._fathers_day(d.year)
        if fd:
            fri_before_fd = fd - timedelta(days=2)
            if fri_before_fd <= d <= fd:
                return rules["fathers_day"]["parent"], "fathers_day"
        md = self._mothers_day(d.year)
        if md:
            fri_before_md = md - timedelta(days=2)
            if fri_before_md <= d <= md:
                return rules["mothers_day"]["parent"], "mothers_day"
        break_name, break_data = self._in_which_break(d)
        if break_name:
            return self._break_custodian(break_name, break_data, d, is_odd_year)
        if d.weekday() == 3:
            return rules["thursday"]["parent"], "thursday"
        if d.weekday() == 4:
            fridays = sorted(self._all_fridays(d.year, d.month))
            if d in fridays:
                fri_rank = fridays.index(d) + 1
                if fri_rank in [1, 3, 5]:
                    return rules["weekend"]["parent"], "weekend"
        return rules["parents"]["managing"], "default_custody"
'''

match = re.search(pattern, content, re.DOTALL)
if match:
    new_content = content[:match.start()] + replacement + content[match.end():]
    with open(base + '/custody_calculator.py', 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("Replacement done!")
else:
    print("Pattern not found!")