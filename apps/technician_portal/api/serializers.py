from rest_framework import serializers
from apps.technician_portal.models import Technician, Repair, Replacement
from core.models import Customer

class TechnicianSerializer(serializers.ModelSerializer):
    class Meta:
        model = Technician
        fields = ['id', 'user', 'phone_number', 'expertise'] 

class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ['id', 'name', 'email', 'phone', 'address', 'city', 'state', 'zip_code']

class RepairSerializer(serializers.ModelSerializer):
    technician = TechnicianSerializer(read_only=True)
    customer = CustomerSerializer(read_only=True)
    # Expose service_date as repair_date for API backward compatibility
    repair_date = serializers.DateTimeField(source='service_date', read_only=True)
    
    class Meta:
        model = Repair
        fields = [
            'id', 'technician', 'customer', 'unit_number', 'repair_date', 
            'description', 'cost', 'queue_status', 'damage_type', 
            'drilled_before_repair', 'windshield_temperature', 'resin_viscosity'
        ]


class ReplacementSerializer(serializers.ModelSerializer):
    technician = TechnicianSerializer(read_only=True)
    customer = CustomerSerializer(read_only=True)
    # Expose service_date as repair_date for API backward compatibility
    repair_date = serializers.DateTimeField(source='service_date', read_only=True)
    
    class Meta:
        model = Replacement
        fields = [
            'id', 'technician', 'customer', 'unit_number', 'repair_date',
            'description', 'cost', 'queue_status',
            'glass_position', 'glass_type', 'nags_number',
            'parts_cost', 'labor_cost', 'requires_adas_calibration', 'adas_calibration_cost',
            'insurance_claim', 'insurance_company', 'claim_number',
        ]
