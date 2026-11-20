"""
PR Analyzer - Analyzes Pull Request changes and identifies impact
"""

import re
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from loguru import logger

from github_client import GitHubClient, PRDetails, PRFile


@dataclass
class ImpactedFeature:
    """Represents a feature impacted by code changes"""
    feature_name: str
    description: str
    impact_level: str  # high, medium, low
    test_types: List[str]
    files_affected: List[str]
    reason: str


@dataclass
class APIChange:
    """Represents an API endpoint that was changed"""
    endpoint_type: str  # GET, POST, PUT, DELETE
    file_path: str
    function_name: str
    change_type: str  # added, modified, removed
    line_number: Optional[int] = None


@dataclass
class ClassImpact:
    """Represents a class that was changed and its API/Kafka impacts"""
    class_name: str
    file_path: str
    change_type: str  # added, modified, deleted
    api_endpoints: List[Dict[str, str]] = field(default_factory=list)  # [{method, path, http_method}]
    kafka_impacts: List[Dict[str, str]] = field(default_factory=list)  # [{type, topic}]
    is_controller: bool = False
    is_service: bool = False
    is_kafka_related: bool = False


@dataclass
class PRImpactAnalysis:
    """Complete impact analysis for a PR"""
    pr_number: int
    pr_title: str
    total_files_changed: int
    impacted_features: List[ImpactedFeature]
    api_changes: List[APIChange]
    class_impacts: List[ClassImpact] = field(default_factory=list)  # NEW: Classes with API/Kafka
    critical_changes: bool = False
    test_recommendations: List[str] = field(default_factory=list)
    summary: str = ""
    raw_changes: Dict[str, Any] = field(default_factory=dict)


class PRAnalyzer:
    """Analyzes PR changes and identifies impact"""
    
    def __init__(self, mapping_file: str = "component_mapping.json"):
        self.github = GitHubClient()
        self.mapping = self._load_mapping(mapping_file)
    
    def _load_mapping(self, mapping_file: str) -> Dict:
        """Load component mapping configuration"""
        mapping_path = Path(__file__).parent / mapping_file
        if mapping_path.exists():
            with open(mapping_path) as f:
                return json.load(f)
        logger.warning(f"Mapping file {mapping_file} not found, using defaults")
        return {"repositories": {}, "file_patterns": {}, "api_patterns": {}}
    
    def analyze_pr(self, pr_number: int) -> Optional[PRImpactAnalysis]:
        """Analyze a PR and return impact analysis"""
        try:
            # Connect to GitHub
            if not self.github._client:
                self.github.connect()
            
            # Get PR details
            pr = self.github.get_pr(pr_number)
            if not pr:
                logger.error(f"Could not fetch PR #{pr_number}")
                return None
            
            # Get file contents
            files = self.github.get_pr_file_contents(pr)
            
            # Analyze impact
            impacted_features = self._analyze_impacted_features(pr)
            api_changes = self._analyze_api_changes(pr, files)
            class_impacts = self._analyze_class_impacts(pr, files)
            
            # Determine if there are critical changes
            critical_changes = (
                any(f.impact_level == "high" for f in impacted_features) or
                any(c.is_controller or c.is_kafka_related for c in class_impacts)
            )
            
            # Generate test recommendations
            test_recommendations = self._generate_test_recommendations(
                impacted_features, api_changes
            )
            
            # Generate summary
            summary = self._generate_summary(pr, impacted_features, api_changes)
            
            return PRImpactAnalysis(
                pr_number=pr.number,
                pr_title=pr.title,
                total_files_changed=len(pr.files_changed),
                impacted_features=impacted_features,
                api_changes=api_changes,
                class_impacts=class_impacts,
                critical_changes=critical_changes,
                test_recommendations=test_recommendations,
                summary=summary,
                raw_changes={
                    "additions": pr.additions,
                    "deletions": pr.deletions,
                    "files": [f.filename for f in pr.files_changed]
                }
            )
            
        except Exception as e:
            logger.error(f"Failed to analyze PR #{pr_number}: {e}")
            return None
    
    def _analyze_impacted_features(self, pr: PRDetails) -> List[ImpactedFeature]:
        """Identify features impacted by file changes"""
        impacted = []
        repo_config = self.mapping.get("repositories", {}).get(
            self.github.config.repo, {}
        )
        components = repo_config.get("components", {})
        file_patterns = self.mapping.get("file_patterns", {})
        
        # Group files by component
        component_files: Dict[str, List[str]] = {}
        
        for pr_file in pr.files_changed:
            filepath = pr_file.filename
            matched_component = None
            
            # Check against component paths
            for path_prefix, config in components.items():
                if filepath.startswith(path_prefix):
                    feature_name = config.get("feature", path_prefix)
                    if feature_name not in component_files:
                        component_files[feature_name] = {
                            "files": [],
                            "config": config
                        }
                    component_files[feature_name]["files"].append(filepath)
                    matched_component = True
                    break
            
            # If no component match, check file patterns
            if not matched_component:
                for pattern, config in file_patterns.items():
                    if self._match_pattern(filepath, pattern):
                        feature_name = config.get("feature_type", "Unknown")
                        if feature_name not in component_files:
                            component_files[feature_name] = {
                                "files": [],
                                "config": config
                            }
                        component_files[feature_name]["files"].append(filepath)
                        break
        
        # Create ImpactedFeature for each component
        for feature_name, data in component_files.items():
            config = data["config"]
            files = data["files"]
            
            # Determine impact level
            impact = config.get("impact", "medium")
            if config.get("critical", False):
                impact = "high"
            
            impacted.append(ImpactedFeature(
                feature_name=feature_name,
                description=config.get("description", ""),
                impact_level=impact,
                test_types=config.get("test_types", ["unit"]),
                files_affected=files,
                reason=f"{len(files)} file(s) modified in this component"
            ))
        
        return impacted
    
    def _analyze_class_impacts(
        self, 
        pr: PRDetails, 
        files: List
    ) -> List[ClassImpact]:
        """Analyze which classes changed and identify API/Kafka impacts"""
        class_impacts = []
        
        # Patterns to detect APIs and Kafka
        api_patterns = {
            # Spring Boot REST patterns
            r'@RestController': 'controller',
            r'@Controller': 'controller',
            r'@GetMapping\s*\(["\']?([^"\')\s]+)': 'GET',
            r'@PostMapping\s*\(["\']?([^"\')\s]+)': 'POST',
            r'@PutMapping\s*\(["\']?([^"\')\s]+)': 'PUT',
            r'@DeleteMapping\s*\(["\']?([^"\')\s]+)': 'DELETE',
            r'@PatchMapping\s*\(["\']?([^"\')\s]+)': 'PATCH',
            r'@RequestMapping\s*\([^)]*value\s*=\s*["\']([^"\']+)': 'REQUEST',
            r'@RequestMapping\s*\(["\']([^"\']+)': 'REQUEST',
            # Express.js patterns
            r'app\.(get|post|put|delete|patch)\s*\(["\']([^"\']+)': 'express',
            r'router\.(get|post|put|delete|patch)\s*\(["\']([^"\']+)': 'express',
        }
        
        kafka_patterns = {
            r'@KafkaListener\s*\([^)]*topics?\s*=\s*["\']?([^"\')\s,]+)': 'consumer',
            r'KafkaTemplate': 'producer',
            r'kafkaTemplate\.send\s*\(["\']([^"\']+)': 'producer',
            r'@SendTo\s*\(["\']([^"\']+)': 'producer',
            r'kafka\.producer': 'producer',
            r'kafka\.consumer': 'consumer',
            r'KafkaProducer': 'producer',
            r'KafkaConsumer': 'consumer',
        }
        
        for pr_file in pr.files_changed:
            # Skip non-code files
            if not any(pr_file.filename.endswith(ext) for ext in ['.java', '.kt', '.py', '.js', '.ts']):
                continue
            
            # Extract class name from filename
            class_name = Path(pr_file.filename).stem
            
            # Get file content from the files list
            file_content = ""
            for f in files:
                if f.path == pr_file.filename:
                    file_content = f.content
                    break
            
            # Also check the patch for changes
            patch_content = pr_file.patch or ""
            combined_content = file_content + "\n" + patch_content
            
            # Analyze for API endpoints
            api_endpoints = []
            is_controller = False
            
            for pattern, api_type in api_patterns.items():
                matches = re.finditer(pattern, combined_content, re.IGNORECASE)
                for match in matches:
                    if api_type == 'controller':
                        is_controller = True
                    elif api_type == 'express':
                        # Express.js style
                        http_method = match.group(1).upper()
                        path = match.group(2)
                        api_endpoints.append({
                            'http_method': http_method,
                            'path': path,
                            'method': 'route_handler'
                        })
                    else:
                        # Spring style
                        path = match.group(1) if match.groups() else ""
                        api_endpoints.append({
                            'http_method': api_type,
                            'path': path,
                            'method': self._extract_method_name(combined_content, match.start())
                        })
            
            # Analyze for Kafka
            kafka_impacts = []
            is_kafka_related = False
            
            for pattern, kafka_type in kafka_patterns.items():
                matches = re.finditer(pattern, combined_content, re.IGNORECASE)
                for match in matches:
                    is_kafka_related = True
                    topic = match.group(1) if match.groups() else "unknown"
                    kafka_impacts.append({
                        'type': kafka_type,
                        'topic': topic
                    })
            
            # Only add if there are impacts
            if api_endpoints or kafka_impacts or is_controller or is_kafka_related:
                # Check if it's a service class
                is_service = '@Service' in combined_content or 'Service' in class_name
                
                class_impacts.append(ClassImpact(
                    class_name=class_name,
                    file_path=pr_file.filename,
                    change_type=pr_file.status,
                    api_endpoints=api_endpoints,
                    kafka_impacts=kafka_impacts,
                    is_controller=is_controller,
                    is_service=is_service,
                    is_kafka_related=is_kafka_related
                ))
        
        return class_impacts
    
    def _extract_method_name(self, content: str, position: int) -> str:
        """Extract the method name following an annotation"""
        # Look for method definition after the annotation
        search_start = content[position:position+500]
        
        # Java/Kotlin method pattern
        method_match = re.search(r'(?:public|private|protected)?\s*\w+\s+(\w+)\s*\(', search_start)
        if method_match:
            return method_match.group(1)
        
        # Python def pattern
        def_match = re.search(r'def\s+(\w+)\s*\(', search_start)
        if def_match:
            return def_match.group(1)
        
        return "unknown"
    
    def _analyze_api_changes(
        self, 
        pr: PRDetails, 
        files: List
    ) -> List[APIChange]:
        """Identify API endpoint changes in the PR"""
        api_changes = []
        api_patterns = self.mapping.get("api_patterns", {})
        
        for pr_file in pr.files_changed:
            if not pr_file.patch:
                continue
            
            # Parse the diff to find API-related changes
            lines = pr_file.patch.split('\n')
            
            for i, line in enumerate(lines):
                # Check if line is an addition or modification
                if not line.startswith('+') or line.startswith('+++'):
                    continue
                
                # Check against API patterns
                for pattern, endpoint_type in api_patterns.items():
                    if pattern in line:
                        # Try to extract function name
                        func_name = self._extract_function_name(line, lines, i)
                        
                        api_changes.append(APIChange(
                            endpoint_type=endpoint_type,
                            file_path=pr_file.filename,
                            function_name=func_name,
                            change_type="added" if pr_file.status == "added" else "modified",
                            line_number=i
                        ))
        
        return api_changes
    
    def _extract_function_name(
        self, 
        line: str, 
        all_lines: List[str], 
        current_idx: int
    ) -> str:
        """Try to extract function/method name from code"""
        # Common patterns for function definitions
        patterns = [
            r'def\s+(\w+)',           # Python
            r'function\s+(\w+)',       # JavaScript
            r'async\s+(\w+)',          # Async functions
            r'(\w+)\s*[=:]\s*(?:async\s*)?\(',  # Arrow functions
            r'@\w+\([^)]*\)\s*\n\s*(?:async\s+)?(\w+)',  # Decorated functions
        ]
        
        # Check current line and nearby lines
        search_range = all_lines[max(0, current_idx-2):min(len(all_lines), current_idx+3)]
        search_text = '\n'.join(search_range)
        
        for pattern in patterns:
            match = re.search(pattern, search_text)
            if match:
                return match.group(1)
        
        return "unknown"
    
    def _match_pattern(self, filepath: str, pattern: str) -> bool:
        """Check if filepath matches a glob-like pattern"""
        if pattern.startswith('*'):
            return filepath.endswith(pattern[1:])
        return pattern in filepath
    
    def _generate_test_recommendations(
        self,
        features: List[ImpactedFeature],
        api_changes: List[APIChange]
    ) -> List[str]:
        """Generate test recommendations based on impact analysis"""
        recommendations = []
        
        # Based on impacted features
        test_types_needed = set()
        for feature in features:
            test_types_needed.update(feature.test_types)
            if feature.impact_level == "high":
                recommendations.append(
                    f"🔴 CRITICAL: {feature.feature_name} requires thorough testing"
                )
        
        # Based on API changes
        if api_changes:
            recommendations.append(
                f"🔵 API Testing: {len(api_changes)} API endpoint(s) were modified"
            )
            for api in api_changes:
                recommendations.append(
                    f"   - Test {api.endpoint_type}: {api.function_name} in {api.file_path}"
                )
        
        # General recommendations based on test types
        if "e2e" in test_types_needed:
            recommendations.append("🟢 Run end-to-end tests for affected user flows")
        if "integration" in test_types_needed:
            recommendations.append("🟡 Run integration tests for service interactions")
        if "api" in test_types_needed:
            recommendations.append("🔵 Run API tests for endpoint validation")
        if "ui" in test_types_needed:
            recommendations.append("🟣 Run UI tests for visual regression")
        
        return recommendations
    
    def _generate_summary(
        self,
        pr: PRDetails,
        features: List[ImpactedFeature],
        api_changes: List[APIChange]
    ) -> str:
        """Generate human-readable summary of impact"""
        high_impact = [f for f in features if f.impact_level == "high"]
        medium_impact = [f for f in features if f.impact_level == "medium"]
        
        summary_parts = [
            f"PR #{pr.number} modifies {len(pr.files_changed)} files "
            f"(+{pr.additions}/-{pr.deletions} lines).",
        ]
        
        if high_impact:
            summary_parts.append(
                f"⚠️ HIGH IMPACT: {len(high_impact)} critical component(s) affected: "
                f"{', '.join(f.feature_name for f in high_impact)}."
            )
        
        if medium_impact:
            summary_parts.append(
                f"📊 MEDIUM IMPACT: {len(medium_impact)} component(s) affected: "
                f"{', '.join(f.feature_name for f in medium_impact)}."
            )
        
        if api_changes:
            summary_parts.append(
                f"🔌 API CHANGES: {len(api_changes)} endpoint(s) modified."
            )
        
        return " ".join(summary_parts)


def format_impact_for_jira(analysis: PRImpactAnalysis) -> str:
    """Format impact analysis for Jira comment/description"""
    lines = [
        "h2. 🔍 PR Impact Analysis",
        "",
        f"*PR:* #{analysis.pr_number} - {analysis.pr_title}",
        f"*Files Changed:* {analysis.total_files_changed}",
        f"*Critical Changes:* {'⚠️ YES' if analysis.critical_changes else '✅ No'}",
        "",
        "h3. Summary",
        analysis.summary,
        "",
    ]
    
    # NEW: Class Impact with API/Kafka details
    if analysis.class_impacts:
        api_classes = [c for c in analysis.class_impacts if c.api_endpoints or c.is_controller]
        kafka_classes = [c for c in analysis.class_impacts if c.kafka_impacts or c.is_kafka_related]
        
        if api_classes:
            lines.extend([
                "h3. 🔌 API Endpoints Impacted",
                "||Class||HTTP Method||Endpoint Path||File||",
            ])
            for cls in api_classes:
                if cls.api_endpoints:
                    for api in cls.api_endpoints:
                        lines.append(
                            f"|{cls.class_name}|{api.get('http_method', 'N/A')}|"
                            f"{api.get('path', 'N/A')}|{cls.file_path}|"
                        )
                elif cls.is_controller:
                    lines.append(f"|{cls.class_name}|Controller|Check manually|{cls.file_path}|")
            lines.append("")
        
        if kafka_classes:
            lines.extend([
                "h3. 📨 Kafka Impacts",
                "||Class||Type||Topic||File||",
            ])
            for cls in kafka_classes:
                if cls.kafka_impacts:
                    for kafka in cls.kafka_impacts:
                        lines.append(
                            f"|{cls.class_name}|{kafka.get('type', 'N/A')}|"
                            f"{kafka.get('topic', 'N/A')}|{cls.file_path}|"
                        )
                elif cls.is_kafka_related:
                    lines.append(f"|{cls.class_name}|Kafka-related|Check manually|{cls.file_path}|")
            lines.append("")
    
    if analysis.impacted_features:
        lines.extend([
            "h3. Impacted Features",
            "||Feature||Impact||Files||Test Types||",
        ])
        for f in analysis.impacted_features:
            impact_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(f.impact_level, "⚪")
            lines.append(
                f"|{f.feature_name}|{impact_icon} {f.impact_level}|"
                f"{len(f.files_affected)}|{', '.join(f.test_types)}|"
            )
        lines.append("")
    
    if analysis.api_changes:
        lines.extend([
            "h3. API Changes (from diff)",
            "||Type||Function||File||",
        ])
        for api in analysis.api_changes:
            lines.append(f"|{api.endpoint_type}|{api.function_name}|{api.file_path}|")
        lines.append("")
    
    if analysis.test_recommendations:
        lines.extend([
            "h3. Test Recommendations",
        ])
        for rec in analysis.test_recommendations:
            lines.append(f"* {rec}")
        lines.append("")
    
    lines.append("_Generated by QA Agent_")
    
    return "\n".join(lines)


# Test the analyzer
if __name__ == "__main__":
    from rich.console import Console
    from rich.table import Table
    
    console = Console()
    analyzer = PRAnalyzer()
    
    # Test with a PR number (change this to test)
    pr_number = 1
    
    console.print(f"\n[bold]Analyzing PR #{pr_number}...[/bold]\n")
    
    analysis = analyzer.analyze_pr(pr_number)
    
    if analysis:
        console.print(f"[green]✅ Analysis complete![/green]\n")
        console.print(f"Summary: {analysis.summary}\n")
        
        if analysis.impacted_features:
            table = Table(title="Impacted Features")
            table.add_column("Feature")
            table.add_column("Impact")
            table.add_column("Files")
            
            for f in analysis.impacted_features:
                table.add_row(f.feature_name, f.impact_level, str(len(f.files_affected)))
            
            console.print(table)
        
        if analysis.test_recommendations:
            console.print("\n[bold]Test Recommendations:[/bold]")
            for rec in analysis.test_recommendations:
                console.print(f"  {rec}")
    else:
        console.print("[red]❌ Analysis failed[/red]")
