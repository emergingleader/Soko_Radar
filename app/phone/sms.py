"""The alert SMS for one county, in the subscriber's language. One SMS (160 characters) at most."""
from i18n import month, t
from sokoradar_data import county_alerts

SMS_MAX = 160


def message_for(county, lang="sw"):
    """The alert SMS for a county (None when there is no jump warning next month)."""
    T = t(lang)
    rows = county_alerts(county, horizon=1)
    if not rows:
        return None
    parts = [f"{T['crops'][r['commodity']]} KES {r['forecast_price_kes']:.0f} "
             f"({r['range_low_kes']:.0f}-{r['range_high_kes']:.0f})" for r in rows]

    def build(items, more=""):
        return T["sms"].format(county=county, month=month(lang, rows[0]["target_month"]), items=", ".join(items) + more)

    msg = build(parts)
    while len(msg) > SMS_MAX and len(parts) > 1:          # keep it to one SMS
        parts.pop()
        msg = build(parts, T["sms_more"])
    return msg
