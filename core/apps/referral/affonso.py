import requests

from django.conf import settings


class AffonsoAPI:
    def __init__(self):
        self.base_url = settings.AFFONSO_URL
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.AFFONSO_API_KEY}",
        }

    def create_affiliate(self, user):
        """
        Create an affiliate in Affonso for the given user.
        """

        payload = {
            "email": user.email,
            "name": " ".join(
                filter(None, [user.first_name, user.middle_name, user.last_name])
            ),
            # Add any other required fields here
        }

        response = requests.post(
            f"{self.base_url}/affiliates", json=payload, headers=self.headers
        )

        if response.status_code == 201:
            return response.json().get("data", {})
        else:
            raise Exception(
                f"Failed to create affiliate: {response.status_code} - {response.text}"
            )

    def create_coupon(
        self,
        affiliate_id,
        code,
        discount_type="percentage",
        discount_value=20,
        duration="forever",
    ):
        """
        Create a coupon in Affonso for the given affiliate.
        """

        payload = {
            "affiliate_id": affiliate_id,
            "code": code,
            "discount_type": discount_type,
            "discount_value": discount_value,
            "duration": duration,
            # Add any other required fields here
        }

        response = requests.post(
            f"{self.base_url}/coupons", json=payload, headers=self.headers
        )

        if response.status_code == 201:
            return response.json().get("data", {})
        else:
            raise Exception(
                f"Failed to create coupon: {response.status_code} - {response.text}"
            )
