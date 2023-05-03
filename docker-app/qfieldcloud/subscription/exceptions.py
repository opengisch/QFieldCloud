from rest_framework import status
from core.exceptions import QFieldCloudException

class SubscriptionException(Exception):
    ...


class NotPremiumPlanException(QFieldCloudException):
    """Raised when TODO ..."""

    # TODO code = ""
    # message = ""
    status_code = status.HTTP_403_FORBIDDEN


# TODO Rather put here? (from core.exceptions)
# class SubscriptionInactiveError(QFieldCloudException):
# 
# class ReachedMaxOrganizationMembersError(QFieldCloudException):
# 
# class QuotaError(QFieldCloudException):