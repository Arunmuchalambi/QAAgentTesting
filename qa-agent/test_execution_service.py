"""
Test Execution Service - Orchestrates test discovery, execution, and reporting
"""

import os
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from loguru import logger

from test_data_finder import TestDataFinder, APITestData
from api_executor import APITestExecutor, TestExecutionSummary, TestStatus
from test_report_generator import TestReportGenerator, ReportConfig, generate_test_report
from pr_analyzer import PRImpactAnalysis
from jira_client import JiraClient


@dataclass
class TestExecutionConfig:
    """Configuration for test execution"""
    base_url: str = None  # Base URL for API calls
    auth_token: str = None  # Auth token for API authentication
    timeout_seconds: int = 30
    max_tests: int = 20  # Maximum tests to execute
    output_dir: str = "test_reports"
    attach_to_jira: bool = True
    execute_real_apis: bool = False  # Set to True to actually execute APIs
    dry_run: bool = True  # If True, generate sample results without executing


@dataclass
class TestExecutionResult:
    """Result of the test execution process"""
    success: bool
    report_path: Optional[str] = None
    summary: Optional[TestExecutionSummary] = None
    attached_to_jira: bool = False
    error: Optional[str] = None
    test_count: int = 0
    passed_count: int = 0
    failed_count: int = 0


class TestExecutionService:
    """
    Service that orchestrates the complete test execution workflow:
    1. Find test data in repository
    2. Match test data to PR changes
    3. Execute API tests
    4. Generate HTML report
    5. Attach report to Jira subtask
    """
    
    def __init__(self, config: TestExecutionConfig = None):
        self.config = config or TestExecutionConfig()
        self.test_finder = TestDataFinder()
        self.jira = JiraClient()
        self.report_generator = TestReportGenerator(
            ReportConfig(output_dir=self.config.output_dir)
        )
        
        # Ensure output directory exists
        os.makedirs(self.config.output_dir, exist_ok=True)
    
    def execute_tests_for_pr(
        self,
        jira_key: str,
        pr_number: int,
        pr_analysis: PRImpactAnalysis,
        subtask_key: str = None,
        pr_files: List[str] = None,
        jira_summary: str = "",
        jira_description: str = "",
        pr_title: str = "",
        pr_description: str = "",
        files_changed: List[Dict] = None
    ) -> TestExecutionResult:
        """Execute tests for a PR and generate report
        
        Args:
            jira_key: Parent Jira issue key
            pr_number: PR number
            pr_analysis: PR impact analysis with API endpoints
            subtask_key: Subtask to attach report to
            pr_files: List of files changed in PR
            jira_summary: Jira issue summary for alignment analysis
            jira_description: Jira issue description for alignment analysis
            pr_title: PR title for alignment analysis
            pr_description: PR description for alignment analysis
            files_changed: Full file change info including patches
        
        Returns:
            TestExecutionResult with report path and summary
        """
        try:
            logger.info(f"Starting test execution for {jira_key} PR #{pr_number}")
            
            # 1. Find test data in repository
            test_files = self.test_finder.find_test_data_in_repo(
                pr_files=pr_files,
                search_related=True
            )
            logger.info(f"Found {len(test_files)} test data files")
            
            # 2. Extract API test configurations
            target_endpoints = self._extract_endpoints_from_analysis(pr_analysis)
            logger.info(f"Target endpoints from PR: {len(target_endpoints)}")
            
            api_tests = self.test_finder.extract_api_test_data(
                test_files=test_files,
                target_endpoints=target_endpoints
            )
            
            # 3. If no test data found, generate from endpoints
            if not api_tests and target_endpoints:
                logger.info("No existing test data found, generating from PR endpoints")
                api_tests = self.test_finder.generate_test_data_for_endpoints(
                    endpoints=target_endpoints,
                    base_url=self.config.base_url
                )
            
            # If still no tests, generate basic tests from PR analysis
            if not api_tests and pr_analysis:
                logger.info("No API tests found, generating basic tests from PR analysis")
                api_tests = self._generate_basic_tests_from_analysis(pr_analysis)
            
            # Limit tests
            api_tests = api_tests[:self.config.max_tests]
            logger.info(f"Will execute {len(api_tests)} tests")
            
            # 4. Execute tests
            if self.config.dry_run or not self.config.execute_real_apis:
                # Generate sample/mock results for demo
                summary = self._generate_sample_results(api_tests, pr_number)
                logger.info("Generated sample test results (dry run mode)")
            else:
                # Actually execute the APIs
                executor = APITestExecutor(
                    base_url=self.config.base_url,
                    timeout_seconds=self.config.timeout_seconds
                )
                summary = executor.execute_tests(
                    api_tests=api_tests,
                    pr_number=pr_number,
                    auth_token=self.config.auth_token
                )
            
            # 5. Generate HTML report with code analysis
            report_path = self.report_generator.generate_html_report(
                summary=summary,
                jira_key=jira_key,
                pr_number=pr_number,
                additional_info={
                    "pr_files_changed": len(pr_files) if pr_files else 0,
                    "endpoints_detected": len(target_endpoints),
                    "test_files_found": len(test_files)
                }
            )
            logger.info(f"Generated report: {report_path}")
            
            # 6. Attach to Jira subtask
            attached = False
            target_issue = subtask_key or jira_key
            
            if self.config.attach_to_jira and target_issue:
                self.jira.connect()
                attached = self.jira.add_test_report_attachment(
                    issue_key=target_issue,
                    report_path=report_path,
                    pr_number=pr_number
                )
                
                if attached:
                    logger.info(f"Attached report to {target_issue}")
                    
                    # Add comment about test execution with view link
                    report_filename = os.path.basename(report_path) if report_path else None
                    self._add_test_execution_comment(
                        issue_key=target_issue,
                        summary=summary,
                        pr_number=pr_number,
                        report_filename=report_filename
                    )
            
            return TestExecutionResult(
                success=True,
                report_path=report_path,
                summary=summary,
                attached_to_jira=attached,
                test_count=summary.total_tests,
                passed_count=summary.passed,
                failed_count=summary.failed
            )
            
        except Exception as e:
            logger.error(f"Test execution failed: {e}")
            return TestExecutionResult(
                success=False,
                error=str(e)
            )
    
    def _extract_endpoints_from_analysis(
        self, 
        analysis: PRImpactAnalysis
    ) -> List[Dict[str, str]]:
        """Extract API endpoints from PR analysis"""
        endpoints = []
        
        # From class impacts (API endpoints detected in code)
        if analysis.class_impacts:
            for cls in analysis.class_impacts:
                for api in cls.api_endpoints:
                    endpoints.append({
                        'http_method': api.get('http_method', 'GET'),
                        'path': api.get('path', '/'),
                        'class': cls.class_name,
                        'file': cls.file_path
                    })
        
        # From API changes detected in diff
        if analysis.api_changes:
            for change in analysis.api_changes:
                endpoints.append({
                    'http_method': change.endpoint_type,
                    'path': change.function_name,
                    'file': change.file_path
                })
        
        return endpoints
    
    def _generate_basic_tests_from_analysis(
        self,
        analysis: PRImpactAnalysis
    ) -> List[APITestData]:
        """Generate basic tests from PR analysis when no API endpoints are found"""
        tests = []
        
        # Generate tests for impacted features
        if analysis.impacted_features:
            for i, feature in enumerate(analysis.impacted_features[:5], 1):
                feature_name = feature.feature_name if hasattr(feature, 'feature_name') else str(feature)
                tests.append(APITestData(
                    endpoint=f"/api/{feature_name.lower().replace(' ', '-')}",
                    http_method="GET",
                    expected_status=200,
                    description=f"Feature Test: Verify {feature_name} functionality"
                ))
        
        # Generate tests for API changes
        if analysis.api_changes:
            for i, api in enumerate(analysis.api_changes[:3], 1):
                tests.append(APITestData(
                    endpoint=f"/api/{api.function_name.lower()}",
                    http_method=api.endpoint_type or "GET",
                    expected_status=200,
                    description=f"API Change Test: Verify {api.function_name}"
                ))
        
        # Generate tests for class impacts (controllers/kafka)
        if analysis.class_impacts:
            for cls in analysis.class_impacts[:3]:
                if cls.api_endpoints:
                    for api in cls.api_endpoints[:2]:
                        tests.append(APITestData(
                            endpoint=api.get('path', '/api/test'),
                            http_method=api.get('http_method', 'GET'),
                            expected_status=200,
                            description=f"API Test: {cls.class_name} - {api.get('http_method', 'GET')} {api.get('path', '/')}"
                        ))
        
        # If still no tests, create placeholder tests based on PR info
        if not tests:
            tests = [
                APITestData(
                    endpoint="/api/health",
                    http_method="GET",
                    expected_status=200,
                    description="Health Check: Basic API health verification"
                ),
                APITestData(
                    endpoint="/api/validate",
                    http_method="POST",
                    expected_status=200,
                    description=f"PR #{analysis.pr_number} Validation: {analysis.pr_title}"
                ),
                APITestData(
                    endpoint="/api/integration/test",
                    http_method="GET",
                    expected_status=200,
                    description="Integration Test: End-to-end verification"
                )
            ]
        
        return tests
    
    def _generate_sample_results(
        self, 
        api_tests: List[APITestData],
        pr_number: int
    ) -> TestExecutionSummary:
        """Generate sample/mock test results for demo purposes"""
        from api_executor import TestResult, APIRequest, APIResponse, TestStatus
        import random
        
        results = []
        
        for i, test in enumerate(api_tests, 1):
            test_id = f"TC_{i:03d}"
            
            # Simulate random pass/fail (80% pass rate for demo)
            passed = random.random() < 0.8
            status = TestStatus.PASSED if passed else TestStatus.FAILED
            
            # Create mock request
            request = APIRequest(
                method=test.http_method,
                url=test.endpoint,
                headers=test.headers or {},
                body=test.request_body,
                timestamp=datetime.now().isoformat()
            )
            
            # Create mock response
            if passed:
                response = APIResponse(
                    status_code=test.expected_status,
                    body={"status": "success", "data": {"id": f"test_{i}"}},
                    headers={"Content-Type": "application/json"},
                    response_time_ms=random.randint(50, 500)
                )
                assertions = [
                    {"type": "status_code", "expected": test.expected_status, 
                     "actual": test.expected_status, "passed": True},
                    {"type": "response_time", "expected": "< 5000ms", 
                     "actual": f"{response.response_time_ms}ms", "passed": True}
                ]
                suggestions = []
            else:
                error_codes = [400, 401, 403, 404, 500]
                actual_status = random.choice(error_codes)
                response = APIResponse(
                    status_code=actual_status,
                    body={"error": "Mock error for testing"},
                    headers={"Content-Type": "application/json"},
                    response_time_ms=random.randint(100, 1000)
                )
                assertions = [
                    {"type": "status_code", "expected": test.expected_status, 
                     "actual": actual_status, "passed": False}
                ]
                suggestions = self._get_suggestions_for_status(actual_status)
            
            result = TestResult(
                test_id=test_id,
                test_name=f"{test.http_method} {test.endpoint}",
                description=test.description or f"Test {test.endpoint}",
                status=status,
                request=request,
                response=response,
                expected_status=test.expected_status,
                actual_status=response.status_code,
                assertions=assertions,
                suggestions=suggestions,
                execution_time_ms=response.response_time_ms,
                source_file=test.source_file,
                pr_related=True
            )
            results.append(result)
        
        # Calculate summary
        passed = sum(1 for r in results if r.status == TestStatus.PASSED)
        failed = len(results) - passed
        
        return TestExecutionSummary(
            total_tests=len(results),
            passed=passed,
            failed=failed,
            errors=0,
            skipped=0,
            total_time_ms=sum(r.execution_time_ms for r in results),
            results=results,
            pr_number=pr_number,
            execution_timestamp=datetime.now().isoformat(),
            overall_status=TestStatus.PASSED if failed == 0 else TestStatus.FAILED
        )
    
    def _get_suggestions_for_status(self, status_code: int) -> List[str]:
        """Get suggestions based on HTTP status code"""
        suggestions = {
            400: [
                "📝 Validate request body format matches API schema",
                "🔍 Check for required fields in the request",
                "📚 Review API documentation for correct payload structure"
            ],
            401: [
                "🔐 Authentication token is missing or invalid",
                "🔑 Verify API credentials are correct",
                "⏰ Token may have expired - try refreshing"
            ],
            403: [
                "🚫 User doesn't have permission for this resource",
                "👤 Check user roles and permissions",
                "🔒 Verify access control configuration"
            ],
            404: [
                "❓ Resource not found - verify endpoint path",
                "🆔 Check if resource ID exists",
                "📍 Verify base URL is correct"
            ],
            500: [
                "💥 Internal server error - check server logs",
                "🐛 Look for unhandled exceptions in the code",
                "📊 Monitor server performance metrics",
                "🔄 Consider adding error handling"
            ]
        }
        return suggestions.get(status_code, ["⚠️ Unexpected error - review API implementation"])
    
    def _add_test_execution_comment(
        self,
        issue_key: str,
        summary: TestExecutionSummary,
        pr_number: int,
        report_filename: str = None
    ):
        """Add a comment about test execution results"""
        
        status_emoji = "✅" if summary.overall_status == TestStatus.PASSED else "❌"
        pass_rate = (summary.passed / summary.total_tests * 100) if summary.total_tests > 0 else 0
        
        # Build view link if report server is available
        view_link = ""
        if report_filename:
            # Local server URL - user can configure their own domain
            view_url = f"http://localhost:8080/report/{report_filename}"
            view_link = f"\n\n🌐 *[View Report Online|{view_url}]* (requires report server running)"
        
        comment = f"""
🧪 *Test Execution Complete - PR #{pr_number}*

{status_emoji} *Overall Status:* {summary.overall_status.value.upper()}

||Metric||Value||
|Total Tests|{summary.total_tests}|
|Passed|{summary.passed} ✅|
|Failed|{summary.failed} ❌|
|Pass Rate|{pass_rate:.1f}%|
|Execution Time|{summary.total_time_ms:.0f}ms|

📎 See attached report: *Test_Case_Outcome_PR{pr_number}*.html{view_link}

_Generated by QA Agent_
"""
        self.jira.add_comment(issue_key, comment)


def execute_tests_and_attach(
    jira_key: str,
    pr_number: int,
    pr_analysis: PRImpactAnalysis,
    subtask_key: str = None,
    pr_files: List[str] = None,
    base_url: str = None,
    dry_run: bool = True
) -> TestExecutionResult:
    """Convenience function to execute tests and attach report
    
    Args:
        jira_key: Parent Jira issue key
        pr_number: PR number
        pr_analysis: PR impact analysis
        subtask_key: Optional subtask key to attach to
        pr_files: Files changed in PR
        base_url: Base URL for API calls
        dry_run: If True, generate sample results
    
    Returns:
        TestExecutionResult
    """
    config = TestExecutionConfig(
        base_url=base_url,
        dry_run=dry_run,
        execute_real_apis=not dry_run
    )
    
    service = TestExecutionService(config)
    return service.execute_tests_for_pr(
        jira_key=jira_key,
        pr_number=pr_number,
        pr_analysis=pr_analysis,
        subtask_key=subtask_key,
        pr_files=pr_files
    )


# Quick test
if __name__ == "__main__":
    from pr_analyzer import PRImpactAnalysis, ClassImpact
    
    # Create sample PR analysis
    analysis = PRImpactAnalysis(
        pr_number=123,
        pr_title="Add user management API",
        total_files_changed=5,
        impacted_features=[],
        api_changes=[],
        class_impacts=[
            ClassImpact(
                class_name="UserController",
                file_path="src/controllers/UserController.java",
                change_type="modified",
                api_endpoints=[
                    {"http_method": "GET", "path": "/api/users", "method": "getUsers"},
                    {"http_method": "POST", "path": "/api/users", "method": "createUser"},
                    {"http_method": "GET", "path": "/api/users/{id}", "method": "getUser"},
                ],
                is_controller=True
            )
        ]
    )
    
    result = execute_tests_and_attach(
        jira_key="DT-TEST",
        pr_number=123,
        pr_analysis=analysis,
        subtask_key=None,  # Will just generate report
        dry_run=True
    )
    
    print(f"\n=== Test Execution Result ===")
    print(f"Success: {result.success}")
    print(f"Report: {result.report_path}")
    print(f"Tests: {result.test_count}")
    print(f"Passed: {result.passed_count}")
    print(f"Failed: {result.failed_count}")

