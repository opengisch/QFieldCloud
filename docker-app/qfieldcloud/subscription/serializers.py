from rest_framework import serializers

from qfieldcloud.subscription.models import CurrentSubscription


class CurrentSubscriptionSerializer(serializers.ModelSerializer):
    plan_display_name = serializers.CharField(source="plan.display_name")
    storage_used_bytes = serializers.FloatField(source="account.storage_used_bytes")

    def get_storage_used_bytes(self, obj):
        return obj.account.storage_used_bytes

    class Meta:
        model = CurrentSubscription
        fields = (
            "uuid",
            "plan_display_name",
            "status",
            "active_since",
            "active_until",
            # how many bytes of storage we have used
            "storage_used_bytes",
            # how many bytes of storage we have in the current subscription
            "active_storage_total_bytes",
        )
        read_only_fields = (
            "uuid",
            "plan_display_name",
            "status",
            "active_since",
            "active_until",
            "storage_used_bytes",
            "active_storage_total_bytes",
        )
