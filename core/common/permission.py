from rest_framework.permissions import BasePermission, SAFE_METHODS
from apps.authentication.models import Permission, User
from apps.organisation.enums import OrganisationRoleChoices, OrganisationSubscriptionStatus
from apps.organisation.models import OrganisationUser
from apps.property.models import Tenant


class IsTenant(BasePermission):
    def has_permission(self, request, view):
        return isinstance(request.user, Tenant) and request.user.is_authenticated


class IsLandlord(BasePermission):
    message = "Only landlords can perform this action."

    def has_permission(self, request, view):
        if not isinstance(request.user, User):
            return False
        return OrganisationUser.objects.filter(
            user=request.user,
            role=OrganisationRoleChoices.LANDLORD,
        ).exists()


class IsAdmin(BasePermission):
    message = "Only administrators can perform this action."

    def has_permission(self, request, view):
        if not isinstance(request.user, User):
            return False
        return OrganisationUser.objects.filter(
            user=request.user,
            role=OrganisationRoleChoices.ADMIN,
        ).exists()


class IsLettingAgent(BasePermission):
    message = "Only letting agents can perform this action."

    def has_permission(self, request, view):
        if not isinstance(request.user, User):
            return False
        return OrganisationUser.objects.filter(
            user=request.user,
            role=OrganisationRoleChoices.LETTING_AGENT,
        ).exists()


class IsMortgageAdviser(BasePermission):
    message = "Only mortgage advisers can perform this action."

    def has_permission(self, request, view):
        if not isinstance(request.user, User):
            return False
        return OrganisationUser.objects.filter(
            user=request.user,
            role=OrganisationRoleChoices.MORTGAGE_ADVISER,
        ).exists()


class IsLandlordOrMortgageAdviser(BasePermission):
    message = "Only landlords or mortgage advisers can perform this action."

    def has_permission(self, request, view):
        if not isinstance(request.user, User):
            return False

        return OrganisationUser.objects.filter(
            user=request.user,
            role__in=[
                OrganisationRoleChoices.LANDLORD,
                OrganisationRoleChoices.MORTGAGE_ADVISER,
            ],
        ).exists()


class CanAccessProperty(BasePermission):
    message = "You do not have permission to access this property."

    def has_object_permission(self, request, view, obj):
        user = request.user
        organisation = user.get_organisation()

        if not organisation:
            return False

        organisation_user = OrganisationUser.objects.filter(
            user=user,
            organisation=organisation,
        ).first()

        if not organisation_user:
            return False

        # Landlord/Admin → full access
        if organisation_user.role in [
            OrganisationRoleChoices.LANDLORD,
            OrganisationRoleChoices.ADMIN,
        ]:
            return True

        # Everyone else → explicit permission required
        permission = Permission.objects.filter(
            user=user,
            organisation=organisation,
            property=obj,
        ).first()

        if not permission:
            return False

        # GET, HEAD, OPTIONS
        if request.method in SAFE_METHODS:
            return permission.can_view or permission.can_edit

        # PUT/PATCH
        if request.method in ["PUT", "PATCH"]:
            return permission.can_edit

        # DELETE → only Landlord/Admin
        if request.method == "DELETE":
            return False

        return False


class CanAccessMortgage(BasePermission):
    message = "You do not have permission to access this mortgage."

    def has_object_permission(self, request, view, obj):
        user = request.user

        organisation = user.get_organisation()

        if not organisation:
            return False

        organisation_user = OrganisationUser.objects.filter(
            user=user,
            organisation=organisation,
        ).first()

        if not organisation_user:
            return False

        # Landlord/Admin have full access
        if organisation_user.role in [
            OrganisationRoleChoices.LANDLORD,
            OrganisationRoleChoices.ADMIN,
        ]:
            return True

        # Everyone else → explicit permission required
        permission = Permission.objects.filter(
            user=user,
            organisation=organisation,
            mortgage=obj,
        ).first()

        if not permission:
            return False

        # GET, HEAD, OPTIONS
        if request.method in SAFE_METHODS:
            return permission.can_view or permission.can_edit

        # PUT/PATCH
        if request.method in ["PUT", "PATCH"]:
            return permission.can_edit

        # DELETE → only Landlord/Admin
        if request.method == "DELETE":
            return False

        return False


class HasActiveSubscription(BasePermission):
    message = "Your subscription payment failed. Please update your payment method to continue."

    def has_permission(self, request, view):
        organisation = request.user.get_organisation()
        subscription = getattr(organisation, "subscription", None)
        if not subscription:
            return False
        return subscription.status in (
            OrganisationSubscriptionStatus.ACTIVE,
            OrganisationSubscriptionStatus.TRIALING,
        )