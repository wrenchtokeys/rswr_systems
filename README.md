# RS Systems - Windshield Repair Management Platform

A comprehensive Django-based windshield repair management system that streamlines operations for repair technicians and provides an intuitive customer portal for service tracking and rewards management.

## 🎯 Overview

RS Systems is a full-stack web application designed to modernize windshield repair operations through digital workflow management. The platform connects technicians, customers, and administrative staff through specialized portals that handle everything from repair requests to customer rewards and referral programs.

### Key Benefits

- **Streamlined Operations**: Digital repair workflow with queue management and status tracking
- **Customer Engagement**: Self-service portal with real-time repair tracking and approvals
- **Revenue Growth**: Integrated referral system with rewards program to drive customer retention
- **Cost Efficiency**: Automated pricing based on repair frequency with built-in discount application
- **Data Insights**: Comprehensive analytics and visualizations for business intelligence

## 🔐 Security Notice

**This is production-ready code with sanitized credentials.** All sensitive information (AWS account IDs, database endpoints, API keys, passwords) has been removed or replaced with placeholders for public distribution.

- ✅ **Safe to use**: All application code, architecture, and logic are production-ready
- ✅ **Credentials removed**: No real passwords, API keys, or infrastructure details exposed
- ⚠️ **Configure first**: Copy `.env.example` to `.env` and add your own credentials before deploying
- 📖 **Read SECURITY.md**: See [SECURITY.md](SECURITY.md) for complete security documentation

**Never commit `.env` files or real credentials to version control.**

## 🏗️ System Architecture

### Core Applications

The system is built with a modular architecture featuring three main applications:

#### 1. **Technician Portal** (`apps/technician_portal/`)
- Repair workflow management with queue-based status tracking
- Customer and unit management with repair history
- Cost calculation based on repair frequency
- Reward fulfillment and discount application
- Real-time notifications for pending tasks

#### 2. **Customer Portal** (`apps/customer_portal/`)
- Self-service repair request submission
- Real-time repair status tracking and approvals
- Interactive data visualizations using D3.js
- Account management and preferences
- Repair history and documentation access

#### 3. **Rewards & Referrals** (`apps/rewards_referrals/`)
- Referral code generation and tracking
- Point-based reward system with automatic earning
- Flexible redemption options with discount types
- Automated reward application to repairs
- Comprehensive redemption management

### Supporting Infrastructure

- **Security Module**: Comprehensive security with bot protection, rate limiting, and audit logging
- **Photo Storage**: Repair documentation and image management
- **Queue Management**: Advanced repair workflow orchestration
- **Scheduling**: Appointment and maintenance scheduling

## 🚀 Features

### For Technicians
- **Digital Repair Queue**: Manage repairs through status-based workflow (Requested → Pending → Approved → In Progress → Completed)
- **Smart Pricing**: Automatic cost calculation based on unit repair frequency ($50 first repair, decreasing to $25 for 5+ repairs)
- **Photo Documentation**: View customer-submitted damage photos and add completion photos
- **Customer Management**: Complete customer profiles with repair history and contact information
- **Reward Integration**: Apply customer rewards and discounts directly to repairs
- **Real-time Notifications**: Stay informed about pending redemptions and approvals

### For Customers
- **Self-Service Portal**: Submit repair requests and track status in real-time
- **Photo Upload**: Attach damage photos when submitting repair requests (mobile camera support)
- **Approval Workflow**: Review and approve/deny repair estimates with detailed information
- **Visual Analytics**: Interactive charts showing repair patterns and costs
- **Referral Program**: Generate unique referral codes and earn 500 points per successful referral
- **Reward Redemption**: Browse and redeem points for discounts, free services, and merchandise

### For Administrators
- **User Management**: Control access and permissions for technicians and customers
- **Reward Configuration**: Set up reward types, options, and redemption rules
- **System Analytics**: Monitor performance, costs, and customer engagement
- **Flexible Pricing**: Configure repair costs and discount structures

## 🛠️ Technology Stack

### Backend
- **Django 5.1.2**: Web framework with ORM and admin interface
- **Django REST Framework 3.15.2**: API development and documentation
- **Pillow 11.3.0**: Image processing and validation for photo uploads
- **PostgreSQL**: Production database with robust data integrity
- **SQLite**: Development database for local testing

### Frontend
- **Bootstrap**: Responsive UI framework
- **D3.js v7**: Advanced data visualization library
- **Font Awesome**: Comprehensive icon library
- **Custom CSS**: Component-based styling approach

### Infrastructure
- **Gunicorn**: Production WSGI server
- **WhiteNoise**: Static file serving
- **AWS S3**: Production file storage and media management
- **Local Media Storage**: Development photo storage
- **Railway/AWS**: Cloud deployment platforms

### Development Tools
- **Python 3.x**: Primary programming language
- **pip**: Package management
- **Django Management Commands**: Custom database setup and user management

## ⚡ Quick Start

### Prerequisites
- Python 3.8+
- pip package manager
- Git
- Virtual environment support

### Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd rs_systems_branch2
   ```

2. **Set up virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**
   ```bash
   # Create .env file with required variables
   SECRET_KEY=your-secret-key
   DEBUG=True
   ADMIN_PASSWORD=secure-admin-password
   ```

5. **Initialize database and create test data**
   ```bash
   python manage.py setup_db
   python manage.py setup_groups
   python manage.py create_test_data
   ```

6. **Verify installation**
   ```bash
   python manage.py test_system_flow --verbose
   ```

7. **Start development server**
   ```bash
   python manage.py runserver
   ```

8. **Access the application**
   - **Customer Portal**: http://localhost:8000/app/login/ (`democustomer` / `demo123`)
   - **Technician Portal**: http://localhost:8000/tech/login/ (`tech1` / `demo123`)
   - **Admin Interface**: http://localhost:8000/admin/ (`demoadmin` / `demo123`)
   - **API Documentation**: http://localhost:8000/api/schema/swagger-ui/

## 📋 Usage Guide

### Default Users
The system creates default test users for immediate access:

- **Admin**: `admin` / `[ADMIN_PASSWORD]` - Full system access
- **Tech Manager**: `johndoe` / `[secure password]` - Technician management
- **Technician**: `jdoe` / `[secure password]` - Repair operations

### Customer Registration
Customers can register through the customer portal with optional referral codes to automatically earn welcome points and referral bonuses.

### Repair Workflow
1. **Customer Request**: Submit repair request with unit and damage details
2. **Technician Review**: Assess request and provide cost estimate
3. **Customer Approval**: Review and approve/deny repair estimate
4. **Work Performance**: Technician completes repair work
5. **Completion**: Automatic cost calculation and reward application

### Reward System
- **Earning Points**: 500 points per successful referral, 100 welcome points
- **Redemption Options**: Percentage discounts, fixed amounts, free services
- **Automatic Application**: Rewards applied to repairs when completed

## 🧪 Testing

The system includes comprehensive testing infrastructure to ensure reliability and functionality.

### Quick Testing
```bash
# Run automated end-to-end test
python manage.py test_system_flow --verbose

# Create fresh test data
python manage.py create_test_data --clean

# Run unit tests
python manage.py test
```

### Manual Testing Workflow
1. **Test Customer Repair Request**:
   - Login: http://localhost:8000/app/login/ (`democustomer` / `demo123`)
   - Submit repair request for unit "TEST001"
   - Verify success message and dashboard update

2. **Test Technician Assignment**:
   - Login: http://localhost:8000/tech/login/ (`tech1` / `demo123`)
   - Verify repair appears in "Customer Requested Repairs"
   - Test with multiple technicians to verify visibility

3. **Test Repair Progression**:
   - Accept repair and progress through: Approved → In Progress → Completed
   - Verify cost calculation ($50 for first repair)

For detailed testing procedures, see [`docs/TESTING.md`](docs/TESTING.md).

## 🛡️ Security Features

RS Systems includes enterprise-grade security features designed to protect against common threats:

### Authentication & Access Control
- **Rate Limiting**: Login attempts limited to 10/hour per IP, registration to 5/hour per IP
- **Portal Separation**: Customer and technician portals with enforced access boundaries
- **Password Requirements**: Minimum 8 characters with validation
- **Session Security**: Secure cookies with proper expiration and SameSite policies

### Bot Protection
- **Username Validation**: Automatically blocks bot-like patterns (e.g., random strings like 'ygzwnplsgv')
- **Honeypot Fields**: Hidden form fields to catch automated registrations
- **Pattern Detection**: Identifies and blocks suspicious registration patterns
- **CSRF Protection**: All forms protected with Django's CSRF middleware

### Infrastructure Security
- **Security Headers**: HSTS, XSS protection, content type validation
- **Health Check Security**: Dedicated middleware for AWS ELB health checks
- **Host Validation**: Proper ALLOWED_HOSTS configuration without wildcards
- **SSL/TLS**: Production deployment enforces HTTPS with security headers

### Monitoring & Audit
- **Login Attempt Tracking**: All authentication attempts logged with IP and user agent
- **Security Audit Logs**: Comprehensive logging of security events
- **Suspicious Activity Detection**: Automatic identification of attack patterns
- **Management Commands**: Built-in tools for security investigation and response

### Security Management
```bash
# Run security audit
python manage.py security_audit

# Check specific user
python manage.py security_audit --check-user suspicious_username

# Remove suspicious users
python manage.py security_audit --delete-suspicious
```

For detailed security information, see:
- `SECURITY_ROADMAP.md` - Long-term security scaling plan
- `SECURITY_QUICK_REFERENCE.md` - Emergency response procedures

## 🔧 Development

### Database Management
```bash
# Create new migrations
python manage.py makemigrations

# Apply migrations
python manage.py migrate
```

### Admin User Management

#### Creating a Superuser

**For Production Deployment (AWS/Railway):**

**Initial Setup (First Time Only):**
1. Set superuser environment variables:
   ```bash
   # AWS Elastic Beanstalk - Initial superuser creation
   eb setenv DJANGO_ADMIN_USERNAME=admin \
            DJANGO_ADMIN_EMAIL=admin@example.com \
            DJANGO_ADMIN_PASSWORD=admin123 \
            CREATE_SUPERUSER=true
   
   eb deploy
   
   # After successful deployment, disable automatic creation
   eb setenv CREATE_SUPERUSER=false
   ```

   ```bash
   # Railway (set in dashboard or via CLI)
   railway variables set DJANGO_ADMIN_USERNAME=admin
   railway variables set DJANGO_ADMIN_EMAIL=admin@example.com  
   railway variables set DJANGO_ADMIN_PASSWORD=admin123
   railway variables set CREATE_SUPERUSER=true
   
   # Deploy, then disable
   railway variables set CREATE_SUPERUSER=false
   ```

**Regular Deployments (After Initial Setup):**
- Keep `CREATE_SUPERUSER=false` to prevent creating superusers on every deployment
- Only set `CREATE_SUPERUSER=true` when you specifically need to create a new superuser

**For Local Development:**
```bash
# Interactive superuser creation
python manage.py createsuperuser

# Or use the custom command with environment variables
export DJANGO_ADMIN_USERNAME=admin
export DJANGO_ADMIN_EMAIL=admin@localhost
export DJANGO_ADMIN_PASSWORD=admin123
python manage.py createsu
```

#### Important Notes:
- **Security**: Use strong, unique passwords for production
- **One-time Creation**: Superusers are only created if they don't already exist
- **Environment Variables**: The `createsu` command respects these variables:
  - `DJANGO_ADMIN_USERNAME` (default: 'admin')
  - `DJANGO_ADMIN_EMAIL` (default: 'admin@example.com') 
  - `DJANGO_ADMIN_PASSWORD` (default: 'admin123')
- **No Duplicates**: Re-deploying will not create duplicate superusers

### Testing
```bash
# Run all tests
python manage.py test

# Test specific app
python manage.py test apps.technician_portal

# System verification
python manage.py test_system_flow
```

### Static Files
```bash
# Collect static files for production
python manage.py collectstatic
```

## 🌐 API Documentation

The system provides comprehensive REST API documentation:

- **Interactive Documentation**: `/api/schema/swagger-ui/`
- **OpenAPI Schema**: `/api/schema/`
- **ReDoc Documentation**: `/api/schema/redoc/`

### Key Endpoints
- **Repairs**: `/api/repairs/` - Repair CRUD operations
- **Customers**: `/api/customers/` - Customer management
- **Rewards**: `/referrals/api/` - Reward and referral operations
- **Analytics**: `/customer/api/` - Data visualization endpoints

## 🚀 Deployment

### Environment Configuration
The system supports multiple deployment environments with environment-specific settings:

- **Development**: `rs_systems/settings.py`
- **Production**: `rs_systems/settings_aws.py`

### Required Environment Variables
```bash
# Core Configuration
SECRET_KEY=your-secret-key
DEBUG=False
ENVIRONMENT=production
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com

# Database
DATABASE_URL=postgresql://user:password@host:port/database

# Security
USE_HTTPS=True

# User Management
ADMIN_USERNAME=admin
ADMIN_EMAIL=admin@yourdomain.com
ADMIN_PASSWORD=secure-password
```

### Deployment Platforms
- **Railway**: Automatic deployment with PostgreSQL
- **AWS**: EC2 with RDS and S3 integration
- **Docker**: Containerized deployment support

## 📊 Data Models

### Core Entities
- **Customer**: Company information and contact details
- **Technician**: User profile with expertise and contact info
- **Repair**: Central repair tracking with status workflow
- **Reward**: Point balances and redemption tracking

### Business Logic
- **Repair Frequency Pricing**: Automatic cost reduction for repeat repairs
- **Reward Integration**: Seamless point earning and redemption
- **Status Workflow**: Structured repair process management
- **Load-Balanced Assignment**: Fair distribution of repairs among technicians

## 📚 Documentation

Professional documentation organized by role and purpose in the [`/docs`](docs/) directory:

### Quick Links
- **[Documentation Index](docs/README.md)** - Complete documentation guide
- **[User Guides](docs/user-guides/)** - Admin, Technician, and Customer guides
- **[Development Docs](docs/development/)** - Workflow, Testing, Changelog
- **[Deployment](docs/deployment/)** - AWS deployment and production checklist
- **[Security](docs/security/)** - Security overview and incident response

### By Role
- **Administrators**: [Admin Guide](docs/user-guides/ADMIN_GUIDE.md) → Manage users, pricing, preferences
- **Technicians**: [Technician Guide](docs/user-guides/TECHNICIAN_GUIDE.md) → Repair workflows, manager features
- **Customers**: [Customer Guide](docs/user-guides/CUSTOMER_GUIDE.md) → Submit requests, approve repairs
- **Developers**: [Workflow Implementation](docs/development/WORKFLOW_IMPLEMENTATION.md) → Sprint tracking, implementation
- **DevOps**: [AWS Deployment](docs/deployment/AWS_DEPLOYMENT.md) → Production deployment guide

### Recent Improvements (v1.3.0)

#### 📸 Photo Upload System
- **Customer Photo Upload**: Customers can attach damage photos when submitting repair requests
- **Mobile Camera Support**: Native camera integration for mobile devices
- **AWS S3 Integration**: Scalable cloud storage for production deployments
- **Photo Validation**: File type and size validation with user-friendly error messages
- **Photo Documentation**: Before/after photo display in both customer and technician portals

#### 🔧 Enhanced User Experience
- **Form Validation**: Improved client-side validation with real-time feedback
- **Mobile Responsiveness**: Better mobile experience for forms and photo uploads
- **Code Quality**: Added comprehensive docstrings and code organization improvements
- **Configuration**: Streamlined settings with proper AWS integration

#### 🧪 Foundation Improvements  
- **Database Migration**: Proper migration for new photo fields
- **Error Handling**: Enhanced validation and error messaging
- **Development Tools**: Improved development workflow and documentation

## 🔒 Security

This project implements enterprise-grade security practices. **See [SECURITY.md](SECURITY.md) for complete security documentation.**

### Authentication & Authorization
- Django's built-in authentication system
- Token-based API authentication
- Role-based permissions with groups
- Session security with CSRF protection

### Data Protection
- Secure password handling with PBKDF2 hashing
- HTTPS enforcement in production
- Environment variable configuration (never hardcoded secrets)
- SQL injection prevention through ORM
- All sensitive data sanitized from public repository

### Reporting Security Issues
Please report security vulnerabilities responsibly. See [SECURITY.md](SECURITY.md) for details on our security policy and how to report issues.

## 📈 Analytics & Reporting

### Customer Portal Visualizations
- Repair frequency trends over time
- Cost analysis by unit and repair type
- Status distribution charts
- Customer-specific metrics

### Business Intelligence
- Technician performance tracking
- Revenue analysis with discount impact
- Customer engagement metrics
- Referral program effectiveness

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### Development Guidelines
- Follow Django best practices
- Write comprehensive tests
- Update documentation for new features
- Use environment variables for configuration
- Maintain security standards

## 📝 License

This project is proprietary software. All rights reserved.

## 📞 Support

For technical support or questions about the RS Systems platform:

- **Documentation**: Refer to the `/docs` directory for detailed guides
- **Issues**: Report bugs and feature requests through the project repository
---

*Built with Django, designed for efficiency, and optimized for growth.*