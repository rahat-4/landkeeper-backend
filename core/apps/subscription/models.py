from django.db import models

from django.contrib.auth import get_user_model

from common.models import CreatedAtUpdatedAtBaseModel

User = get_user_model()


class SubscriptionPlan(CreatedAtUpdatedAtBaseModel):
    name = models.CharField(max_length=50)
    max_properties = models.PositiveIntegerField(default=3)
    allow_reports = models.BooleanField(default=False)
    allow_accountant_access = models.BooleanField(default=False)
    storage_limit_mb = models.PositiveIntegerField(default=100)

    def __str__(self):
        return self.name


class UserSubscription(CreatedAtUpdatedAtBaseModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.CASCADE)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.user.email} - {self.plan.name}"
