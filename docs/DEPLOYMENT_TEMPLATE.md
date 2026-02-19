# RS Systems - AWS Elastic Beanstalk Deployment Template

##  Deployment Steps

### Step 1: Verify Local Setup
```bash
cd rswr_systems/src
python manage.py check --settings=rs_systems.settings_aws_fixed
python manage.py migrate --settings=rs_systems.settings_aws_fixed
python manage.py runserver --settings=rs_systems.settings_aws_fixed
```

### Step 2: Initialize Elastic Beanstalk (if not already done)
```bash
# From the project root directory
eb init

# Select:
# - Region: [YOUR_PREFERRED_REGION]
# - Application name: rs-systems
# - Platform: Python 3.11
# - CodeCommit: No
```

### Step 3: Create Environment
```bash
eb create [YOUR_ENV_NAME]

# Or if you want to specify more options:
eb create [YOUR_ENV_NAME] --instance-type t3.small --platform-version "3.11"
```

### Step 4: Set Environment Variables
```bash
# Set a secure secret key
eb setenv SECRET_KEY="[YOUR_SECURE_SECRET_KEY]"

# If using RDS, set database credentials
eb setenv RDS_HOSTNAME="[YOUR_RDS_ENDPOINT]"
eb setenv RDS_DB_NAME="[YOUR_DB_NAME]"
eb setenv RDS_USERNAME="[YOUR_DB_USERNAME]"
eb setenv RDS_PASSWORD="[YOUR_DB_PASSWORD]"
eb setenv RDS_PORT="5432"

# Set debug to false for production
eb setenv DEBUG="False"
```

### Step 5: Deploy
```bash
eb deploy
```

### Step 6: Open Your Application
```bash
eb open
```

##  Database Setup Options

### Option A: Use SQLite (Simple, for testing)
- No additional setup required
- The app will use SQLite by default if no RDS variables are set

### Option B: Use RDS PostgreSQL (Recommended for production)
1. Create RDS instance through AWS Console or EB Console
2. Set the environment variables as shown in Step 4
3. The app will automatically use PostgreSQL when RDS variables are detected

##  Troubleshooting

### If deployment fails:
1. Check logs: `eb logs`
2. Check health: `eb health`
3. SSH into instance: `eb ssh`

### Common issues and solutions:

1. **Migration errors**: 
   ```bash
   eb ssh
   cd /var/app/current
   source /var/app/venv/*/bin/activate
   python manage.py migrate --settings=rs_systems.settings_aws_fixed
   ```

2. **Static files not loading**:
   ```bash
   eb ssh
   cd /var/app/current
   source /var/app/venv/*/bin/activate
   python manage.py collectstatic --settings=rs_systems.settings_aws_fixed --noinput
   ```

3. **Environment variables not set**:
   ```bash
   eb printenv  # Check current environment variables
   eb setenv KEY=VALUE  # Set missing variables
   ```

##  File Structure
```
rs_systems_branch2/
 application.py              #  Fixed WSGI entry point
 requirements.txt            #  Updated with all dependencies
 .ebextensions/             #  Cleaned up EB configuration
    01_packages.config     # System packages
    02_migrations.config   # Database migrations
    03_collectstatic.config # Static files
    04_env_vars.config     # Environment variables
 rswr_systems/src/
     rs_systems/
        settings_aws_fixed.py  #  Fixed Django settings
     core/
        apps.py            #  Created Django app config
     apps/
         technician_portal/
            apps.py        #  Created Django app config
         customer_portal/
            apps.py        #  Created Django app config
         [other apps]/
             apps.py        #  Created Django app configs
```

##  Success Indicators

When deployment is successful, you should see:
-  Django system check passes with no issues
-  All migrations apply successfully
-  Static files collect without errors
-  Application starts and responds to HTTP requests
-  All Django apps are properly loaded

##  Next Steps After Deployment

1. **Create a superuser**:
   ```bash
   eb ssh
   cd /var/app/current
   source /var/app/venv/*/bin/activate
   python manage.py createsuperuser --settings=rs_systems.settings_aws_fixed
   ```

2. **Test your application endpoints**
3. **Set up monitoring and logging**
4. **Configure custom domain (if needed)**
5. **Set up SSL certificate**

##  Need Help?

If you encounter any issues:
1. Check the logs: `eb logs`
2. Verify environment variables: `eb printenv`
3. Test locally first with the same settings
4. Check AWS EB console for detailed error messages

## Note

Replace all placeholders in brackets with your actual values:
- [YOUR_PREFERRED_REGION]: Your chosen AWS region
- [YOUR_ENV_NAME]: Your chosen environment name
- [YOUR_SECURE_SECRET_KEY]: Your Django secret key
- [YOUR_RDS_ENDPOINT]: Your RDS endpoint
- [YOUR_DB_NAME]: Your database name
- [YOUR_DB_USERNAME]: Your database username
- [YOUR_DB_PASSWORD]: Your database password

Your Django application is now properly configured for AWS Elastic Beanstalk deployment! 