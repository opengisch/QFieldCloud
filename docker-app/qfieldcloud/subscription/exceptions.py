from rest_framework import status

from qfieldcloud.core.exceptions import QFieldCloudException


class SubscriptionException(QFieldCloudException): ...


class NotPremiumPlanException(SubscriptionException): ...


class ReachedMaxOrganizationMembersError(SubscriptionException):
    """Raised when an organization has exhausted its quota of members"""

    code = "organization_has_max_number_of_members"
    message = "Cannot add new organization members, account limit has been reached."
    status_code = status.HTTP_403_FORBIDDEN


class AccountInactiveError(SubscriptionException):
    """
    Raised when a permission (action) is denied because the useraccount is inactive.
    """

    code = "permission_denied_inactive"
    message = "Permission denied because the useraccount is inactive"
    status_code = status.HTTP_403_FORBIDDEN


class InactiveSubscriptionError(SubscriptionException):
    """
    Raised when a permission (action) is denied because the useraccount subscription is inactive.
    """

    code = "inactive_subscription"
    message = "Permission denied because the subscription is inactive"
    status_code = status.HTTP_403_FORBIDDEN


class PlanInsufficientError(SubscriptionException):
    """
    Raised when a permission (action) is denied because the useraccount plan is insufficient.
    """

    code = "permission_denied_plan_insufficient"
    message = "Permission denied because the useraccount's plan is insufficient"
    status_code = status.HTTP_403_FORBIDDEN


class QuotaError(SubscriptionException):
    """Raised when a quota limitation is hit"""

    code = "over_quota"
    message = "Quota error"
    status_code = status.HTTP_402_PAYMENT_REQUIRED
