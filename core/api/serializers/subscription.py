from rest_framework import serializers

from apps.organisation.models import OrganisationSubscription
from apps.subscription.models import SubscriptionFeature, SubscriptionPlan, PaymentCard, PaymentTransaction


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

    class Meta:
        model = SubscriptionPlan
        fields = [
            "alias",
             "name",
            "plan_type",
            "monthly_price",
            "max_properties",
            "referral_discount_percent",
            "description",
            "features",
            "is_active",
        ]

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
    plan_name = serializers.CharField(
        source="subscription.plan.name",
        read_only=True,
    )

    class Meta:
        model = PaymentTransaction
        fields = [
            "alias",
            "plan_name",
            "amount",
            "currency",
            "status",
            "attempt_number",
            "created_at",
            "invoice_pdf_url",
        ]
        read_only_fields = fields


class OrganisationSubscriptionStatusSerializer(serializers.ModelSerializer):
    plan = SubscriptionPlanSerializer(read_only=True)

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
        ]
        read_only_fields = [
            "status",
            "plan",
            "start_date",
            "end_date",
            "next_billing_date",
            "cancelled_at",
        ]


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