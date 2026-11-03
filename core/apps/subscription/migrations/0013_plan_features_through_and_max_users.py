from django.db import migrations, models
import django.db.models.deletion


def basic_to_starter(apps, schema_editor):
    SubscriptionPlan = apps.get_model("subscription", "SubscriptionPlan")
    if not SubscriptionPlan.objects.filter(plan_type="STARTER").exists():
        SubscriptionPlan.objects.filter(plan_type="BASIC").update(
            plan_type="STARTER", name="Starter"
        )


def starter_to_basic(apps, schema_editor):
    SubscriptionPlan = apps.get_model("subscription", "SubscriptionPlan")
    SubscriptionPlan.objects.filter(plan_type="STARTER").update(
        plan_type="BASIC", name="Basic"
    )


class Migration(migrations.Migration):

    dependencies = [
        ("subscription", "0012_remove_subscriptionplan_referral_discount_percent"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="subscriptionfeature",
            options={"ordering": ["display_order", "id"]},
        ),
        migrations.AddField(
            model_name="subscriptionfeature",
            name="display_order",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="subscriptionplan",
            name="max_users",
            field=models.PositiveIntegerField(
                blank=True,
                help_text="Maximum number of users. Leave empty for unlimited.",
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="subscriptionplan",
            name="plan_type",
            field=models.CharField(
                choices=[
                    ("STARTER", "Starter"),
                    ("STANDARD", "Standard"),
                    ("PREMIUM", "Premium"),
                ],
                max_length=20,
                null=True,
                unique=True,
            ),
        ),
        migrations.RunPython(basic_to_starter, starter_to_basic),
        # Django can't add `through` to an existing M2M, so drop and re-add it.
        # Plan/feature links are re-seeded by `add_subscription_plans`.
        migrations.RemoveField(
            model_name="subscriptionplan",
            name="features",
        ),
        migrations.CreateModel(
            name="SubscriptionPlanFeature",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("is_included", models.BooleanField(default=True)),
                (
                    "value",
                    models.CharField(
                        blank=True,
                        help_text="Display text, e.g. 'Up to 3' or 'Priority support'. "
                        "Empty means a plain included/not-included tick.",
                        max_length=150,
                    ),
                ),
                (
                    "feature",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="plan_features",
                        to="subscription.subscriptionfeature",
                    ),
                ),
                (
                    "plan",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="plan_features",
                        to="subscription.subscriptionplan",
                    ),
                ),
            ],
            options={
                "ordering": ["feature__display_order", "feature_id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("plan", "feature"), name="unique_feature_per_plan"
                    )
                ],
            },
        ),
        migrations.AddField(
            model_name="subscriptionplan",
            name="features",
            field=models.ManyToManyField(
                blank=True,
                related_name="plans",
                through="subscription.SubscriptionPlanFeature",
                to="subscription.subscriptionfeature",
            ),
        ),
    ]
