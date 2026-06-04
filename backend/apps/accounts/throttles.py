"""Custom DRF throttle classes for the accounts app."""

from rest_framework.throttling import UserRateThrottle


class TOTPVerifyThrottle(UserRateThrottle):
    """Rate-limit TOTP verification and disable attempts to 5 per minute.

    Prevents brute-force attacks against 6-digit OTP codes. A 6-digit TOTP
    has 10^6 possible values; without throttling an attacker could enumerate
    the current 30-second window trivially.
    """

    scope = "totp_verify"
    rate = "5/min"
