"""The USSD menu. Africa's Talking sends every key press so far in `text` (e.g. "3*1*9*3*1*2"),
so the menu walks those choices from the start each time: no session storage is needed.

First screen: choose the language. Then the main menu in that language.
Replies start with "CON " (show a menu and wait) or "END " (show an answer and close).
Keep every screen short: USSD screens hold about 160 to 182 characters.
"""
import notify
import subscribers
from i18n import CHOOSE_LANGUAGE, LANGUAGES, month, t
from sms import message_for
from sokoradar_data import CROPS, counties, county_alerts, outlook

PAGE = 8          # counties per screen; 9 = next page, 0 = previous page
MAX_SCREEN = 182  # characters a USSD screen can hold


def handle(text, phone=""):
    steps = [s.strip() for s in text.split("*")] if text else []
    if not steps:
        return "\n".join([f"CON {CHOOSE_LANGUAGE}"] + [f"{k}. {t(c)['name']}" for k, c in enumerate(LANGUAGES, 1)])
    s = steps[0]
    if not (s.isdigit() and 1 <= int(s) <= len(LANGUAGES)):
        return "END " + t("sw")["bad"]
    lang, rest = LANGUAGES[int(s) - 1], steps[1:]
    T = t(lang)
    if not rest:
        return "\n".join([f"CON {T['title']}"] + [f"{k}. {item}" for k, item in enumerate(T["main"], 1)])
    flows = {"1": price_flow, "2": alerts_flow, "3": subscribe_flow, "4": unsubscribe_flow}
    if rest[0] not in flows:
        return "END " + T["bad"]
    return flows[rest[0]](rest[1:], phone, lang)


# --------------------------------------------------------------------------- pickers
def pick_county(steps, lang):
    """Walk the county pages. Returns (county, remaining steps, None) once picked,
    or (None, [], screen) while still choosing, or (None, [], END screen) on a wrong key."""
    T = t(lang)
    names = counties()
    pages = (len(names) + PAGE - 1) // PAGE
    page = 0
    for i, s in enumerate(steps):
        if s == "9" and page < pages - 1:
            page += 1
        elif s == "0" and page > 0:
            page -= 1
        elif s.isdigit() and 1 <= int(s) <= PAGE and page * PAGE + int(s) <= len(names):
            return names[page * PAGE + int(s) - 1], steps[i + 1:], None
        else:
            return None, [], "END " + T["bad"]
    shown = names[page * PAGE:(page + 1) * PAGE]
    lines = [f"CON {T['pick_county']}"] + [f"{k}. {n}" for k, n in enumerate(shown, 1)]
    if page < pages - 1:
        lines.append(f"9. {T['more']}")
    if page > 0:
        lines.append(f"0. {T['back']}")
    return None, [], "\n".join(lines)


def pick_from(steps, options, title, lang):
    """A numbered menu. options: list of (value, label)."""
    if not steps:
        return None, [], "\n".join([f"CON {title}"] + [f"{k}. {lab}" for k, (_, lab) in enumerate(options, 1)])
    s = steps[0]
    if s.isdigit() and 1 <= int(s) <= len(options):
        return options[int(s) - 1][0], steps[1:], None
    return None, [], "END " + t(lang)["bad"]


# --------------------------------------------------------------------------- 1. price outlook
def price_flow(steps, phone, lang):
    T = t(lang)
    county, steps, screen = pick_county(steps, lang)
    if screen:
        return screen
    crop, steps, screen = pick_from(steps, [(c, T["crops"][c]) for c in CROPS], T["pick_crop"], lang)
    if screen:
        return screen
    ptype, steps, screen = pick_from(steps, list(T["types"].items()), T["pick_type"], lang)
    if screen:
        return screen
    screen = price_answer(county, crop, ptype, lang)
    has_data = outlook(county, crop, ptype, horizon=1) is not None
    return also_by_sms(screen, phone, lang) if has_data else screen


def price_answer(county, crop, ptype, lang):
    T = t(lang)
    r = outlook(county, crop, ptype, horizon=1)
    if r is None:
        return "END " + T["no_data"].format(crop=T["crops"][crop], county=county)
    now = f"KES {r['price_kes']:.0f}/kg" + ("" if r["price_is_real"] else f" ({T['estimate']})")
    lines = [
        f"END {T['crops'][crop]}, {county} ({T['types'][ptype].lower()})",
        f"{month(lang, r['origin_month'])}: {now}",
        f"{month(lang, r['target_month'])}: KES {r['forecast_price_kes']:.0f} "
        f"({r['range_low_kes']:.0f}-{r['range_high_kes']:.0f})",
    ]
    if isinstance(r.get("phase"), str) and r["phase"]:
        lines.append(T["season"].format(phase=T["phase"].get(r["phase"], r["phase"])))
    if r["spike_alert"]:
        lines.append(T["alert"])
    if isinstance(r.get("where_to_buy_county"), str) and r["where_to_buy_county"]:
        lines.append(T["cheaper"].format(county=r["where_to_buy_county"]))
    return "\n".join(lines)


# --------------------------------------------------------------------------- 2. alerts in my county
def alerts_flow(steps, phone, lang):
    county, steps, screen = pick_county(steps, lang)
    if screen:
        return screen
    screen = alerts_answer(county, lang)
    # the SMS is the same short alert subscribers get each month (always one SMS)
    return also_by_sms(screen, phone, lang, message_for(county, lang)) if county_alerts(county, horizon=1) else screen


def alerts_answer(county, lang):
    T = t(lang)
    rows = county_alerts(county, horizon=1)
    if not rows:
        return "END " + T["no_alerts"].format(county=county)
    lines = [f"END {county}, {month(lang, rows[0]['target_month'])}", T["alerts_head"]]
    for r in rows:
        lines.append(f"- {T['crops'][r['commodity']]}: KES {r['forecast_price_kes']:.0f} "
                     f"({r['range_low_kes']:.0f}-{r['range_high_kes']:.0f})")
    return "\n".join(lines)


# --------------------------------------------------------------------------- a copy by SMS
SMS_MAX = 160     # characters in one SMS


def _fit(lines, limit, lang):
    """Drop the least important lines until the text fits: the season line first, then the cheaper-nearby line."""
    T = t(lang)
    for key in ("season", "cheaper"):
        if len("\n".join(lines)) <= limit:
            break
        start = T[key].split("{")[0]
        lines = [x for x in lines if not (start and x.startswith(start))]
    return lines


def also_by_sms(screen, phone, lang, sms=None):
    """A USSD screen disappears when the session ends, so the answer is also sent by SMS to keep.
    The screen says so only when an SMS is really on its way (SMS sending is set up and we know the phone).
    Both the screen and the SMS keep the alert lines; the season and cheaper-nearby lines go first if space is short."""
    body = screen[4:].split("\n")
    sms = sms or "\n".join(_fit(["SokoRadar"] + body, SMS_MAX, lang))
    if not (phone and notify.send_later(phone, sms)):
        return screen
    return "END " + "\n".join(_fit(body + [t(lang)["sms_copy"]], MAX_SCREEN - 4, lang))


# --------------------------------------------------------------------------- 3 and 4. SMS sign-up
def subscribe_flow(steps, phone, lang):
    T = t(lang)
    county, steps, screen = pick_county(steps, lang)
    if screen:
        return screen
    ok, steps, screen = pick_from(steps, [(True, T["yes"]), (False, T["no"])], T["consent"].format(county=county), lang)
    if screen:
        return screen
    if not ok:
        return "END " + T["not_subscribed"]
    if not phone:
        return "END " + T["no_phone"]
    subscribers.add(phone, county, lang)
    notify.send_later(phone, T["welcome"].format(county=county))      # welcome SMS, in the background
    return "END " + T["subscribed"].format(county=county)


def unsubscribe_flow(steps, phone, lang):
    T = t(lang)
    removed = subscribers.remove(phone) if phone else 0
    return "END " + (T["unsubscribed"] if removed else T["was_not"])
