from django.db import transaction

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from apps.referral.models import Referral
from apps.referral.affonso import AffonsoAPI
from apps.referral.utils import get_coupon_code


class JoinReferralView(APIView):
    def post(self, request, *args, **kwargs):
        user = request.user

        # Check if the user already has a referral profile
        if hasattr(user, "referral_profile"):
            return Response(
                {"detail": "User already has a referral profile."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        affonso_api = AffonsoAPI()

        try:
            with transaction.atomic():
                coupon_code = get_coupon_code(user)

                # Create affiliate in Affonso
                affiliate_data = affonso_api.create_affiliate(user)

                # Create coupon in Affonso
                affonso_api.create_coupon(
                    affiliate_id=affiliate_data["id"],
                    code=coupon_code,
                )

                # Save local referral profile
                Referral.objects.create(
                    user=user,
                    affiliate_id=affiliate_data["id"],
                    coupon_code=coupon_code,
                )

        except Exception as exc:
            error_message = str(exc)

            if (
                "DUPLICATE_ERROR" in error_message
                or "already exists in this program" in error_message
            ):
                return Response(
                    {
                        "detail": (
                            "An affiliate with your email already exists "
                            "in the referral program. Please contact support "
                            "to link your existing affiliate account."
                        ),
                        "code": "AFFILIATE_ALREADY_EXISTS",
                    },
                    status=status.HTTP_409_CONFLICT,
                )

            return Response(
                {
                    "detail": "Failed to create your referral profile.",
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {"detail": "Referral profile created successfully."},
            status=status.HTTP_201_CREATED,
        )
