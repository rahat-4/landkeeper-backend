from django.dispatch import receiver
from allauth.account.signals import user_signed_up
from apps.organisation.enums import OrganisationRoleChoices
from apps.organisation.models import OrganisationUser, Organisation


def create_default_organisation(user):
    """Creates a default org for a user if they don't have one."""
    if OrganisationUser.objects.filter(user=user).exists():
        return

    base_name = (
        f"{user.first_name} {user.last_name}".strip()
        or user.email.split("@")[0]
    )
    org_name = f"{base_name}'s Organisation"

    # AutoSlugField handles slug automatically from name
    organisation = Organisation.objects.create(name=org_name)

    OrganisationUser.objects.create(
        user=user,
        organisation=organisation,
        role=OrganisationRoleChoices.LANDLORD,
    )


@receiver(user_signed_up)
def handle_user_signed_up(request, user, **kwargs):
    """Fires for both regular signup AND social signup."""
    create_default_organisation(user)