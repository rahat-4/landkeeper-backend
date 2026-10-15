import random
import re
from decimal import Decimal

from rest_framework import status
from rest_framework.response import Response

from .affonso import AffonsoAPI
from .enums import ReferralStatus
from .models import Referral


class InvalidCouponError(Exception):
    pass


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


def validate_coupon_code(coupon_code, user):
    """
    Validate an affiliate coupon against Affonso and return the Affonso
    coupon data. The discount itself is applied in our own Stripe account.
    """
    code = (coupon_code or "").strip().upper()

    if not code:
        raise InvalidCouponError("Invalid coupon code.")

    coupon = AffonsoAPI().get_coupon_by_code(code)

    if not coupon:
        raise InvalidCouponError("Invalid coupon code.")

    affiliate = coupon.get("affiliate") or {}
    own_referral = Referral.objects.filter(user=user).first()

    if (affiliate.get("email") or "").lower() == user.email.lower() or (
        own_referral and own_referral.affiliate_id == coupon.get("affiliate_id")
    ):
        raise InvalidCouponError("You cannot use your own coupon code.")

    # Respect affiliates suspended on our side
    referral = Referral.objects.filter(affiliate_id=coupon.get("affiliate_id")).first()
    if referral and referral.status != ReferralStatus.ACTIVE:
        raise InvalidCouponError("This coupon code is no longer active.")

    if coupon.get("discount_type") not in ("percentage", "fixed"):
        raise InvalidCouponError("This coupon code is no longer active.")

    return coupon


def get_discounted_price(price, coupon):
    """Apply an Affonso coupon discount to a plan price."""
    price = Decimal(price)
    value = Decimal(str(coupon.get("discount_value") or 0))

    if coupon.get("discount_type") == "percentage":
        discount = price * value / Decimal("100")
    else:
        discount = value

    discount = min(discount, price).quantize(Decimal("0.01"))

    return {
        "discount_amount": discount,
        "discounted_price": (price - discount).quantize(Decimal("0.01")),
    }


def validate_coupon(coupon_code, user):
    """Return (affonso_coupon, error_response)."""

    try:
        return validate_coupon_code(coupon_code, user), None
    except InvalidCouponError as exc:
        return None, Response(
            {"detail": str(exc)},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Exception as exc:
        return None, Response(
            {"detail": "Could not validate coupon code. Please try again."},
            status=status.HTTP_502_BAD_GATEWAY,
        )
