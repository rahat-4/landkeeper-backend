import random

from .models import Referral


def get_coupon_code(user):
    """
    Generate a unique coupon code using the first three letters
    of the user's first name and a random 6-digit number.
    """
    prefix = user.first_name[:3].upper().ljust(3, "X")

    while True:
        coupon_code = f"{prefix}{random.randint(100000, 999999)}"

        if not Referral.objects.filter(coupon_code=coupon_code).exists():
            return coupon_code
