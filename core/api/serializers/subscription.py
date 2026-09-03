from rest_framework import serializers

from apps.organisation.models import OrganisationSubscription
from apps.subscription.models import SubscriptionFeature, SubscriptionPlan


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
            "features",
        ]


class SelectSubscriptionSerializer(serializers.Serializer):
    plan = serializers.SlugRelatedField(
        slug_field="plan_type",
        queryset=SubscriptionPlan.objects.filter(is_active=True),
    )

    def validate_plan(self, plan):
        if not plan.is_active:
            raise serializers.ValidationError(
                "This subscription plan is not available."
            )

        return plan


class OrganisationSubscriptionStatusSerializer(serializers.ModelSerializer):
    plan = SubscriptionPlanSerializer(read_only=True)

    class Meta:
        model = OrganisationSubscription
        fields = [
            "status",
            "plan",
            "started_at",
            "current_period_start",
            "current_period_end",
            "cancelled_at",
        ]
