from django.core.management.base import BaseCommand
from django.db import transaction

from apps.subscription.enums import PlanType
from apps.subscription.models import (
    SubscriptionFeature,
    SubscriptionPlan,
    SubscriptionPlanFeature,
)

# Order of this list = row order of the pricing table.
FEATURES = [
    {
        "code": "dashboard",
        "name": "Birds eye view",
        "description": "Bird's-eye-view dashboard for managing the portfolio.",
    },
    {
        "code": "mortgage",
        "name": "Mortgages",
        "description": "Manage mortgage details.",
    },
    {
        "code": "tenant_management",
        "name": "Tenants",
        "description": "Manage tenant details.",
    },
    {
        "code": "property_compliance",
        "name": "Compliance Reminder",
        "description": "Reminders for property compliance requirements.",
    },
    {
        "code": "certificates_storage",
        "name": "Certificates storing",
        "description": "Store property certificates.",
    },
    {
        "code": "documents_storage",
        "name": "Documents storage",
        "description": "Store property documents.",
    },
    {
        "code": "finance_management",
        "name": "Recording income & expenses",
        "description": "Record property income and expenses.",
    },
    {
        "code": "making_tax_digital",
        "name": "MTD (Making Tax Digital)",
        "description": "Access Making Tax Digital functionality.",
    },
    {
        "code": "property_maintenance",
        "name": "Property maintenance",
        "description": "Manage property maintenance.",
    },
    {
        "code": "reports_analytics",
        "name": "Reports",
        "description": "Access reports and analytics.",
    },
    {
        "code": "marketplace",
        "name": "Market place",
        "description": "Access the Landkeeper marketplace.",
    },
    {
        "code": "property_management_tools",
        "name": "Tools",
        "description": "Access property management tools.",
    },
    {
        "code": "support_ticket",
        "name": "Support",
        "description": "Create and manage support tickets.",
    },
    {
        "code": "documents_templates",
        "name": "Documents Templates",
        "description": "Access document templates.",
    },
    {
        "code": "onboarding",
        "name": "Onboarding",
        "description": "Help getting started with Landkeeper.",
    },
    {
        "code": "dedicated_account_manager",
        "name": "Dedicated Account Manager",
        "description": "Access to a dedicated account manager.",
    },
]

# Per-plan feature values:
#   True        -> included (tick)
#   False       -> not included
#   "some text" -> included, shown with this text
PLANS = [
    {
        "plan_type": PlanType.STARTER,
        "name": "Starter",
        "monthly_price": "12.99",
        "max_properties": 3,
        "max_users": 2,
        "features": {
            "dashboard": True,
            "mortgage": "All mortgage details",
            "tenant_management": "All tenants",
            "property_compliance": True,
            "certificates_storage": True,
            "documents_storage": True,
            "finance_management": True,
            "making_tax_digital": False,
            "property_maintenance": False,
            "reports_analytics": "Limited",
            "marketplace": True,
            "property_management_tools": True,
            "support_ticket": "Basic support",
            "documents_templates": "Limited access",
            "onboarding": "Self user guide",
            "dedicated_account_manager": False,
        },
    },
    {
        "plan_type": PlanType.STANDARD,
        "name": "Standard",
        "monthly_price": "29.99",
        "max_properties": 15,
        "max_users": 4,
        "features": {
            "dashboard": True,
            "mortgage": "All mortgage details",
            "tenant_management": "All tenants",
            "property_compliance": True,
            "certificates_storage": True,
            "documents_storage": True,
            "finance_management": True,
            "making_tax_digital": True,
            "property_maintenance": True,
            "reports_analytics": "Full",
            "marketplace": True,
            "property_management_tools": True,
            "support_ticket": "Priority support",
            "documents_templates": "All documents",
            "onboarding": "Personal onboarding",
            "dedicated_account_manager": True,
        },
    },
    {
        "plan_type": PlanType.PREMIUM,
        "name": "Premium",
        "monthly_price": "59.99",
        "max_properties": 100,
        "max_users": None,  # unlimited ("More than 4")
        "features": {
            "dashboard": True,
            "mortgage": "All mortgage details",
            "tenant_management": "All tenants",
            "property_compliance": True,
            "certificates_storage": True,
            "documents_storage": True,
            "finance_management": True,
            "making_tax_digital": True,
            "property_maintenance": True,
            "reports_analytics": "Full",
            "marketplace": True,
            "property_management_tools": True,
            "support_ticket": "Priority support",
            "documents_templates": "All documents",
            "onboarding": "Personal onboarding",
            "dedicated_account_manager": True,
        },
    },
]


class Command(BaseCommand):
    help = "Create/update subscription features and plans."

    @transaction.atomic
    def handle(self, *args, **options):
        feature_codes = [f["code"] for f in FEATURES]
        for plan_data in PLANS:
            missing = set(feature_codes) - set(plan_data["features"])
            unknown = set(plan_data["features"]) - set(feature_codes)
            if missing or unknown:
                raise ValueError(
                    f"{plan_data['name']}: missing={sorted(missing)} "
                    f"unknown={sorted(unknown)}"
                )

        # -----------------------------------
        # Create / Update Features
        # -----------------------------------
        self.stdout.write("Creating/updating subscription features...")

        features = {}
        for order, feature_data in enumerate(FEATURES, start=1):
            feature, created = SubscriptionFeature.objects.update_or_create(
                code=feature_data["code"],
                defaults={
                    "name": feature_data["name"],
                    "description": feature_data.get("description", ""),
                    "display_order": order,
                    "is_active": True,
                },
            )
            features[feature.code] = feature

            if created:
                self.stdout.write(
                    self.style.SUCCESS(f"Created feature: {feature.name}")
                )
            else:
                self.stdout.write(f"Updated feature: {feature.name}")

        # Deactivate features no longer on the pricing table
        stale = SubscriptionFeature.objects.exclude(code__in=feature_codes)
        for feature in stale.filter(is_active=True):
            self.stdout.write(
                self.style.WARNING(f"Deactivated feature: {feature.name}")
            )
        stale.update(is_active=False)

        # -----------------------------------
        # Create / Update Plans
        # -----------------------------------
        self.stdout.write("\nCreating/updating subscription plans...")

        created_count = 0
        updated_count = 0

        for plan_data in PLANS:
            plan, created = SubscriptionPlan.objects.update_or_create(
                plan_type=plan_data["plan_type"],
                defaults={
                    "name": plan_data["name"],
                    "monthly_price": plan_data["monthly_price"],
                    "max_properties": plan_data["max_properties"],
                    "max_users": plan_data["max_users"],
                    "is_active": True,
                },
            )

            for code, spec in plan_data["features"].items():
                SubscriptionPlanFeature.objects.update_or_create(
                    plan=plan,
                    feature=features[code],
                    defaults={
                        "is_included": spec is not False,
                        "value": spec if isinstance(spec, str) else "",
                    },
                )

            plan.plan_features.exclude(feature__code__in=feature_codes).delete()

            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f"Created plan: {plan.name}"))
            else:
                updated_count += 1
                self.stdout.write(f"Updated plan: {plan.name}")

        # -----------------------------------
        # Summary
        # -----------------------------------
        self.stdout.write(
            self.style.SUCCESS(
                f"\nCompleted successfully."
                f"\nFeatures: {len(features)}"
                f"\nPlans created: {created_count}"
                f"\nPlans updated: {updated_count}"
            )
        )
