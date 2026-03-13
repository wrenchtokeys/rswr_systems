# Customer Portal App

## Overview
The Customer Portal is a Django web application that provides a complete self-service interface for RS Systems clients. It enables customers to view their repair history, request new windshield repairs, manage approvals, view invoices, and visualize their repair data through interactive charts. The portal is designed to be intuitive, responsive, and information-rich for customers.

## Key Features

### User Management & Authentication
- **Customer Registration**: New customers can create accounts with email verification
- **Profile Creation**: Link user accounts to customer companies
- **Account Settings Management**: Update contact information and preferences
- **Company Information Management**: Maintain company details and addresses
- **Primary Contact Designation**: Specify primary company representatives

### Repair Management
- **Repair History**: View comprehensive list of all repairs with filterable status
- **New Repair Requests**: Submit detailed requests for windshield repairs
- **Approval Workflow**: Approve or deny pending repairs with comments
- **Repair Details**: View complete information about individual repairs
- **Status Tracking**: Monitor real-time progress of repairs through workflow stages

### Analytics & Visualization
The portal provides three interactive D3.js visualizations that give customers insights into their repair data:

1. **Repair Status Distribution** (Pie Chart):
   - Displays the breakdown of repairs by current status
   - Color-coded segments with interactive legend
   - Shows counts alongside status names

2. **Repairs by Unit** (Bar Chart):
   - Illustrates which units/vehicles have had the most repairs
   - Sorted in descending order by repair frequency
   - Shows top 10 most-repaired units for clarity

3. **Repair Frequency Over Time** (Line Chart):
   - Tracks repair volume trends month by month
   - Helps identify seasonal patterns or increasing/decreasing trends
   - Interactive tooltips show exact counts for each month

## System Architecture

### Data Models

#### CustomerUser
Links standard Django User accounts to Customer entities:
```python
class CustomerUser(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    is_primary_contact = models.BooleanField(default=False)
```

#### CustomerPreference
Stores customer portal preferences and notification settings:
```python
class CustomerPreference(models.Model):
    customer = models.OneToOneField(Customer, on_delete=models.CASCADE)
    receive_email_notifications = models.BooleanField(default=True)
    receive_sms_notifications = models.BooleanField(default=False)
    default_view = models.CharField(
        max_length=20, 
        choices=[('pending', 'Pending Repairs'), ('completed', 'Completed Repairs')],
        default='pending'
    )
```

#### RepairApproval
Tracks customer approvals/denials for repair requests:
```python
class RepairApproval(models.Model):
    repair = models.OneToOneField(Repair, on_delete=models.CASCADE)
    approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(CustomerUser, on_delete=models.SET_NULL, null=True, blank=True)
    approval_date = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
```

### Key Views

#### Dashboard
`customer_dashboard` serves as the main entry point, providing:
- Summary statistics (active repairs, completed repairs, pending approvals)
- Company information with edit controls
- Quick action links for common operations
- Interactive visualizations of repair data
- List of recent repairs and items awaiting approval

#### Repair Management
- `customer_repairs`: Lists all repairs with filtering and sorting options
- `customer_repair_detail`: Shows comprehensive information about a specific repair
- `customer_repair_approve`: Handles the approval workflow for pending repairs
- `customer_repair_deny`: Processes repair denials with required reasoning
- `request_repair`: Provides form for creating new repair requests

#### Account & Profile Management
- `customer_register`: Handles new customer registration
- `profile_creation`: Sets up new profiles for existing companies or creates new companies
- `edit_company`: Allows updating company details
- `account_settings`: Manages user account settings and preferences

#### API Endpoints
- `unit_repair_data_api`: Provides JSON data for the unit repair bar chart
- `repair_cost_data_api`: Supplies time-series data for the frequency line chart

### Template Structure
The portal is built around these key templates:

- **dashboard.html**: Main dashboard with statistics and visualizations
- **repairs.html**: Filterable list of all customer repairs
- **repair_detail.html**: Detailed individual repair information
- **repair_approve.html** & **repair_deny.html**: Approval/denial workflow interfaces
- **request_repair.html**: Form for submitting new repair requests
- **edit_company.html**: Company information management
- **account_settings.html**: User preferences and settings
- **profile_creation.html**: Profile setup wizard
- **register.html**: New user registration

### Data Visualization Implementation
Visualizations are implemented using D3.js v7 with the following pattern:
1. Fetch data from API endpoints or template context
2. Process and format data for visualization
3. Generate SVG elements with appropriate scales and axes
4. Add interactivity (tooltips, legends, transitions)
5. Implement responsive behavior for different screen sizes

The visualization styles are defined in `dashboard_visualizations.css`, ensuring consistent appearance across all charts.

## Usage Workflow

### For Administrators
1. Create customer accounts through Django admin
2. Set up company information and assign primary contacts
3. Monitor repair approvals and customer engagement
4. Review customer repair history and status

### For Customers
1. Register an account or receive login credentials from admin
2. Complete profile setup, linking to company
3. Request repairs for windshield damage as needed
4. View dashboard for overall repair status and statistics
5. Approve or deny pending repairs
6. Track repair progress through status updates
7. View historical data through visualizations

## API Documentation

The Customer Portal exposes two main API endpoints for data visualization:

### Unit Repair Data API
- **Endpoint**: `/customer/api/unit-repair-data/`
- **Method**: GET
- **Returns**: JSON array of objects with unit_number and repair_count
- **Authentication**: Requires customer user login
- **Powers**: Repairs by Unit bar chart

### Repair Frequency Data API
- **Endpoint**: `/customer/api/repair-cost-data/`
- **Method**: GET
- **Returns**: JSON array of objects with date and count (grouped by month)
- **Authentication**: Requires customer user login
- **Powers**: Repair Frequency Over Time line chart

### Invoice Portal
- **Invoice List** (`/app/invoices/`): View all invoices with status badges (Paid, Overdue, Sent, Partial)
- **Invoice Detail** (`/app/invoices/<id>/`): Line items, subtotal, discount, total, payment history
- **Pay Now**: Stripe checkout integration for online payments
- **Download PDF**: S3-hosted invoice PDFs

## Technical Dependencies
- **Django**: Core web framework
- **D3.js v7**: Data visualization library
- **Bootstrap**: UI components and responsive design
- **Font Awesome**: Icon library for interface elements
- **Django ORM**: Database access and model relationships

## Production URL

Customer portal is accessible at: `https://rssystems.io/app/`