from easy_thumbnails.fields import ThumbnailerImageField
import uuid
import logging
import pprint

from django.conf import settings
from django.db import models
from autoslug import AutoSlugField

logger = logging.getLogger(__name__)
USER_IP_ADDRESS = ""
User = settings.AUTH_USER_MODEL

class CreatedAtUpdatedAtBaseModel(models.Model):
    alias = models.UUIDField(
        default=uuid.uuid4, editable=False, db_index=True, unique=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_%(class)s_set",
        verbose_name="Created By",
    )
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_%(class)s_set",
        verbose_name="Updated By",
    )

    user_ip = models.GenericIPAddressField(
        null=True,
        blank=True,
        editable=False,
    )

    class Meta:
        abstract = True
        ordering = ("-created_at",)

    def _print(self):
        _pp = pprint.PrettyPrinter(indent=4)
        _pp.pprint("------------------------------------------")
        logger.info("Details of {} : ".format(self))
        _pp.pprint(vars(self))
        _pp.pprint("------------------------------------------")

    def save(self, *args, **kwargs):
        self.full_clean()
        self.user_ip = USER_IP_ADDRESS
        super().save(*args, **kwargs)


class NameSlugDescriptionBaseModel(CreatedAtUpdatedAtBaseModel):
    name = models.CharField(max_length=200, db_index=True)
    slug = AutoSlugField(
        populate_from="name", always_update=True, unique=True, allow_unicode=True
    )
    description = models.TextField(blank=True)

    class Meta:
        abstract = True
        ordering = ("name",)

    def __str__(self):
        return self.get_name()

    def get_name(self):
        return "ID: {}, Name: {}, Slug: {}".format(self.id, self.name, self.slug)


class TimestampThumbnailImageField(ThumbnailerImageField):
    def generate_filename(self, instance, filename):
        new_filename = "{}_{}".format(uuid.uuid4().hex, filename)
        filename = super(TimestampThumbnailImageField, self).generate_filename(
            instance, new_filename
        )
        return filename