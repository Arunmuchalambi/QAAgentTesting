"""
API Test Executor - Executes API tests and captures results
"""

import time
import json
import traceback
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from enum import Enum
import requests
from requests.exceptions import RequestException, Timeout, ConnectionError
from loguru import logger

from test_data_finder import APITestData


class TestStatus(Enum):
    """Test execution status"""
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass
class APIRequest:
    """Captured API request details"""
    method: str
    url: str
    headers: Dict[str, str] = field(default_factory=dict)
    body: Optional[Any] = None
    params: Optional[Dict[str, str]] = None
    timestamp: str = ""


@dataclass
class APIResponse:
    """Captured API response details"""
    status_code: int
    body: Any = None
    headers: Dict[str, str] = field(default_factory=dict)
    response_time_ms: float = 0
    error: Optional[str] = None


@dataclass
class TestResult:
    """Result of a single test execution"""
    test_id: str
    test_name: str
    description: str
    status: TestStatus
    request: APIRequest
    response: Optional[APIResponse]
    expected_status: int
    actual_status: int
    assertions: List[Dict[str, Any]] = field(default_factory=list)  # Assertion results
    error_message: Optional[str] = None
    suggestions: List[str] = field(default_factory=list)
    execution_time_ms: float = 0
    source_file: str = ""
    pr_related: bool = False


@dataclass
class TestExecutionSummary:
    """Summary of all test executions"""
    total_tests: int
    passed: int
    failed: int
    errors: int
    skipped: int
    total_time_ms: float
    results: List[TestResult]
    pr_number: Optional[int] = None
    execution_timestamp: str = ""
    overall_status: TestStatus = TestStatus.PASSED


class APITestExecutor:
    """Executes API tests and captures detailed results"""
    
    def __init__(
        self, 
        base_url: str = None,
        default_headers: Dict[str, str] = None,
        timeout_seconds: int = 30,
        verify_ssl: bool = True
    ):
        self.base_url = base_url or ""
        self.default_headers = default_headers or {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        self.timeout = timeout_seconds
        self.verify_ssl = verify_ssl
        self.session = requests.Session()
    
    def execute_tests(
        self, 
        api_tests: List[APITestData],
        pr_number: int = None,
        auth_token: str = None
    ) -> TestExecutionSummary:
        """Execute all API tests and return summary
        
        Args:
            api_tests: List of API test configurations
            pr_number: PR number for reference
            auth_token: Optional auth token for API calls
        """
        results = []
        start_time = time.time()
        
        # Add auth token if provided
        if auth_token:
            self.default_headers["Authorization"] = f"Bearer {auth_token}"
        
        for i, test in enumerate(api_tests, 1):
            test_id = f"TC_{i:03d}"
            logger.info(f"Executing test {test_id}: {test.http_method} {test.endpoint}")
            
            result = self._execute_single_test(test, test_id)
            results.append(result)
            
            # Small delay between tests to avoid rate limiting
            time.sleep(0.5)
        
        total_time = (time.time() - start_time) * 1000
        
        # Calculate summary
        passed = sum(1 for r in results if r.status == TestStatus.PASSED)
        failed = sum(1 for r in results if r.status == TestStatus.FAILED)
        errors = sum(1 for r in results if r.status == TestStatus.ERROR)
        skipped = sum(1 for r in results if r.status == TestStatus.SKIPPED)
        
        overall_status = TestStatus.PASSED
        if failed > 0 or errors > 0:
            overall_status = TestStatus.FAILED
        
        return TestExecutionSummary(
            total_tests=len(results),
            passed=passed,
            failed=failed,
            errors=errors,
            skipped=skipped,
            total_time_ms=total_time,
            results=results,
            pr_number=pr_number,
            execution_timestamp=datetime.now().isoformat(),
            overall_status=overall_status
        )
    
    def _execute_single_test(
        self, 
        test: APITestData, 
        test_id: str
    ) -> TestResult:
        """Execute a single API test"""
        
        # Build full URL
        full_url = self._build_url(test.endpoint, test.base_url)
        
        # Prepare headers
        headers = {**self.default_headers}
        if test.headers:
            headers.update(test.headers)
        
        # Create request record
        request = APIRequest(
            method=test.http_method,
            url=full_url,
            headers=headers,
            body=test.request_body,
            params=test.query_params,
            timestamp=datetime.now().isoformat()
        )
        
        # Execute the request
        start_time = time.time()
        response = None
        error_message = None
        status = TestStatus.PASSED
        assertions = []
        suggestions = []
        
        try:
            # Make the actual HTTP request
            http_response = self._make_request(
                method=test.http_method,
                url=full_url,
                headers=headers,
                json_body=test.request_body,
                params=test.query_params
            )
            
            execution_time = (time.time() - start_time) * 1000
            
            # Parse response
            response_body = self._parse_response_body(http_response)
            
            response = APIResponse(
                status_code=http_response.status_code,
                body=response_body,
                headers=dict(http_response.headers),
                response_time_ms=execution_time
            )
            
            # Run assertions
            assertions, status = self._run_assertions(
                test, response, assertions
            )
            
            # Generate suggestions if failed
            if status == TestStatus.FAILED:
                suggestions = self._generate_suggestions(test, response, assertions)
            
        except ConnectionError as e:
            status = TestStatus.ERROR
            error_message = f"Connection failed: {str(e)}"
            suggestions = [
                "🔌 Check if the API server is running",
                "🌐 Verify the base URL is correct",
                "🔒 Check network connectivity and firewall settings"
            ]
            
        except Timeout as e:
            status = TestStatus.ERROR
            error_message = f"Request timed out after {self.timeout}s"
            suggestions = [
                "⏱️ The endpoint might be slow - consider increasing timeout",
                "🔍 Check if the server is under heavy load",
                "📊 Monitor server performance"
            ]
            
        except RequestException as e:
            status = TestStatus.ERROR
            error_message = f"Request failed: {str(e)}"
            suggestions = [
                "🔍 Check the request format",
                "📝 Verify headers and authentication"
            ]
            
        except Exception as e:
            status = TestStatus.ERROR
            error_message = f"Unexpected error: {str(e)}\n{traceback.format_exc()}"
            suggestions = [
                "🐛 An unexpected error occurred - check logs for details"
            ]
        
        execution_time = (time.time() - start_time) * 1000
        
        return TestResult(
            test_id=test_id,
            test_name=f"{test.http_method} {test.endpoint}",
            description=test.description or f"Test API endpoint {test.endpoint}",
            status=status,
            request=request,
            response=response,
            expected_status=test.expected_status,
            actual_status=response.status_code if response else 0,
            assertions=assertions,
            error_message=error_message,
            suggestions=suggestions,
            execution_time_ms=execution_time,
            source_file=test.source_file,
            pr_related=True if test.source_file != "auto-generated" else False
        )
    
    def _build_url(self, endpoint: str, test_base_url: str = None) -> str:
        """Build full URL from endpoint and base URL"""
        base = test_base_url or self.base_url
        
        if endpoint.startswith(('http://', 'https://')):
            return endpoint
        
        if base:
            base = base.rstrip('/')
            endpoint = endpoint.lstrip('/')
            return f"{base}/{endpoint}"
        
        return endpoint
    
    def _make_request(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        json_body: Any = None,
        params: Dict[str, str] = None
    ) -> requests.Response:
        """Make the actual HTTP request"""
        
        method = method.upper()
        
        kwargs = {
            "headers": headers,
            "timeout": self.timeout,
            "verify": self.verify_ssl
        }
        
        if params:
            kwargs["params"] = params
        
        if json_body and method in ['POST', 'PUT', 'PATCH']:
            kwargs["json"] = json_body
        
        return self.session.request(method, url, **kwargs)
    
    def _parse_response_body(self, response: requests.Response) -> Any:
        """Parse response body, trying JSON first"""
        try:
            return response.json()
        except:
            # Return text if not JSON
            text = response.text
            if len(text) > 5000:
                return text[:5000] + "... (truncated)"
            return text
    
    def _run_assertions(
        self, 
        test: APITestData, 
        response: APIResponse,
        assertions: List[Dict]
    ) -> tuple:
        """Run assertions on the response"""
        status = TestStatus.PASSED
        
        # 1. Status code assertion
        status_assertion = {
            "type": "status_code",
            "expected": test.expected_status,
            "actual": response.status_code,
            "passed": response.status_code == test.expected_status
        }
        assertions.append(status_assertion)
        
        if not status_assertion["passed"]:
            status = TestStatus.FAILED
        
        # 2. Response time assertion (default: should be under 5 seconds)
        time_threshold = 5000  # ms
        time_assertion = {
            "type": "response_time",
            "expected": f"< {time_threshold}ms",
            "actual": f"{response.response_time_ms:.0f}ms",
            "passed": response.response_time_ms < time_threshold
        }
        assertions.append(time_assertion)
        
        # 3. Response body assertion (if expected response provided)
        if test.expected_response:
            body_assertion = self._assert_response_body(
                test.expected_response, response.body
            )
            assertions.append(body_assertion)
            if not body_assertion["passed"]:
                status = TestStatus.FAILED
        
        # 4. Check for error responses
        if response.status_code >= 400:
            error_assertion = {
                "type": "no_error",
                "expected": "No error response",
                "actual": f"Error {response.status_code}",
                "passed": False
            }
            assertions.append(error_assertion)
            status = TestStatus.FAILED
        
        return assertions, status
    
    def _assert_response_body(
        self, 
        expected: Any, 
        actual: Any
    ) -> Dict[str, Any]:
        """Assert response body matches expected"""
        
        if isinstance(expected, dict) and isinstance(actual, dict):
            # Check if expected keys exist in actual
            missing_keys = []
            mismatched_values = []
            
            for key, expected_value in expected.items():
                if key not in actual:
                    missing_keys.append(key)
                elif expected_value is not None and actual[key] != expected_value:
                    if not (expected_value == "*" or expected_value == "any"):
                        mismatched_values.append({
                            "key": key,
                            "expected": expected_value,
                            "actual": actual[key]
                        })
            
            passed = len(missing_keys) == 0 and len(mismatched_values) == 0
            
            details = ""
            if missing_keys:
                details += f"Missing keys: {missing_keys}. "
            if mismatched_values:
                details += f"Mismatched: {mismatched_values}"
            
            return {
                "type": "response_body",
                "expected": str(expected)[:200],
                "actual": str(actual)[:200],
                "passed": passed,
                "details": details if details else "All expected fields match"
            }
        
        # Simple equality check
        return {
            "type": "response_body",
            "expected": str(expected)[:200],
            "actual": str(actual)[:200],
            "passed": expected == actual
        }
    
    def _generate_suggestions(
        self, 
        test: APITestData, 
        response: APIResponse,
        assertions: List[Dict]
    ) -> List[str]:
        """Generate improvement suggestions based on failure"""
        suggestions = []
        
        for assertion in assertions:
            if not assertion.get("passed", True):
                assertion_type = assertion.get("type", "")
                
                if assertion_type == "status_code":
                    expected = assertion.get("expected")
                    actual = assertion.get("actual")
                    
                    if actual == 401:
                        suggestions.append("🔐 Authentication failed - check API token/credentials")
                    elif actual == 403:
                        suggestions.append("🚫 Access denied - verify user permissions")
                    elif actual == 404:
                        suggestions.append("❓ Resource not found - verify endpoint path is correct")
                    elif actual == 500:
                        suggestions.append("💥 Server error - check server logs for stack trace")
                    elif actual == 400:
                        suggestions.append("📝 Bad request - validate request body format")
                    else:
                        suggestions.append(f"⚠️ Expected status {expected}, got {actual}")
                
                elif assertion_type == "response_time":
                    suggestions.append("⏱️ Response time is slow - consider optimization")
                    suggestions.append("📊 Add database indexes if querying is slow")
                    suggestions.append("💾 Consider caching frequently accessed data")
                
                elif assertion_type == "response_body":
                    suggestions.append("📋 Response body doesn't match expected structure")
                    suggestions.append("🔍 Check API documentation for correct response format")
                    if assertion.get("details"):
                        suggestions.append(f"   Details: {assertion['details']}")
        
        # General suggestions for failed tests
        if response and response.status_code >= 400:
            suggestions.append("📚 Review API documentation for correct usage")
            suggestions.append("🧪 Add input validation if handling user input")
        
        return suggestions


def execute_api_tests_for_pr(
    api_tests: List[APITestData],
    pr_number: int,
    base_url: str = None,
    auth_token: str = None
) -> TestExecutionSummary:
    """Convenience function to execute tests for a PR
    
    Args:
        api_tests: List of API test data
        pr_number: PR number
        base_url: Base URL for API calls
        auth_token: Optional auth token
    """
    executor = APITestExecutor(base_url=base_url)
    return executor.execute_tests(
        api_tests=api_tests,
        pr_number=pr_number,
        auth_token=auth_token
    )


# Quick test
if __name__ == "__main__":
    # Test with a sample API
    test_data = APITestData(
        endpoint="https://jsonplaceholder.typicode.com/posts/1",
        http_method="GET",
        expected_status=200,
        description="Get a sample post"
    )
    
    executor = APITestExecutor()
    result = executor._execute_single_test(test_data, "TC_001")
    
    print(f"\nTest: {result.test_name}")
    print(f"Status: {result.status.value}")
    print(f"Response Code: {result.actual_status}")
    print(f"Time: {result.execution_time_ms:.0f}ms")
    
    for assertion in result.assertions:
        symbol = "✅" if assertion["passed"] else "❌"
        print(f"{symbol} {assertion['type']}: {assertion.get('details', assertion['actual'])}")

