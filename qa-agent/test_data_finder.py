"""
Test Data Finder - Searches repository for test data and fixtures
"""

import re
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from loguru import logger

from github_client import GitHubClient


@dataclass
class TestDataFile:
    """Represents a test data file found in the repo"""
    path: str
    name: str
    file_type: str  # json, yaml, csv, xml
    content: str
    data: Optional[Dict[str, Any]] = None
    endpoints: List[str] = field(default_factory=list)  # API endpoints found in this file


@dataclass
class APITestData:
    """Test data for a specific API endpoint"""
    endpoint: str
    http_method: str
    base_url: Optional[str] = None
    request_body: Optional[Dict[str, Any]] = None
    headers: Optional[Dict[str, str]] = None
    query_params: Optional[Dict[str, str]] = None
    expected_status: int = 200
    expected_response: Optional[Dict[str, Any]] = None
    description: str = ""
    source_file: str = ""


class TestDataFinder:
    """Finds and parses test data from repository"""
    
    # Common test data directories
    TEST_DATA_DIRS = [
        'test/data',
        'tests/data',
        'test/fixtures',
        'tests/fixtures',
        'testdata',
        'test_data',
        'src/test/resources',
        'src/test/data',
        'fixtures',
        'mocks',
        '__tests__/fixtures',
        '__tests__/data',
        'spec/fixtures',
        'test/resources',
    ]
    
    # Common test data file patterns
    TEST_DATA_PATTERNS = [
        '**/test*.json',
        '**/fixture*.json',
        '**/mock*.json',
        '**/*test_data*.json',
        '**/*testdata*.json',
        '**/api_test*.json',
        '**/request*.json',
        '**/response*.json',
        '**/*_fixture.json',
        '**/sample*.json',
        '**/example*.json',
    ]
    
    # Patterns to identify API test configs
    API_CONFIG_PATTERNS = [
        r'"(endpoint|url|path|api)":\s*"([^"]+)"',
        r'"(method|http_method)":\s*"(GET|POST|PUT|DELETE|PATCH)"',
        r'"(base_url|baseUrl|baseURL)":\s*"([^"]+)"',
    ]
    
    def __init__(self):
        self.github = GitHubClient()
        self._ensure_connected()
    
    def _ensure_connected(self):
        """Ensure GitHub connection is established"""
        if not self.github._client:
            self.github.connect()
    
    def find_test_data_in_repo(
        self, 
        pr_files: List[str] = None,
        search_related: bool = True
    ) -> List[TestDataFile]:
        """Find all test data files in the repository
        
        Args:
            pr_files: List of files changed in PR (to prioritize related test data)
            search_related: If True, search for test data related to PR files
        """
        test_data_files = []
        
        try:
            repo = self.github.repo
            if not repo:
                logger.error("GitHub repo not available")
                return []
            
            # 1. Search common test data directories
            for test_dir in self.TEST_DATA_DIRS:
                try:
                    contents = repo.get_contents(test_dir)
                    test_data_files.extend(
                        self._scan_directory(repo, contents)
                    )
                except Exception:
                    # Directory doesn't exist, skip
                    continue
            
            # 2. If PR files provided, search for related test data
            if pr_files and search_related:
                for pr_file in pr_files:
                    related = self._find_related_test_data(repo, pr_file)
                    for tf in related:
                        if tf.path not in [f.path for f in test_data_files]:
                            test_data_files.append(tf)
            
            logger.info(f"Found {len(test_data_files)} test data files")
            return test_data_files
            
        except Exception as e:
            logger.error(f"Error finding test data: {e}")
            return []
    
    def _scan_directory(self, repo, contents) -> List[TestDataFile]:
        """Recursively scan a directory for test data files"""
        files = []
        
        if not isinstance(contents, list):
            contents = [contents]
        
        for item in contents:
            try:
                if item.type == "dir":
                    # Recursively scan subdirectories
                    sub_contents = repo.get_contents(item.path)
                    files.extend(self._scan_directory(repo, sub_contents))
                elif item.type == "file":
                    # Check if it's a test data file
                    if self._is_test_data_file(item.name):
                        test_file = self._parse_test_file(item)
                        if test_file:
                            files.append(test_file)
            except Exception as e:
                logger.warning(f"Error scanning {item.path}: {e}")
                continue
        
        return files
    
    def _is_test_data_file(self, filename: str) -> bool:
        """Check if a file is likely a test data file"""
        filename_lower = filename.lower()
        
        # Check file extension
        valid_extensions = ['.json', '.yaml', '.yml', '.xml', '.csv']
        has_valid_ext = any(filename_lower.endswith(ext) for ext in valid_extensions)
        
        if not has_valid_ext:
            return False
        
        # Check for test-related keywords in name
        test_keywords = [
            'test', 'fixture', 'mock', 'sample', 'example',
            'request', 'response', 'data', 'stub', 'fake'
        ]
        
        return any(kw in filename_lower for kw in test_keywords)
    
    def _parse_test_file(self, file_content) -> Optional[TestDataFile]:
        """Parse a test data file and extract relevant information"""
        try:
            # Get file content
            content = file_content.decoded_content.decode('utf-8')
            
            file_type = Path(file_content.name).suffix.lstrip('.')
            
            test_file = TestDataFile(
                path=file_content.path,
                name=file_content.name,
                file_type=file_type,
                content=content
            )
            
            # Try to parse JSON
            if file_type == 'json':
                try:
                    test_file.data = json.loads(content)
                    # Look for API endpoints in the data
                    test_file.endpoints = self._extract_endpoints(test_file.data)
                except json.JSONDecodeError:
                    pass
            
            return test_file
            
        except Exception as e:
            logger.warning(f"Error parsing test file {file_content.path}: {e}")
            return None
    
    def _extract_endpoints(self, data: Any, prefix: str = "") -> List[str]:
        """Extract API endpoints from test data structure"""
        endpoints = []
        
        if isinstance(data, dict):
            # Check for endpoint fields
            for key in ['endpoint', 'url', 'path', 'api', 'uri']:
                if key in data and isinstance(data[key], str):
                    endpoints.append(data[key])
            
            # Check for method to identify API calls
            if 'method' in data or 'http_method' in data:
                method = data.get('method') or data.get('http_method', 'GET')
                path = data.get('endpoint') or data.get('url') or data.get('path', '')
                if path:
                    endpoints.append(f"{method.upper()} {path}")
            
            # Recursively check nested structures
            for value in data.values():
                endpoints.extend(self._extract_endpoints(value))
                
        elif isinstance(data, list):
            for item in data:
                endpoints.extend(self._extract_endpoints(item))
        
        return list(set(endpoints))
    
    def _find_related_test_data(self, repo, pr_file: str) -> List[TestDataFile]:
        """Find test data files related to a specific PR file"""
        related = []
        
        # Get the base name without extension
        base_name = Path(pr_file).stem.replace('Controller', '').replace('Service', '')
        
        # Search for test data with similar names
        search_patterns = [
            f"{base_name}_test",
            f"test_{base_name}",
            f"{base_name}_fixture",
            f"{base_name}_data",
            f"{base_name}_mock",
        ]
        
        # Check test directories for related files
        for test_dir in self.TEST_DATA_DIRS[:5]:  # Check first 5 dirs to limit API calls
            try:
                contents = repo.get_contents(test_dir)
                if not isinstance(contents, list):
                    contents = [contents]
                
                for item in contents:
                    if item.type == "file":
                        item_name_lower = item.name.lower()
                        for pattern in search_patterns:
                            if pattern.lower() in item_name_lower:
                                test_file = self._parse_test_file(item)
                                if test_file:
                                    related.append(test_file)
                                break
            except Exception:
                continue
        
        return related
    
    def extract_api_test_data(
        self, 
        test_files: List[TestDataFile],
        target_endpoints: List[Dict[str, str]] = None
    ) -> List[APITestData]:
        """Extract API test data from test files
        
        Args:
            test_files: List of test data files
            target_endpoints: List of endpoints from PR analysis to match against
        """
        api_tests = []
        
        for tf in test_files:
            if not tf.data:
                continue
            
            # Try to extract API test configurations
            tests = self._parse_api_test_config(tf.data, tf.path)
            api_tests.extend(tests)
        
        # If target endpoints provided, filter/prioritize
        if target_endpoints:
            # First add exact matches
            matched = []
            unmatched = []
            
            for test in api_tests:
                is_match = any(
                    test.endpoint.lower() in ep.get('path', '').lower() or
                    ep.get('path', '').lower() in test.endpoint.lower()
                    for ep in target_endpoints
                )
                if is_match:
                    matched.append(test)
                else:
                    unmatched.append(test)
            
            # Return matched first, then unmatched
            api_tests = matched + unmatched[:5]  # Limit unmatched to prevent too many tests
        
        logger.info(f"Extracted {len(api_tests)} API test configurations")
        return api_tests
    
    def _parse_api_test_config(
        self, 
        data: Any, 
        source_file: str
    ) -> List[APITestData]:
        """Parse API test configuration from data structure"""
        tests = []
        
        if isinstance(data, dict):
            # Check if this dict is an API test config
            if self._looks_like_api_test(data):
                test = self._create_api_test_from_dict(data, source_file)
                if test:
                    tests.append(test)
            
            # Check for test arrays
            for key in ['tests', 'testCases', 'test_cases', 'requests', 'api_tests']:
                if key in data and isinstance(data[key], list):
                    for item in data[key]:
                        if isinstance(item, dict):
                            test = self._create_api_test_from_dict(item, source_file)
                            if test:
                                tests.append(test)
            
            # Recursively check nested objects
            for value in data.values():
                if isinstance(value, (dict, list)):
                    tests.extend(self._parse_api_test_config(value, source_file))
                    
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    test = self._create_api_test_from_dict(item, source_file)
                    if test:
                        tests.append(test)
        
        return tests
    
    def _looks_like_api_test(self, data: dict) -> bool:
        """Check if a dict looks like an API test configuration"""
        api_keys = ['endpoint', 'url', 'path', 'uri', 'api']
        method_keys = ['method', 'http_method', 'httpMethod']
        
        has_endpoint = any(k in data for k in api_keys)
        has_method = any(k in data for k in method_keys)
        has_request = 'request' in data or 'body' in data or 'request_body' in data
        
        return has_endpoint or (has_method and (has_request or has_endpoint))
    
    def _create_api_test_from_dict(
        self, 
        data: dict, 
        source_file: str
    ) -> Optional[APITestData]:
        """Create APITestData from a dict configuration"""
        try:
            # Extract endpoint
            endpoint = (
                data.get('endpoint') or 
                data.get('url') or 
                data.get('path') or 
                data.get('uri') or
                data.get('api', '')
            )
            
            if not endpoint:
                return None
            
            # Extract method
            method = (
                data.get('method') or 
                data.get('http_method') or 
                data.get('httpMethod', 'GET')
            ).upper()
            
            # Extract request body
            request_body = (
                data.get('body') or 
                data.get('request_body') or 
                data.get('requestBody') or
                data.get('request', {}).get('body') or
                data.get('data')
            )
            
            # Extract headers
            headers = (
                data.get('headers') or 
                data.get('request', {}).get('headers')
            )
            
            # Extract query params
            query_params = (
                data.get('params') or 
                data.get('query_params') or 
                data.get('queryParams') or
                data.get('query')
            )
            
            # Extract expected response
            expected_response = (
                data.get('expected_response') or 
                data.get('expectedResponse') or 
                data.get('response') or
                data.get('expected')
            )
            
            # Extract expected status
            expected_status = data.get('expected_status') or data.get('status') or 200
            if isinstance(expected_status, str):
                expected_status = int(expected_status)
            
            # Extract base URL
            base_url = data.get('base_url') or data.get('baseUrl') or data.get('baseURL')
            
            return APITestData(
                endpoint=endpoint,
                http_method=method,
                base_url=base_url,
                request_body=request_body,
                headers=headers,
                query_params=query_params,
                expected_status=expected_status,
                expected_response=expected_response,
                description=data.get('description', '') or data.get('name', ''),
                source_file=source_file
            )
            
        except Exception as e:
            logger.warning(f"Error creating API test from dict: {e}")
            return None
    
    def generate_test_data_for_endpoints(
        self, 
        endpoints: List[Dict[str, str]],
        base_url: str = None
    ) -> List[APITestData]:
        """Generate test data for endpoints that don't have existing test data
        
        This creates basic test templates that can be executed
        """
        tests = []
        
        for ep in endpoints:
            http_method = ep.get('http_method', 'GET')
            path = ep.get('path', '/')
            
            # Generate sample request body for write operations
            request_body = None
            if http_method in ['POST', 'PUT', 'PATCH']:
                request_body = {
                    "id": "test_123",
                    "name": "Test Data",
                    "description": "Auto-generated test data"
                }
            
            test = APITestData(
                endpoint=path,
                http_method=http_method,
                base_url=base_url,
                request_body=request_body,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                },
                expected_status=200 if http_method == 'GET' else 201,
                description=f"Auto-generated test for {http_method} {path}",
                source_file="auto-generated"
            )
            tests.append(test)
        
        return tests


# Quick test
if __name__ == "__main__":
    finder = TestDataFinder()
    
    # Test finding test data
    files = finder.find_test_data_in_repo()
    
    print(f"\nFound {len(files)} test data files:")
    for f in files[:10]:
        print(f"  - {f.path} ({f.file_type})")
        if f.endpoints:
            print(f"    Endpoints: {f.endpoints[:3]}")

