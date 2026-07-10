# Customer Portal API Documentation

> **Note:** written before multi-tenant isolation was added (see `apps/tenants/README.md`).
> Endpoints below are described as they worked pre-tenancy; verify tenant-scoping against
> current views before relying on this for security-sensitive details.

## Overview
This document describes the API endpoints powering the RSWR Systems Customer Portal's interactive data visualizations and features. These APIs provide authenticated access to repair metrics, unit data, and status information.

## Authentication Requirements
All API endpoints use Django's session-based authentication. Users must be logged in with a valid customer account to access these endpoints. Unauthorized access attempts will be redirected to the login page.

## Available API Endpoints

### Unit Repair Data API

**Endpoint**: `/customer/api/unit-repair-data/`

**Method**: GET

**Purpose**: Retrieves repair counts for each unit/vehicle associated with the logged-in customer's account. This data powers the "Repairs by Unit" bar chart visualization.

**Response Format**:
```json
[
  {
    "unit_number": "A123",
    "repair_count": 8
  },
  {
    "unit_number": "B456",
    "repair_count": 5
  }
]
```

**Status Codes**:
- 200: Success - Data returned as expected
- 302: Authentication required - Redirected to login
- 404: Customer profile not found

**Example Implementation**:
```javascript
// Fetch unit repair count data for visualization
fetch('/customer/api/unit-repair-data/')
  .then(response => response.json())
  .then(data => {
    // Process unit repair data for visualization
    createUnitRepairChart(data);
  })
  .catch(error => {
    console.error('Error fetching unit repair data:', error);
    showErrorMessage('Unable to load unit repair data');
  });
```

### Repair Frequency Data API

**Endpoint**: `/customer/api/repair-cost-data/`

**Method**: GET

**Purpose**: Retrieves repair frequency data grouped by month, showing repair volume trends over time. This powers the "Repair Frequency Over Time" line chart.

**Response Format**:
```json
[
  {
    "date": "2023-01",
    "count": 3
  },
  {
    "date": "2023-02",
    "count": 7
  }
]
```

**Status Codes**:
- 200: Success - Data returned as expected
- 302: Authentication required - Redirected to login
- 404: Customer profile not found

**Example Implementation**:
```javascript
// Fetch repair frequency data for time series chart
fetch('/customer/api/repair-cost-data/')
  .then(response => response.json())
  .then(data => {
    // Process repair frequency data for visualization
    createRepairFrequencyChart(data);
  })
  .catch(error => {
    console.error('Error fetching repair frequency data:', error);
    showErrorMessage('Unable to load repair trend data');
  });
```

### Repair Status Distribution Data

**Note**: Unlike the other APIs, this data is passed directly through the Django template context rather than being accessed through a separate API endpoint.

**Data Structure**:
```json
{
  "repair_status_counts": [
    {"status": "REQUESTED", "count": 5},
    {"status": "PENDING", "count": 3},
    {"status": "APPROVED", "count": 2},
    {"status": "IN_PROGRESS", "count": 4},
    {"status": "COMPLETED", "count": 12},
    {"status": "DENIED", "count": 1}
  ]
}
```

**Usage**: This data is accessed in the dashboard template and used directly by the JavaScript functions that generate the pie chart visualization.

## Implementation Details

### Backend Implementation

The API endpoints are implemented in `views.py` using the following pattern:

```python
@login_required
def unit_repair_data_api(request):
    try:
        # Get the customer associated with the logged-in user
        customer_user = CustomerUser.objects.get(user=request.user)
        customer = customer_user.customer
        
        # Query repair counts for this customer's units
        unit_repair_counts = UnitRepairCount.objects.filter(customer=customer)
        
        # Format data for the visualization
        data = [
            {"unit_number": unit.unit_number, "repair_count": unit.repair_count}
            for unit in unit_repair_counts
        ]
        
        # Return JSON response
        return JsonResponse(data, safe=False)
        
    except CustomerUser.DoesNotExist:
        # Handle the case where user doesn't have a customer profile
        return JsonResponse({"error": "Customer profile not found"}, status=404)
```

### URL Configuration

The API endpoints are registered in `urls.py`:

```python
from django.urls import path
from . import views

urlpatterns = [
    # ... other URL patterns ...
    path('api/unit-repair-data/', views.unit_repair_data_api, name='unit_repair_data_api'),
    path('api/repair-cost-data/', views.repair_cost_data_api, name='repair_cost_data_api'),
]
```

## Error Handling

The API implements consistent error handling for common scenarios:

1. **Authentication Errors**: The `@login_required` decorator handles unauthorized access by redirecting to the login page.

2. **Missing Customer Profile**: If a user is authenticated but doesn't have an associated customer profile, a 404 status is returned with an error message.

3. **Server Errors**: Django's standard error handling returns appropriate 500-series status codes for unexpected errors.

## Best Practices for API Usage

1. **Include Error Handling**: Always implement error handling for API calls to provide a smooth user experience even when data cannot be loaded.

2. **Show Loading States**: Display loading indicators while waiting for API responses, especially for visualizations.

3. **Implement Caching**: Consider caching API responses in the browser for frequently accessed data that doesn't change often.

4. **Handle Network Issues**: Implement retry logic or graceful degradation for network failures.

5. **Respect Rate Limits**: Avoid making excessive API calls, especially in loops or short intervals.

## Planned Future API Extensions

The following API endpoints are planned for future development:

1. **Repair Details API**: Detailed information retrieval for specific repairs.

2. **Repair Status Update API**: Allow customers to programmatically update repair statuses.

3. **Repair Request API**: Submit new repair requests via the API.

4. **Customer Profile API**: Access and update customer profile information.