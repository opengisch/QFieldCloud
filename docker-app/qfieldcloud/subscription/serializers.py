from qfieldcloud.subscription.models import CurrentSubscription
from rest_framework import serializers


class CurrentSubscriptionSerializer(serializers.ModelSerializer):
    storage_used_bytes = serializers.SerializerMethodField()
    active_plan_display_name = serializers.SerializerMethodField()

    def get_storage_used_bytes(self, obj):
        return obj.account.storage_used_bytes

    def get_active_plan_display_name(self, obj):
        return obj.plan.display_name if obj.plan else None

    class Meta:
        model = CurrentSubscription
        fields = (
            "storage_used_bytes",
            "active_storage_total_bytes",
            "active_plan_display_name",
            "active_until",
        )
        read_only_fields = (
            "storage_used_bytes",
            "active_storage_total_bytes",
            "active_plan_display_name",
            "active_until",
        )
