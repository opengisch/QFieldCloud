from qfieldcloud.core.exceptions import QFieldCloudException
from rest_framework import status


class SubscriptionException(QFieldCloudException):
    ...


class NotPremiumPlanException(SubscriptionException):
    ...


class ReachedMaxOrganizationMembersError(QFieldCloudException):
    """Raised when an organization has exhausted its quota of members"""

    code = "organization_has_max_number_of_members"
    message = "Cannot add new organization members, account limit has been reached."
    status_code = status.HTTP_403_FORBIDDEN


class AccountInactiveError(QFieldCloudException):
    """
    Raised when a permission (action) is denied because the useraccount is inactive.
    """

    code = "permission_denied_inactive"
    message = "Permission denied because the useraccount is inactive"
    status_code = status.HTTP_403_FORBIDDEN


class InactiveSubscriptionError(QFieldCloudException):
    """
    Raised when a permission (action) is denied because the useraccount subscription is inactive.
    """

    code = "inactive_subscription"
    message = "Permission denied because the subscription is inactive"
    status_code = status.HTTP_403_FORBIDDEN


class QuotaError(QFieldCloudException):
    """Raised when a quota limitation is hit"""

    code = "over_quota"
    message = "Quota error"
    status_code = status.HTTP_402_PAYMENT_REQUIRED
