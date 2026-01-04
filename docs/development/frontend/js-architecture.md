# D3.js Visualizations Documentation

## Overview
This directory contains JavaScript files for the D3.js data visualizations used in the RS Wind Repair customer portal. These visualizations provide customers with intuitive, interactive representations of their repair data.

## Visualization Components

### 1. Repair Status Distribution (Pie Chart)
**File**: `repair_status_chart.js`

**Description**: Displays the distribution of repairs across different statuses (requested, pending, approved, in progress, completed, denied).

**Data Requirements**:
- Array of objects with `status` and `count` properties
- Example: `[{status: "REQUESTED", count: 5}, {status: "COMPLETED", count: 12}, ...]`

**Customization**:
- Color scheme: Edit the `colorScale` variable to change the colors for each status
- Size: Adjust the `width`, `height`, and `radius` variables
- Animation: Modify the transition duration in the `arc` and `path` transitions

### 2. Repairs by Unit (Bar Chart)
**File**: `unit_repair_chart.js`

**Description**: Shows the number of repairs for each unit, sorted in descending order by repair count. Limited to the top 10 units with the most repairs.

**Data Requirements**:
- Array of objects with `unit_number` and `repair_count` properties
- Example: `[{unit_number: "A123", repair_count: 8}, {unit_number: "B456", repair_count: 5}, ...]`

**Customization**:
- Color: Change the `barColor` variable
- Size: Adjust the `width`, `height`, and `margin` variables
- Limit: Modify the `.slice(0, 10)` to show more or fewer units
- Sort order: Change the sorting function to alter how units are ordered

### 3. Repair Frequency Over Time (Line Chart)
**File**: `repair_frequency_chart.js`

**Description**: Displays the number of repairs performed over time, grouped by month, to help identify trends and patterns.

**Data Requirements**:
- Array of objects with `date` (string in YYYY-MM format) and `count` (number) properties
- Example: `[{date: "2023-01", count: 3}, {date: "2023-02", count: 7}, ...]`

**Customization**:
- Color: Modify the `lineColor` variable
- Size: Adjust the `width`, `height`, and `margin` variables
- Time format: Change the `parseTime` function to use a different date format
- Line smoothing: Adjust the `.curve()` method on the line generator

## Integration

### Loading Data from API
Each visualization fetches data from its respective API endpoint:
- Status Distribution: Uses statistics passed directly from the Django view
- Repairs by Unit: Fetches from `/customer/api/unit-repair-data/`
- Repair Frequency: Fetches from `/customer/api/repair-cost-data/`

### DOM Dependencies
Visualizations expect the following HTML elements to exist:
- `#status-chart-container` for the status distribution chart
- `#unit-chart-container` for the repairs by unit chart
- `#frequency-chart-container` for the repair frequency chart

### Error Handling
Each visualization includes:
- Loading indicators that display while data is being fetched
- Error messages that appear if data cannot be loaded
- "No data available" messages for when data is empty

## Development Guidelines

### Adding a New Visualization
1. Create a new JavaScript file for your visualization
2. Include the file in `dashboard.html`
3. Add the corresponding HTML container element
4. Create a new API endpoint in `views.py` if needed
5. Update the CSS in `dashboard_visualizations.css`

### Best Practices
- Use the `DOMContentLoaded` event to ensure the DOM is fully loaded
- Include responsive design considerations using `viewBox` for SVG elements
- Provide meaningful transitions for better user experience
- Include tooltips for detailed information on hover
- Handle all possible data scenarios (empty data, errors, etc.)
- Use consistent styling with the rest of the application

### Testing Visualizations
For testing during development:
1. Check browser console for any JavaScript errors
2. Test with various data scenarios (empty, single item, many items)
3. Test responsiveness on different screen sizes
4. Verify tooltips and interactions work as expected
5. Ensure animations perform well on slower devices 