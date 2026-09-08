from django.core.management.base import BaseCommand
from apps.subscription.models import SubscriptionFeature, SubscriptionPlan
from apps.subscription.enums import PlanType

FEATURES = [
    {
        "code": "property_management",
        "name": "Property Management",
        "description": "Full property management features.",
    },
    {
        "code": "dashboard",
        "name": "Bird's-eye-view Dashboard",
        "description": "Bird's-eye-view dashboard for managing the portfolio.",
    },
    {
        "code": "tenant_management",
        "name": "Tenant Details Management",
        "description": "Manage tenant details.",
    },
    {
        "code": "property_compliance",
        "name": "Property Compliance",
        "description": "Manage property compliance requirements.",
    },
    {
        "code": "documents_templates",
        "name": "Documents & Templates",
        "description": "Access and manage documents and templates.",
    },
    {
        "code": "finance_management",
        "name": "Finance Management",
        "description": "Manage property and portfolio finances.",
    },
    {
        "code": "reports_analytics",
        "name": "Reports & Analytics",
        "description": "Access reports and analytics.",
    },
    {
        "code": "marketplace",
        "name": "Marketplace",
        "description": "Access the Landkeeper marketplace.",
    },
    {
        "code": "property_management_tools",
        "name": "Property Management Tools",
        "description": "Access property management tools.",
    },
    {
        "code": "support_ticket",
        "name": "Support Ticket System",
        "description": "Create and manage support tickets.",
    },
    {
        "code": "making_tax_digital",
        "name": "Making Tax Digital (MTD)",
        "description": "Access Making Tax Digital functionality.",
    },
    {
        "code": "property_maintenance",
        "name": "Property Maintenance Management",
        "description": "Manage property maintenance.",
    },
    {
        "code": "dedicated_account_manager",
        "name": "Dedicated Account Manager",
        "description": "Access to a dedicated account manager.",
    },
    {
        "code": "advanced_property_insights",
        "name": "Advanced Property Insights",
        "description": "Access advanced property insights.",
    },
    {
        "code": "enhanced_portfolio_management",
        "name": "Enhanced Portfolio Management & Reporting",
        "description": "Enhanced portfolio management and reporting.",
    },
]


PLANS = [
    {
        "plan_type": PlanType.BASIC,
        "name": "Basic",
        "monthly_price": "12.99",
        "max_properties": 3,
        "referral_discount_percent": "20.00",
        "feature_codes": [
            "property_management",
            "dashboard",
            "tenant_management",
            "property_compliance",
            "documents_templates",
            "finance_management",
            "reports_analytics",
            "marketplace",
            "property_management_tools",
            "support_ticket",
        ],
    },
    {
        "plan_type": PlanType.STANDARD,
        "name": "Standard",
        "monthly_price": "29.99",
        "max_properties": 15,
        "referral_discount_percent": "20.00",
        "feature_codes": [
            # Basic features
            "property_management",
            "dashboard",
            "tenant_management",
            "property_compliance",
            "documents_templates",
            "finance_management",
            "reports_analytics",
            "marketplace",
            "property_management_tools",
            "support_ticket",
            # Standard features
            "making_tax_digital",
            "property_maintenance",
        ],
    },
    {
        "plan_type": PlanType.PREMIUM,
        "name": "Premium",
        "monthly_price": "59.99",
        "max_properties": 100,
        "referral_discount_percent": "20.00",
        "feature_codes": [
            # Basic features
            "property_management",
            "dashboard",
            "tenant_management",
            "property_compliance",
            "documents_templates",
            "finance_management",
            "reports_analytics",
            "marketplace",
            "property_management_tools",
            "support_ticket",
            # Standard features
            "making_tax_digital",
            "property_maintenance",
            # Premium features
            "dedicated_account_manager",
            "advanced_property_insights",
            "enhanced_portfolio_management",
        ],
    },
]


class Command(BaseCommand):
    help = "Create/update subscription features and plans."

    def handle(self, *args, **options):
        self.stdout.write("Creating/updating subscription features...")

        features = {}

        # -----------------------------------
        # Create / Update Features
        # -----------------------------------
        for feature_data in FEATURES:
            feature, created = SubscriptionFeature.objects.update_or_create(
                code=feature_data["code"],
                defaults={
                    "name": feature_data["name"],
                    "description": feature_data["description"],
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

        # -----------------------------------
        # Create / Update Plans
        # -----------------------------------
        self.stdout.write("\nCreating/updating subscription plans...")

        created_count = 0
        updated_count = 0

        for plan_data in PLANS:
            feature_codes = plan_data.pop("feature_codes")

            plan, created = SubscriptionPlan.objects.update_or_create(
                plan_type=plan_data["plan_type"],
                defaults={
                    "name": plan_data["name"],
                    "monthly_price": plan_data["monthly_price"],
                    "max_properties": plan_data["max_properties"],
                    "referral_discount_percent": plan_data["referral_discount_percent"],
                    "is_active": True,
                },
            )

            # Assign features to plan
            plan.features.set([features[code] for code in feature_codes])

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
