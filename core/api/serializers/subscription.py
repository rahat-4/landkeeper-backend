from rest_framework import serializers
from django.utils import timezone
import math

from apps.organisation.models import OrganisationSubscription
from apps.subscription.models import (
    SubscriptionFeature,
    SubscriptionPlan,
    PaymentCard,
    PaymentTransaction,
)
from apps.referral.utils import get_discounted_price


class SubscriptionFeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionFeature
        fields = [
            "code",
            "name",
            "description",
        ]


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    features = SubscriptionFeatureSerializer(
        many=True,
        read_only=True,
    )
    current_plan = serializers.SerializerMethodField()
    coupon_code = serializers.SerializerMethodField()
    discounted_price = serializers.SerializerMethodField()
    discount_value = serializers.SerializerMethodField()
    discount_type = serializers.SerializerMethodField()

    class Meta:
        model = SubscriptionPlan
        fields = [
            "alias",
            "name",
            "plan_type",
            "monthly_price",
            "coupon_code",
            "discounted_price",
            "discount_value",
            "discount_type",
            "max_properties",
            "referral_discount_percent",
            "description",
            "features",
            "is_active",
            "current_plan",
        ]

    def get_discounted_price(self, obj):
        coupon = self.context.get("coupon")

        if not coupon:
            return None

        pricing = get_discounted_price(
            obj.monthly_price,
            coupon,
        )
        return str(pricing["discounted_price"])

    def get_discount_value(self, obj):
        coupon = self.context.get("coupon")

        if not coupon:
            return None

        return str(coupon.get("discount_value"))

    def get_discount_type(self, obj):
        coupon = self.context.get("coupon")

        if not coupon:
            return None

        return coupon.get("discount_type")

    def get_coupon_code(self, obj):
        coupon = self.context.get("coupon")

        if not coupon:
            return None

        return coupon.get("code")

    def get_current_plan(self, obj):
        request = self.context.get("request")

        if request and hasattr(request, "user") and request.user.is_authenticated:
            organisation = request.user.get_organisation()

            if organisation and hasattr(organisation, "subscription"):
                return organisation.subscription.plan == obj

        return False


class PaymentCardSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentCard
        fields = [
            "id",
            "alias",
            "stripe_payment_method_id",
            "last_four",
            "card_brand",
            "expiry_month",
            "expiry_year",
            "is_default",
        ]
        read_only_fields = fields


class BillingHistorySerializer(serializers.ModelSerializer):
    plan_name = serializers.SerializerMethodField()
    last_four = serializers.SerializerMethodField()
    card_brand = serializers.SerializerMethodField()

    class Meta:
        model = PaymentTransaction
        fields = [
            "alias",
            "plan_name",
            "amount",
            "currency",
            "status",
            "attempt_number",
            "last_four",
            "card_brand",
            "created_at",
            "invoice_pdf_url",
        ]
        read_only_fields = fields

    def get_plan_name(self, obj):
        return obj.plan_name_snapshot or obj.subscription.plan.name

    def get_last_four(self, obj):
        return obj.card.last_four if obj.card else None

    def get_card_brand(self, obj):
        return obj.card.card_brand if obj.card else None


class OrganisationSubscriptionStatusSerializer(serializers.ModelSerializer):
    plan = SubscriptionPlanSerializer(read_only=True)
    trial_days_left = serializers.SerializerMethodField()

    class Meta:
        model = OrganisationSubscription
        fields = [
            "alias",
            "status",
            "plan",
            "start_date",
            "end_date",
            "next_billing_date",
            "auto_renew",
            "cancelled_at",
            "trial_days_left",
        ]
        read_only_fields = [
            "status",
            "plan",
            "start_date",
            "end_date",
            "next_billing_date",
            "cancelled_at",
            "trial_days_left",
        ]

    def get_trial_days_left(self, obj):
        if (
            obj.status != OrganisationSubscription.Status.TRIALING
            or not obj.trial_end_date
        ):
            return None
        remaining = obj.trial_end_date - timezone.now()
        if remaining.total_seconds() <= 0:
            return 0
        return math.ceil(remaining.total_seconds() / 86400)


class SelectSubscriptionSerializer(serializers.Serializer):
    plan = serializers.SlugRelatedField(
        slug_field="plan_type",
        queryset=SubscriptionPlan.objects.filter(is_active=True),
    )
    payment_method_id = serializers.CharField(required=False, allow_blank=True)

    def validate_plan(self, plan):
        if not plan.is_active:
            raise serializers.ValidationError(
                "This subscription plan is not available."
            )
        return plan
