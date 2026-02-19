# Technician Portal App

## Overview
The Technician Portal is a Django web application that provides RSWR Systems repair technicians with a comprehensive interface for managing windshield repair operations. The portal streamlines the entire repair workflow from customer request intake through completion, enabling technicians to efficiently process repairs, document their work, and maintain repair history.

## Key Features

### User Management & Authentication
- **Technician Registration**: Administrative creation of technician accounts
- **Profile Management**: Store and update technician contact info and expertise
- **Certification Tracking**: Record technician skill levels and certifications
- **Role-Based Access**: Different capabilities for technicians vs. administrators

### Repair Queue Management
- **Dashboard View**: Central hub showing pending work and system status
- **Repair Queue**: View all assigned and available repairs in filterable list
- **Status Updates**: Move repairs through the workflow with status tracking
- **Filter System**: Sort repairs by status, customer, or other attributes
- **Customer Requested Repairs**:  **Enhanced** - All REQUESTED repairs visible to all technicians
- **Load-Balanced Assignment**:  **New** - Intelligent assignment based on technician workload
- **Assignment Indicators**: Visual cues showing which repairs are assigned to current technician

### Technical Documentation
- **Repair Details**: Comprehensive data collection for each repair
- **Damage Assessment**: Detailed recording of damage type and severity
- **Technical Parameters**: Track repair-specific data including:
  - Windshield temperature during repair
  - Whether drilling was performed
  - Resin viscosity used
  - Repair techniques applied
- **Photo Documentation**: Upload capabilities for repair photos (planned)

### Reporting & Analytics
- **Status Reports**: Current workload and completion statistics
- **Performance Metrics**: Track technician efficiency and quality
- **Customer History**: View repair trends by customer
- **Unit Tracking**: Monitor unit/vehicle repair frequency

## System Architecture

### Data Models

#### Technician
Extends the Django User model with technician-specific information:
```python
class Technician(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    phone_number = models.CharField(max_length=15, blank=True)
    expertise = models.CharField(max_length=100, blank=True)
```

#### Repair
Central model tracking all windshield repair operations:
```python
class Repair(models.Model):
    QUEUE_CHOICES = [
        ('REQUESTED', 'Customer Requested'),
        ('PENDING', 'Approval Pending'),
        ('APPROVED', 'Approved'),
        ('IN_PROGRESS', 'In Progress'),
        ('COMPLETED', 'Completed'),
        ('DENIED', 'Denied by Customer'),
    ]

    technician = models.ForeignKey(Technician, on_delete=models.CASCADE)
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True)
    unit_number = models.CharField(max_length=50)
    repair_date = models.DateTimeField(default=timezone.now)
    description = models.TextField(blank=True, null=True)
    cost = models.DecimalField(max_digits=10, decimal_places=2, default=0, editable=False)
    queue_status = models.CharField(max_length=20, choices=QUEUE_CHOICES, default='PENDING')
    damage_type = models.CharField(max_length=100)
    drilled_before_repair = models.BooleanField(default=False)
    windshield_temperature = models.FloatField(null=True, blank=True)
    resin_viscosity = models.CharField(max_length=50, blank=True)
```

#### UnitRepairCount
Tracks repair frequency for each customer unit:
```python
class UnitRepairCount(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    unit_number = models.CharField(max_length=50)
    repair_count = models.IntegerField(default=0)

    class Meta:
        unique_together = ['customer', 'unit_number']
```

### Key Views

#### Dashboard
`technician_dashboard` provides:
- Overview of current work status
- Customer-requested repairs needing attention
- Quick access to common actions

#### Repair Management
- `repair_list`: Comprehensive list of repairs with filtering options
- `repair_detail`: Detailed view of a specific repair with status controls
- `create_repair`: Form for creating new repair records
- `update_repair`: Interface for modifying repair details
- `update_queue_status`: Handles repair workflow status transitions

#### Customer Management
- `customer_details`: Shows all repairs for a specific customer
- `unit_details`: Displays repair history for a specific unit/vehicle
- `mark_unit_replaced`: Resets repair count when a unit is replaced

#### Special Administrative Features
- `create_customer`: Admin capability to create new customer records
- Additional repair management functions for administrators

### Template Structure
The portal's interface is built around these key templates:

- **dashboard.html**: Main technician dashboard
- **repair_list.html**: Filterable list of all repairs
- **repair_detail.html**: Detailed individual repair information
- **repair_form.html**: Form for creating/editing repairs
- **customer_details.html**: Customer-specific repair history
- **unit_details.html**: Unit-specific repair record
- **customer_form.html**: Form for creating/editing customers

### Workflow Stages
The technician portal manages repairs through six distinct stages:

1. **REQUESTED**: Initial repair request submitted by customer
2. **PENDING**: Awaiting customer approval (for technician-initiated repairs)
3. **APPROVED**: Approved by customer, ready for work
4. **IN_PROGRESS**: Currently being worked on by technician
5. **COMPLETED**: Repair successfully finished
6. **DENIED**: Repair request denied by customer

## Recent Improvements (v1.2.0)

###  Critical Repair Visibility Fix

**Issue Resolved**: Previously, technicians could only see repairs specifically assigned to them, causing customer repair requests to be invisible to most technicians.

**Solution Implemented**:
- **Enhanced Dashboard Logic** (`views.py:88-96`): All REQUESTED repairs now visible to all technicians
- **Assignment Indicators**: Added `assigned_to_me` flag to distinguish personal assignments
- **Improved Collaboration**: Technicians can now see system-wide repair queue

###  Load-Balanced Assignment

**New Feature**: Intelligent technician assignment based on current workload.

**Implementation** (`apps/customer_portal/views.py:500-514`):
```python
# Assigns to technician with least active repairs
technicians = Technician.objects.annotate(
    active_repairs=Count('repair', filter=Q(repair__queue_status__in=[
        'REQUESTED', 'PENDING', 'APPROVED', 'IN_PROGRESS'
    ]))
).order_by('active_repairs', 'id')
```

**Benefits**:
- Fair distribution of workload among technicians
- Prevents bottlenecks when specific technicians are busy
- Improved system efficiency and resource utilization

###  Testing Infrastructure

**New Testing Capabilities**:
- **Automated System Testing**: `python manage.py test_system_flow`
- **Test Data Management**: `python manage.py create_test_data`
- **End-to-End Verification**: Complete repair workflow testing

## Integration with Customer Portal

The Technician Portal integrates with the Customer Portal in several ways:

1. **Shared Repair Data**: Both portals access the same repair records but with different permissions and interfaces
2. **Approval Workflow**: Customer approvals in the Customer Portal affect repair availability in the Technician Portal
3. **Status Synchronization**: Status changes made by technicians are immediately visible to customers
4. **Unit Tracking**: The UnitRepairCount model is updated when repairs are completed
5. **Load-Balanced Assignment**:  **New** - Customer requests automatically assigned using workload balancing

## API Features (Planned)

The following API endpoints are planned or in development:

### Repair Status Update API
- **Endpoint**: `/technician/api/update-repair-status/`
- **Method**: POST
- **Parameters**: repair_id, new_status
- **Authentication**: Requires technician login
- **Purpose**: Update repair status via mobile app or external system

### Materials Tracking API
- **Endpoint**: `/technician/api/record-materials/`
- **Method**: POST
- **Parameters**: repair_id, material_data
- **Authentication**: Requires technician login
- **Purpose**: Record materials used during repairs

## Usage Workflow

### For Administrators
1. Set up technician accounts through admin interface
2. Create customer records as needed
3. Monitor repair queue and status transitions
4. View performance metrics and assign work
5. Handle special cases and manage overall system

### For Technicians
1. Log in to the technician portal
2. View dashboard for new work and alerts
3. Process customer-requested repairs
4. Create new repair records for direct requests
5. Update repair status as work progresses
6. Document technical details of each repair
7. Mark repairs as completed when finished

## Technical Dependencies
- **Django**: Web framework
- **Bootstrap**: UI components and responsive design
- **JavaScript**: Interactive elements and form validation
- **Chart.js**: Performance visualization (planned)
- **Dropzone.js**: Photo uploads (planned)