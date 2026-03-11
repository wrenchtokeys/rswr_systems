#!/usr/bin/env python3
"""
Simple load testing script for quick application health checks.
Lightweight version for regular monitoring.
"""

import requests
import time
import threading
from statistics import mean, median
from concurrent.futures import ThreadPoolExecutor, as_completed

class SimpleLoadTester:
    def __init__(self, base_url="https://rssystems.io"):
        self.base_url = base_url.rstrip('/')
        self.results = []
        
    def single_request(self, endpoint="/"):
        """Make a single request and measure response time"""
        url = f"{self.base_url}{endpoint}"
        start_time = time.time()
        
        try:
            response = requests.get(url, timeout=10)
            response_time = time.time() - start_time
            
            return {
                'url': url,
                'status_code': response.status_code,
                'response_time': response_time,
                'success': 200 <= response.status_code < 400,
                'content_length': len(response.content)
            }
        except Exception as e:
            response_time = time.time() - start_time
            return {
                'url': url,
                'status_code': 0,
                'response_time': response_time,
                'success': False,
                'error': str(e),
                'content_length': 0
            }
    
    def run_load_test(self, num_requests=100, num_threads=10):
        """Run simple load test with threading"""
        print(f"🚀 Running load test: {num_requests} requests with {num_threads} threads")
        print(f"Target: {self.base_url}")
        
        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            # Submit all requests
            futures = [executor.submit(self.single_request) for _ in range(num_requests)]
            
            # Collect results
            for future in as_completed(futures):
                result = future.result()
                self.results.append(result)
                
                # Print progress
                if len(self.results) % 10 == 0:
                    print(f"Progress: {len(self.results)}/{num_requests} requests completed")
        
        total_time = time.time() - start_time
        self.print_results(total_time)
    
    def print_results(self, total_time):
        """Print test results"""
        if not self.results:
            print("❌ No results to display")
            return
        
        successful = [r for r in self.results if r['success']]
        failed = [r for r in self.results if not r['success']]
        response_times = [r['response_time'] for r in self.results]
        
        print("\n" + "="*50)
        print("📊 LOAD TEST RESULTS")
        print("="*50)
        print(f"Total Requests:      {len(self.results)}")
        print(f"Successful:          {len(successful)} ({len(successful)/len(self.results)*100:.1f}%)")
        print(f"Failed:              {len(failed)} ({len(failed)/len(self.results)*100:.1f}%)")
        print(f"Total Time:          {total_time:.2f}s")
        print(f"Requests/Second:     {len(self.results)/total_time:.2f}")
        print(f"Average Response:    {mean(response_times):.3f}s")
        print(f"Median Response:     {median(response_times):.3f}s")
        print(f"Min Response:        {min(response_times):.3f}s")
        print(f"Max Response:        {max(response_times):.3f}s")
        
        # Show status code distribution
        status_codes = {}
        for result in self.results:
            code = result['status_code']
            status_codes[code] = status_codes.get(code, 0) + 1
        
        print(f"\nStatus Code Distribution:")
        for code, count in sorted(status_codes.items()):
            print(f"  {code}: {count} requests")
        
        # Performance assessment
        avg_time = mean(response_times)
        error_rate = len(failed) / len(self.results) * 100
        
        if avg_time < 1.0 and error_rate < 5:
            status = "🟢 EXCELLENT"
        elif avg_time < 2.0 and error_rate < 10:
            status = "🟡 GOOD"
        elif avg_time < 5.0 and error_rate < 25:
            status = "🟠 ACCEPTABLE"
        else:
            status = "🔴 POOR"
        
        print(f"\nPerformance Status: {status}")
        
        # Show any errors
        if failed:
            print(f"\n❌ Errors ({len(failed)} requests):")
            error_types = {}
            for result in failed:
                error = result.get('error', f"HTTP {result['status_code']}")
                error_types[error] = error_types.get(error, 0) + 1
            
            for error, count in error_types.items():
                print(f"  {error}: {count} times")

def quick_health_check(base_url="https://rssystems.io"):
    """Quick health check function"""
    print("🏥 Quick Health Check")
    print(f"Target: {base_url}")
    
    endpoints = ["/", "/admin/", "/tech/", "/app/"]
    
    for endpoint in endpoints:
        try:
            start = time.time()
            response = requests.get(f"{base_url}{endpoint}", timeout=10)
            duration = time.time() - start
            
            status = "✅" if 200 <= response.status_code < 400 else "❌"
            print(f"{status} {endpoint:15} {response.status_code:3d} {duration:.3f}s")
            
        except Exception as e:
            print(f"❌ {endpoint:15} ERR {str(e)[:40]}")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "health":
        quick_health_check()
    else:
        tester = SimpleLoadTester()
        
        # Parse command line arguments
        num_requests = 50
        num_threads = 5
        
        if len(sys.argv) > 1:
            try:
                num_requests = int(sys.argv[1])
            except ValueError:
                print("Usage: python load_test_simple.py [num_requests] [num_threads]")
                sys.exit(1)
        
        if len(sys.argv) > 2:
            try:
                num_threads = int(sys.argv[2])
            except ValueError:
                print("Usage: python load_test_simple.py [num_requests] [num_threads]")
                sys.exit(1)
        
        tester.run_load_test(num_requests, num_threads)