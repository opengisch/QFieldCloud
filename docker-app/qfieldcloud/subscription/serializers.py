from rest_framework import serializers

from qfieldcloud.subscription.models import CurrentSubscription


class CurrentSubscriptionSerializer(serializers.ModelSerializer):
    plan_display_name = serializers.CharField(source="plan.display_name")
    plan_code = serializers.CharField(source="plan.code")
    plan_is_premium = serializers.BooleanField(source="plan.is_premium")
    storage_used_bytes = serializers.IntegerField(source="account.storage_used_bytes")
    plan_storage_threshold_warning_bytes = serializers.IntegerField(
        source="plan.storage_threshold_warning_bytes"
    )
    plan_storage_threshold_critical_bytes = serializers.IntegerField(
        source="plan.storage_threshold_critical_bytes"
    )

    def get_storage_used_bytes(self, obj):
        return obj.account.storage_used_bytes

    class Meta:
        model = CurrentSubscription
        fields = (
            "uuid",
            "plan_display_name",
            "plan_code",
            "plan_is_premium",
            "status",
            "active_since",
            "active_until",
            # how many bytes of storage we have used
            "storage_used_bytes",
            # how many bytes of storage we have in the current subscription
            "active_storage_total_bytes",
            # remaining bytes thresholds for client-side storage warnings
            "plan_storage_threshold_warning_bytes",
            "plan_storage_threshold_critical_bytes",
        )
        read_only_fields = (
            "uuid",
            "plan_display_name",
            "plan_code",
            "plan_is_premium",
            "status",
            "active_since",
            "active_until",
            "storage_used_bytes",
            "active_storage_total_bytes",
            "plan_storage_threshold_warning_bytes",
            "plan_storage_threshold_critical_bytes",
        )
