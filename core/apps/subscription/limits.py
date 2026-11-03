"""Plan user-limit helpers (``SubscriptionPlan.max_users``).

``max_users`` of ``None`` means unlimited. Every ``OrganisationUser`` row
(including the landlord/owner) counts as a user. Pending invites also hold a
seat when deciding whether a new invite can be sent.
"""


class PlanUserLimitBlockedError(Exception):
    def __init__(self, current_user_count, max_users, excess):
        self.current_user_count = current_user_count
        self.max_users = max_users
        self.excess = excess
        super().__init__("Too many users for this plan.")


def get_organisation_user_count(organisation):
    return organisation.organisation_users.count()


def get_organisation_seat_count(organisation):
    """Current members plus pending invites."""
    return get_organisation_user_count(organisation) + organisation.invites.count()


def can_add_user(plan, current_count):
    if plan is None or plan.max_users is None:
        return True
    return current_count < plan.max_users


def ensure_plan_fits_users(organisation, plan):
    """Raise PlanUserLimitBlockedError if the org has more users than ``plan`` allows."""
    if plan.max_users is None:
        return

    current_count = get_organisation_user_count(organisation)
    if plan.max_users < current_count:
        raise PlanUserLimitBlockedError(
            current_user_count=current_count,
            max_users=plan.max_users,
            excess=current_count - plan.max_users,
        )
