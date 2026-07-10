# Referral and Rewards System

> **Note:** written before multi-tenant isolation was added. `RewardOption` and related
> models are tenant-scoped via FK (see `apps/tenants/README.md` and CLAUDE.md's
> "Reward Integration" section) — that isn't reflected below.

## Overview

The Referral and Rewards System is a comprehensive solution for managing customer referrals and rewards within the RS Systems platform. It enables customers to refer others to the service, earn points for successful referrals, and redeem these points for various rewards, discounts, and services.

## Table of Contents

1. [System Architecture](#system-architecture)
2. [Core Components](#core-components)
3. [Database Structure](#database-structure)
4. [User Workflows](#user-workflows)
5. [Technical Implementation](#technical-implementation)
6. [Interaction with Other Systems](#interaction-with-other-systems)
7. [Security Considerations](#security-considerations)
8. [Potential Improvements](#potential-improvements)

## System Architecture

The Referral and Rewards System is built as a Django application within the larger RS Systems platform. It consists of several key components:

- **Models**: Define the database structure for referral codes, referrals, rewards, and redemptions
- **Services**: Contain business logic for referral processing, reward management, and fulfillment
- **Views**: Handle HTTP requests and responses for various user interfaces
- **URLs**: Define routing for the application's endpoints
- **Templates**: Provide the user interface for customers and technicians

The system follows a service-oriented architecture within the Django framework, with clear separation of concerns between data models, business logic, and presentation layers.

## Core Components

### 1. Referral Management

- **Referral Code Generation**: Customers can generate unique referral codes to share with others
- **Referral Tracking**: The system tracks when new customers sign up using a referral code
- **Referral Statistics**: Customers can view statistics about their referrals, including total count and points earned

### 2. Reward Management

- **Point Accumulation**: Customers earn points for successful referrals and other actions
- **Reward Options**: Various rewards are available for redemption, with different point requirements
- **Redemption Processing**: Customers can redeem points for rewards, which then go through an approval and fulfillment workflow

### 3. Fulfillment System

- **Technician Assignment**: Eligible technicians are assigned to fulfill reward redemptions
- **Notification System**: Technicians are notified of new redemptions that require their attention
- **Fulfillment Tracking**: The system tracks the status of each redemption from request to completion

## Database Structure

The system uses the following key models:

### ReferralCode
- Stores unique referral codes linked to customer users
- Fields: `code`, `customer_user`, `created_at`, `updated_at`

### Referral
- Tracks successful referrals when new customers use a referral code
- Fields: `referral_code`, `customer_user`, `created_at`

### RewardType
- Defines types of rewards and how they should be applied
- Fields: `name`, `category`, `discount_type`, `discount_value`, `description`, `is_active`
- Categories include: repair discounts, replacement discounts, free services, merchandise, gift cards, etc.
- Discount types include: percentage, fixed amount, free (100% off), or none

### Reward
- Tracks point balances for customers
- Fields: `customer_user`, `points`, `created_at`, `updated_at`

### RewardOption
- Defines available redemption options
- Fields: `name`, `description`, `points_required`, `reward_type`, `is_active`, `created_at`, `updated_at`

### RewardRedemption
- Tracks redemption requests and their fulfillment status
- Fields: `reward`, `reward_option`, `created_at`, `status`, `notes`, `processed_by`, `processed_at`, `assigned_technician`, `fulfilled_at`, `applied_to_repair`
- Status options: pending, approved, fulfilled, rejected

## User Workflows

### Customer Workflow

1. **Referral Generation**:
   - Customer logs into their account
   - Navigates to the referrals section
   - Generates a unique referral code
   - Shares the code with friends, family, or colleagues

2. **Earning Points**:
   - New customers sign up using the referral code
   - When a new customer uses the code, both the referrer and the new customer receive points
   - Referrer receives 500 points per successful referral
   - New customer receives 100 points as a welcome bonus

3. **Reward Redemption**:
   - Customer views available rewards based on their point balance
   - Selects a reward to redeem
   - Confirms redemption, points are deducted from their balance
   - Receives confirmation and tracking information for their redemption

4. **Redemption Tracking**:
   - Customer can view their redemption history
   - Sees status updates as their redemption moves through the fulfillment process
   - Receives notification when their redemption is fulfilled

### Technician Workflow

1. **Redemption Assignment**:
   - System assigns redemptions to technicians based on workload and availability
   - Technician receives notification of new assignment

2. **Fulfillment Process**:
   - Technician reviews the redemption details
   - Processes the reward (applies discount, provides service, etc.)
   - Marks the redemption as fulfilled
   - Adds notes about the fulfillment process if needed

3. **Reward Application**:
   - For repair-related rewards, technicians can apply the reward directly to a repair
   - The system links the redemption to the specific repair record

## Technical Implementation

### Service Classes

The system implements three main service classes to encapsulate business logic:

#### ReferralService
- Handles generation of referral codes
- Validates and processes referrals
- Tracks referral statistics

```python
class ReferralService:
    @staticmethod
    def generate_referral_code(customer_user):
        # Generate unique code
        
    @staticmethod
    def process_referral(referral_code_obj, customer_user):
        # Process referral and award points
```

#### RewardService
- Manages reward points and balances
- Handles redemption requests
- Provides available reward options based on point balance

```python
class RewardService:
    @staticmethod
    def get_reward_balance(customer_user):
        # Get current point balance
        
    @staticmethod
    def redeem_reward(customer_user, reward_option_id):
        # Process redemption and deduct points
```

#### RewardFulfillmentService
- Assigns technicians to fulfill redemptions
- Manages the redemption fulfillment process
- Handles notifications between customers and technicians

```python
class RewardFulfillmentService:
    @staticmethod
    def assign_technician(redemption):
        # Find and assign appropriate technician
        
    @staticmethod
    def mark_as_fulfilled(redemption, technician, notes=None):
        # Mark redemption as complete
```

### API Endpoints

The system provides the following key endpoints:

- `/generate-referral-code/`: Generate a new referral code
- `/referral-code/`: Get the current user's referral code
- `/referral-tracking/`: Track a successful referral
- `/referral-history/`: View referral history
- `/referral-stats/`: Get statistics about referrals
- `/referral-leaderboard/`: View top referrers
- `/reward-balance/`: Check current reward balance
- `/reward-options/`: View available reward options
- `/redeem-reward/`: Redeem points for a reward
- `/referral-rewards/`: Main dashboard for rewards system
- `/referral-rewards-history/`: View redemption history

## Interaction with Other Systems

The Referral and Rewards System interacts with the following components:

### Customer Portal
- Allows customers to access the referral and rewards dashboard
- Provides interfaces for generating codes, tracking referrals, and redeeming rewards

### Technician Portal
- Notifies technicians of new redemptions to fulfill
- Allows technicians to process and complete redemptions

### Repair System
- Enables rewards to be applied directly to repairs
- Links redemptions to specific repair records for tracking

## Security Considerations

The system implements several security measures:

1. **Authentication**: All endpoints require login authentication
2. **Authorization**: Customers can only access their own referral codes and redemptions
3. **Validation**: Referral codes are validated before processing
4. **Anti-fraud Measures**:
   - Users cannot refer themselves
   - Each referral code can only be used once per customer
   - Points are only awarded for genuine referrals

## Potential Improvements

### Short-term Improvements
1. **Enhanced Analytics**: Add more detailed analytics about referral performance
2. **Multi-channel Sharing**: Integrate social media sharing for referral codes
3. **Reward Categorization**: Implement better categorization and filtering of reward options
4. **Email Notifications**: Add email notifications for important events in the referral/reward process

### Mid-term Improvements
1. **Dynamic Point System**: Implement variable point values based on customer value or promotional periods
2. **A/B Testing Framework**: Test different referral incentives and reward structures
3. **Personalized Rewards**: Offer rewards tailored to customer preferences and history
4. **Mobile App Integration**: Deeper integration with mobile apps for better user experience

### Long-term Vision
1. **Partner Network**: Expand rewards to include partner businesses and services
2. **Tiered Reward System**: Implement levels or tiers in the rewards program to encourage loyalty
3. **Gamification Elements**: Add badges, achievements, and challenges to increase engagement
4. **AI-driven Recommendations**: Use machine learning to suggest optimal referral strategies and reward options
5. **Blockchain-based Point System**: Explore using blockchain for transparent and secure point tracking

---

*This documentation is maintained by the RS Systems development team. Last updated: 4/3/2025
