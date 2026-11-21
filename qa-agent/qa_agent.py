"""
QA Agent - Test Case Generator
Uses an OpenAI-compatible LLM (Gemini free tier by default, also Groq/OpenAI)
Enhanced with QA Platform Knowledge
"""

import json
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from openai import OpenAI
from loguru import logger

from config import settings
from jira_client import JiraIssue
from github_client import PRDetails, RepoFile
from product_knowledge import get_product_knowledge, ProductKnowledge


@dataclass
class TestCase:
    """Represents a generated test case"""
    id: str
    title: str
    description: str
    preconditions: List[str]
    steps: List[str]
    expected_results: List[str]
    test_type: str  # unit, integration, e2e, api
    priority: str  # high, medium, low
    tags: List[str]


@dataclass
class TestSuite:
    """Collection of test cases for a feature"""
    feature_name: str
    jira_key: Optional[str]
    pr_number: Optional[int]
    test_cases: List[TestCase]
    summary: str
    coverage_notes: str


SYSTEM_PROMPT = """You are an expert QA Engineer and Test Automation Specialist. Your role is to analyze code changes and generate comprehensive test cases.

## Your Expertise:
- Writing clear, actionable test cases
- Identifying edge cases and boundary conditions
- Understanding code logic and potential failure points
- Creating tests for unit, integration, and end-to-end scenarios

## Test Case Format:
For each test case, provide:
1. **ID**: Unique identifier (TC-001, TC-002, etc.)
2. **Title**: Clear, descriptive title
3. **Description**: What this test validates
4. **Preconditions**: Setup requirements
5. **Steps**: Numbered test steps
6. **Expected Results**: What should happen
7. **Type**: unit/integration/e2e/api
8. **Priority**: high/medium/low
9. **Tags**: Relevant categories

## Guidelines:
- Focus on the actual code changes, not hypothetical scenarios
- Include positive tests (happy path) AND negative tests (error handling)
- Consider boundary conditions and edge cases
- Think about security implications
- Consider performance aspects for critical paths
- Include data validation tests where applicable

## Output Format:
Return your response as a JSON object with this structure:
{
    "summary": "Brief overview of test coverage",
    "coverage_notes": "Any gaps or areas needing manual testing",
    "test_cases": [
        {
            "id": "TC-001",
            "title": "Test title",
            "description": "What this tests",
            "preconditions": ["precondition 1"],
            "steps": ["step 1", "step 2"],
            "expected_results": ["result 1"],
            "test_type": "unit",
            "priority": "high",
            "tags": ["tag1", "tag2"]
        }
    ]
}
"""


class QAAgent:
    """AI-powered QA Agent for generating test cases"""
    
    def __init__(self):
        self.config = settings.llm
        self._client: Optional[OpenAI] = None
        self.knowledge = get_product_knowledge()  # product knowledge base
    
    def connect(self) -> bool:
        """Initialize OpenAI-compatible LLM client (Gemini/Groq/OpenAI)"""
        try:
            api_key = self.config.resolved_api_key
            if not api_key:
                raise ValueError("Missing LLM API key for provider " + self.config.resolved_provider)

            kwargs = {"api_key": api_key}
            base_url = self.config.resolved_base_url
            if base_url:
                kwargs["base_url"] = base_url

            self._client = OpenAI(**kwargs)
            logger.info(
                f"✅ LLM client initialized "
                f"(provider={self.config.resolved_provider}, model={self.config.resolved_model})"
            )
            return True
        except Exception as e:
            logger.error(f"❌ Failed to initialize LLM client: {e}")
            return False
    
    @property
    def client(self) -> OpenAI:
        """Get the LLM client"""
        if self._client is None:
            self.connect()
        return self._client
    
    def generate_test_cases(
        self,
        jira_issue: Optional[JiraIssue] = None,
        pr_details: Optional[PRDetails] = None,
        files: Optional[List[RepoFile]] = None,
        pr_only: bool = False
    ) -> Optional[TestSuite]:
        """Generate test cases based on Jira issue, PR, and code files
        
        Args:
            jira_issue: Jira issue details
            pr_details: PR details
            files: Code files from PR
            pr_only: If True, generate test cases ONLY from PR code changes,
                    ignore Jira description (use for PR updates)
        """
        
        # Build the context for the AI
        context = self._build_context(jira_issue, pr_details, files, pr_only=pr_only)
        
        if not context:
            logger.error("No context provided for test generation")
            return None
        
        try:
            model = self.config.resolved_model
            
            request_params = {
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": context}
                ],
                "temperature": 0.3,
                "max_tokens": 4000,
            }
            
            # Only add response_format for models that support it
            if self.config.supports_json_mode:
                request_params["response_format"] = {"type": "json_object"}
            
            response = self.client.chat.completions.create(**request_params)
            
            result = response.choices[0].message.content
            return self._parse_response(result, jira_issue, pr_details)
            
        except Exception as e:
            logger.error(f"Failed to generate test cases: {e}")
            return None
    
    def _build_context(
        self,
        jira_issue: Optional[JiraIssue],
        pr_details: Optional[PRDetails],
        files: Optional[List[RepoFile]],
        pr_only: bool = False
    ) -> str:
        """Build context string for the AI
        
        Args:
            pr_only: If True, focus ONLY on PR code changes, skip Jira description
        """
        parts = []
        
        # Add Jira context ONLY if not pr_only mode
        if jira_issue and not pr_only:
            parts.append(f"""
## Jira Story/Task
- **Key**: {jira_issue.key}
- **Summary**: {jira_issue.summary}
- **Type**: {jira_issue.issue_type}
- **Description**: 
{jira_issue.description or 'No description provided'}

{"- **Acceptance Criteria**: " + jira_issue.acceptance_criteria if jira_issue.acceptance_criteria else ""}
""")
            
            # Add QA Platform Context
            product_context = self.knowledge.get_test_context_for_jira(
                jira_summary=jira_issue.summary,
                jira_description=jira_issue.description or "",
                components=jira_issue.components
            )
            
            if product_context.get("has_context"):
                parts.append(self.knowledge.format_context_for_prompt(product_context))
                logger.info(f"📚 Added product context: {product_context.get('context_summary')}")
        
        # For PR-only mode, add minimal Jira reference (just the key)
        elif jira_issue and pr_only:
            parts.append(f"""
## PR Analysis Mode (Focus on Code Changes Only)
- **Related Jira**: {jira_issue.key}
- **IMPORTANT**: Generate test cases ONLY based on the actual code changes below.
- Do NOT generate generic test cases from the Jira description.
- Focus strictly on what the code changes DO, not what the Jira SAYS.
""")
        
        # Add PR context
        if pr_details:
            files_summary = "\n".join([
                f"  - {f.filename} ({f.status}: +{f.additions}/-{f.deletions})"
                for f in pr_details.files_changed[:20]
            ])
            
            parts.append(f"""
## Pull Request Details
- **PR #{pr_details.number}**: {pr_details.title}
- **Branch**: {pr_details.branch} → {pr_details.base_branch}
- **Author**: {pr_details.author}
- **Changes**: +{pr_details.additions}/-{pr_details.deletions} across {len(pr_details.files_changed)} files

### Files Changed:
{files_summary}

### PR Description:
{pr_details.description or 'No description'}
""")
            
            # Add file patches (code diff)
            patches = []
            for f in pr_details.files_changed[:10]:
                if f.patch:
                    patches.append(f"### {f.filename}\n```diff\n{f.patch[:2000]}\n```")
            
            if patches:
                parts.append("## Code Changes (Diffs)\n" + "\n\n".join(patches))
        
        # Add full file contents
        if files:
            file_contents = []
            total_size = 0
            max_size = 30000  # Limit total content size
            
            for f in files:
                if total_size + len(f.content) > max_size:
                    break
                file_contents.append(f"### {f.path}\n```\n{f.content}\n```")
                total_size += len(f.content)
            
            if file_contents:
                parts.append("## Repository Files (Full Content)\n" + "\n\n".join(file_contents))
        
        # Final instruction
        parts.append("""
## Your Task
Based on the above information, generate comprehensive test cases that cover:
1. All functional requirements from the Jira story
2. All code changes in the PR
3. Edge cases and error scenarios
4. Integration points with other systems

Return your response as a valid JSON object.
""")
        
        return "\n".join(parts)
    
    def _parse_response(
        self,
        response: str,
        jira_issue: Optional[JiraIssue],
        pr_details: Optional[PRDetails]
    ) -> Optional[TestSuite]:
        """Parse AI response into TestSuite"""
        try:
            data = json.loads(response)
            
            test_cases = []
            for tc in data.get("test_cases", []):
                test_cases.append(TestCase(
                    id=tc.get("id", "TC-000"),
                    title=tc.get("title", "Untitled"),
                    description=tc.get("description", ""),
                    preconditions=tc.get("preconditions", []),
                    steps=tc.get("steps", []),
                    expected_results=tc.get("expected_results", []),
                    test_type=tc.get("test_type", "unit"),
                    priority=tc.get("priority", "medium"),
                    tags=tc.get("tags", [])
                ))
            
            feature_name = ""
            if jira_issue:
                feature_name = jira_issue.summary
            elif pr_details:
                feature_name = pr_details.title
            
            return TestSuite(
                feature_name=feature_name,
                jira_key=jira_issue.key if jira_issue else None,
                pr_number=pr_details.number if pr_details else None,
                test_cases=test_cases,
                summary=data.get("summary", ""),
                coverage_notes=data.get("coverage_notes", "")
            )
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response as JSON: {e}")
            return None
    
    def format_test_cases_markdown(self, test_suite: TestSuite) -> str:
        """Format test cases as Markdown for Jira/GitHub comments"""
        lines = [
            f"# Test Cases: {test_suite.feature_name}",
            "",
            f"**Summary:** {test_suite.summary}",
            "",
        ]
        
        if test_suite.jira_key:
            lines.append(f"**Jira:** {test_suite.jira_key}")
        if test_suite.pr_number:
            lines.append(f"**PR:** #{test_suite.pr_number}")
        
        lines.extend(["", "---", ""])
        
        for tc in test_suite.test_cases:
            lines.extend([
                f"## {tc.id}: {tc.title}",
                "",
                f"**Type:** {tc.test_type} | **Priority:** {tc.priority}",
                "",
                f"**Description:** {tc.description}",
                "",
                "### Preconditions",
                *[f"- {p}" for p in tc.preconditions],
                "",
                "### Test Steps",
                *[f"{i+1}. {step}" for i, step in enumerate(tc.steps)],
                "",
                "### Expected Results",
                *[f"- {r}" for r in tc.expected_results],
                "",
                f"**Tags:** {', '.join(tc.tags)}",
                "",
                "---",
                ""
            ])
        
        if test_suite.coverage_notes:
            lines.extend([
                "## Coverage Notes",
                test_suite.coverage_notes,
                ""
            ])
        
        return "\n".join(lines)
    
    def format_test_cases_code(self, test_suite: TestSuite, language: str = "python") -> str:
        """Generate test code skeletons"""
        if language == "python":
            return self._generate_python_tests(test_suite)
        elif language == "javascript":
            return self._generate_javascript_tests(test_suite)
        else:
            return self.format_test_cases_markdown(test_suite)
    
    def _generate_python_tests(self, test_suite: TestSuite) -> str:
        """Generate Python pytest test skeletons"""
        lines = [
            '"""',
            f"Auto-generated test cases for: {test_suite.feature_name}",
            f"Jira: {test_suite.jira_key or 'N/A'}",
            f"PR: #{test_suite.pr_number or 'N/A'}",
            '"""',
            "",
            "import pytest",
            "",
            ""
        ]
        
        for tc in test_suite.test_cases:
            # Convert title to function name
            func_name = tc.id.lower().replace("-", "_") + "_" + \
                        tc.title.lower().replace(" ", "_").replace("-", "_")[:50]
            func_name = ''.join(c for c in func_name if c.isalnum() or c == '_')
            
            tags = [f'@pytest.mark.{tag}' for tag in tc.tags if tag.isalnum()]
            
            lines.extend([
                f"# {tc.id}: {tc.title}",
                f"# Priority: {tc.priority}",
                *tags,
                f"def test_{func_name}():",
                f'    """',
                f"    {tc.description}",
                f"    ",
                f"    Preconditions:",
                *[f"    - {p}" for p in tc.preconditions],
                f"    ",
                f"    Steps:",
                *[f"    {i+1}. {s}" for i, s in enumerate(tc.steps)],
                f"    ",
                f"    Expected:",
                *[f"    - {r}" for r in tc.expected_results],
                f'    """',
                "    # TODO: Implement test",
                "    pass",
                "",
                ""
            ])
        
        return "\n".join(lines)
    
    def _generate_javascript_tests(self, test_suite: TestSuite) -> str:
        """Generate JavaScript Jest test skeletons"""
        lines = [
            "/**",
            f" * Auto-generated test cases for: {test_suite.feature_name}",
            f" * Jira: {test_suite.jira_key or 'N/A'}",
            f" * PR: #{test_suite.pr_number or 'N/A'}",
            " */",
            "",
            f"describe('{test_suite.feature_name}', () => {{",
            ""
        ]
        
        for tc in test_suite.test_cases:
            steps_comment = "\n".join([f"     *   {i+1}. {s}" for i, s in enumerate(tc.steps)])
            expected_comment = "\n".join([f"     *   - {r}" for r in tc.expected_results])
            
            lines.extend([
                f"  // {tc.id} - Priority: {tc.priority}",
                f"  it('{tc.title}', () => {{",
                f"    /**",
                f"     * {tc.description}",
                f"     * ",
                f"     * Steps:",
                f"{steps_comment}",
                f"     * ",
                f"     * Expected:",
                f"{expected_comment}",
                f"     */",
                f"    // TODO: Implement test",
                f"    expect(true).toBe(true);",
                f"  }});",
                ""
            ])
        
        lines.append("});")
        
        return "\n".join(lines)

