import random
import re

from .models import Referral


def get_coupon_code(user):
    """
    Generate a unique coupon code using up to three alphanumeric
    characters from the user's first name and a random 6-digit number.
    """
    prefix = re.sub(r"[^A-Z0-9]", "", user.first_name.upper())[:3]
    prefix = prefix.ljust(3, "X")

    while True:
        coupon_code = f"{prefix}-{random.randint(100000, 999999)}"

        if not Referral.objects.filter(coupon_code=coupon_code).exists():
            return coupon_code
