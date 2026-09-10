from rest_framework import serializers


class LandLordDashboardSerializer(serializers.Serializer):
    total_properties = serializers.IntegerField()
    total_tenants = serializers.IntegerField()
    total_rent_collected = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_pending_rent = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_maintenance_requests = serializers.IntegerField()
    total_maintenance_completed = serializers.IntegerField()
