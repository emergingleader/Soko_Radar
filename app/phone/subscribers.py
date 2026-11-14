"""In the dashboard the USSD menu is a preview: sign-ups are kept in memory for the visit only and no phone number is
stored. The live USSD service keeps its subscriber list on its own server, never in GitHub."""
from datetime import date

_rows = []
FIELDS = ["phone", "county", "lang", "joined"]


def load():
    return list(_rows)


def add(phone, county, lang="sw"):
    remove(phone)
    _rows.append({"phone": phone, "county": county, "lang": lang, "joined": date.today().isoformat()})


def remove(phone):
    before = len(_rows)
    _rows[:] = [r for r in _rows if r["phone"] != phone]
    return before - len(_rows)
