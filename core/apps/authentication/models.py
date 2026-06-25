import random
import string
from django.utils import timezone
from datetime import timedelta
from django.db import models
from django.contrib.auth.base_user import BaseUserManager, AbstractBaseUser
from django.contrib.auth.models import PermissionsMixin
from django.utils.translation import gettext_lazy as _
from common.models import CreatedAtUpdatedAtBaseModel
from .enums import NameTitleChoices, UserRoleChoices
from .utils import profile_image_upload_path


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("The Email field is required")
        email = self.normalize_email(email)
        extra_fields.setdefault("first_name", "")
        extra_fields.setdefault("last_name", "")
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("first_name", "")
        extra_fields.setdefault("last_name", "")
        extra_fields.setdefault("phone", "")

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin, CreatedAtUpdatedAtBaseModel):
    email = models.EmailField(unique=True, db_index=True)
    phone = models.CharField(
        db_index=True, max_length=24, unique=False, null=True, blank=True, default=None
    )
    title = models.CharField(
        max_length=64, choices=NameTitleChoices.choices, default=NameTitleChoices.MR
    )
    first_name = models.CharField(max_length=64)
    middle_name = models.CharField(max_length=64, blank=True)
    last_name = models.CharField(max_length=64)
    profile_image = models.ImageField(
        upload_to=profile_image_upload_path, blank=True, null=True
    )
    is_staff = models.BooleanField(
        _("staff status"),
        default=False,
        help_text=_("Designates whether the user can log into this admin site."),
    )
    is_active = models.BooleanField(
        _("active"),
        default=True,
        help_text=_("Designates whether this user should be treated as active."),
    )

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    class Meta:
        ordering = ["-created_at", "-updated_at"]

    def get_full_name(self):
        parts = [self.title, self.first_name, self.middle_name, self.last_name]
        full_name = " ".join(filter(None, parts))
        return full_name.strip().title()

    def get_organisation(self):
        organisation_user = self.organisation_users.first()
        if organisation_user:
            return organisation_user.organisation
        return None

    def __str__(self):
        name = f"{self.first_name} {self.last_name}".strip()
        return f"{name or 'User'} - {self.email}"

class EmailVerification(CreatedAtUpdatedAtBaseModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='email_verification')
    code = models.CharField(max_length=6)
    is_verified = models.BooleanField(default=False)
    expires_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.pk:
            self.expires_at = timezone.now() + timedelta(minutes=2)
        super().save(*args, **kwargs)

    def is_expired(self):
        if not self.expires_at:
            return True
        return timezone.now() > self.expires_at

    def generate_code(self):
        self.code = ''.join(random.choices(string.digits, k=6))
        self.save()

    @staticmethod
    def make_code():
        return ''.join(random.choices(string.digits, k=6))