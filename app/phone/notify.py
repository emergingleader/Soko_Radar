"""In the dashboard the USSD menu is a preview: it never sends an SMS. Real SMS go out from the live USSD service
(Africa's Talking, github.com/sirajiali-hub/sokoradar-demo), which uses the same menu code with its own notify.py."""


def enabled():
    return False


def send_later(phone, message):
    return False
