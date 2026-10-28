from django.db import models
from django.utils.translation import gettext_lazy as _


class MTDQuarter(models.TextChoices):
    Q1 = "Q1", _("Quarter 1 (6 Apr - 5 Jul)")
    Q2 = "Q2", _("Quarter 2 (6 Jul - 5 Oct)")
    Q3 = "Q3", _("Quarter 3 (6 Oct - 5 Jan)")
    Q4 = "Q4", _("Quarter 4 (6 Jan - 5 Apr)")
