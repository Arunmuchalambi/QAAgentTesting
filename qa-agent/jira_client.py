"""
Jira Integration Client
Handles connection to Jira and fetching story/task details
"""

import re
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from jira import JIRA
from loguru import logger

from config import settings


@dataclass
class JiraIssue:
    """Represents a Jira issue/story/task"""
    key: str
    summary: str
    description: str
    issue_type: str
    status: str
    assignee: Optional[str]
    reporter: str
    labels: List[str]
    components: List[str]
    pr_links: List[str]
    acceptance_criteria: Optional[str]
    raw_data: Dict[str, Any]

    def get_github_pr_numbers(self) -> List[int]:
        """Extract PR numbers from the issue"""
        pr_numbers = []
        
        # Pattern to match GitHub PR URLs or references
        patterns = [
            r'github\.com/[\w-]+/[\w-]+/pull/(\d+)',  # Full URL
            r'#(\d+)',  # Simple reference
            r'PR[- ]?(\d+)',  # PR-123 or PR 123
        ]
        
        text_to_search = f"{self.description or ''} {' '.join(self.pr_links)}"
        
        for pattern in patterns:
            matches = re.findall(pattern, text_to_search, re.IGNORECASE)
            pr_numbers.extend([int(m) for m in matches])
        
        return list(set(pr_numbers))


class JiraClient:
    """Client for interacting with Jira API"""
    
    def __init__(self):
        self.config = settings.jira
        self._client: Optional[JIRA] = None
    
    def connect(self) -> bool:
        """Establish connection to Jira"""
        try:
            self._client = JIRA(
                server=self.config.server,
                basic_auth=(self.config.email, self.config.api_token)
            )
            # Test connection
            self._client.myself()
            logger.info(f"✅ Connected to Jira: {self.config.server}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to connect to Jira: {e}")
            return False
    
    @property
    def client(self) -> JIRA:
        """Get the Jira client, connecting if necessary"""
        if self._client is None:
            self.connect()
        return self._client
    
    def get_issue(self, issue_key: str) -> Optional[JiraIssue]:
        """Fetch a specific issue by key"""
        try:
            issue = self.client.issue(issue_key)
            return self._parse_issue(issue)
        except Exception as e:
            logger.error(f"Failed to fetch issue {issue_key}: {e}")
            return None
    
    def get_recent_issues(self, max_results: int = 10) -> List[JiraIssue]:
        """Get recently created issues from the project"""
        try:
            jql = f'project = {self.config.project_key} ORDER BY created DESC'
            issues = self.client.search_issues(jql, maxResults=max_results)
            return [self._parse_issue(issue) for issue in issues]
        except Exception as e:
            logger.error(f"Failed to fetch recent issues: {e}")
            return []
    
    def get_issues_with_prs(self, max_results: int = 10) -> List[JiraIssue]:
        """Get issues that likely have associated PRs"""
        try:
            # Search for issues with PR-related labels or in certain statuses
            jql = f'''
                project = {self.config.project_key} 
                AND (status = "In Review" OR status = "Code Review" OR labels = "has-pr")
                ORDER BY updated DESC
            '''
            issues = self.client.search_issues(jql, maxResults=max_results)
            return [self._parse_issue(issue) for issue in issues]
        except Exception as e:
            logger.error(f"Failed to fetch issues with PRs: {e}")
            return []
    
    def _parse_issue(self, issue) -> JiraIssue:
        """Parse Jira issue into our dataclass"""
        fields = issue.fields
        
        # Extract PR links from various fields
        pr_links = []
        
        # Check custom fields for GitHub links
        for field_name in dir(fields):
            if field_name.startswith('customfield_'):
                value = getattr(fields, field_name, None)
                if value and isinstance(value, str) and 'github.com' in value:
                    pr_links.append(value)
        
        # Check description for PR links
        description = fields.description or ""
        github_urls = re.findall(r'https://github\.com/[\w-]+/[\w-]+/pull/\d+', description)
        pr_links.extend(github_urls)
        
        # Extract acceptance criteria (often in description or custom field)
        acceptance_criteria = None
        if description:
            ac_match = re.search(
                r'(?:acceptance criteria|ac|given.*when.*then)[:]*\s*(.*?)(?=\n\n|\Z)',
                description,
                re.IGNORECASE | re.DOTALL
            )
            if ac_match:
                acceptance_criteria = ac_match.group(1).strip()
        
        return JiraIssue(
            key=issue.key,
            summary=fields.summary,
            description=description,
            issue_type=fields.issuetype.name,
            status=fields.status.name,
            assignee=fields.assignee.displayName if fields.assignee else None,
            reporter=fields.reporter.displayName if fields.reporter else "Unknown",
            labels=list(fields.labels) if fields.labels else [],
            components=[c.name for c in fields.components] if fields.components else [],
            pr_links=list(set(pr_links)),
            acceptance_criteria=acceptance_criteria,
            raw_data=issue.raw
        )
    
    def add_comment(self, issue_key: str, comment: str) -> bool:
        """Add a comment to an issue"""
        try:
            self.client.add_comment(issue_key, comment)
            logger.info(f"Added comment to {issue_key}")
            return True
        except Exception as e:
            logger.error(f"Failed to add comment to {issue_key}: {e}")
            return False
    
    def add_test_cases_comment(self, issue_key: str, test_cases: str) -> bool:
        """Add generated test cases as a formatted comment"""
        formatted_comment = f"""
🤖 *QA Agent - Auto-Generated Test Cases*

{test_cases}

---
_Generated automatically by QA Agent_
        """
        return self.add_comment(issue_key, formatted_comment)
    
    def create_subtask(
        self, 
        parent_key: str, 
        summary: str, 
        description: str
    ) -> Optional[str]:
        """Create a subtask under a parent issue
        
        Returns the created subtask key (e.g., 'DT-1850') or None if failed
        """
        try:
            # Get parent issue to extract project info
            parent = self.client.issue(parent_key)
            project_key = parent.fields.project.key
            
            # Get project-specific issue types
            project = self.client.project(project_key)
            subtask_type = None
            
            # Find the Sub-task issue type for this project
            for it in project.issueTypes:
                if it.subtask:
                    subtask_type = it
                    break
            
            if not subtask_type:
                logger.error(f"Could not find Sub-task issue type for project {project_key}")
                return None
            
            logger.info(f"Using subtask type: {subtask_type.name} (id={subtask_type.id})")
            
            # Create the subtask
            subtask_dict = {
                'project': {'key': project_key},
                'summary': summary,
                'description': description,
                'issuetype': {'id': subtask_type.id},
                'parent': {'key': parent_key}
            }
            
            new_issue = self.client.create_issue(fields=subtask_dict)
            logger.info(f"✅ Created subtask {new_issue.key} under {parent_key}")
            
            return new_issue.key
            
        except Exception as e:
            logger.error(f"Failed to create subtask under {parent_key}: {e}")
            return None
    
    def find_qa_agent_subtask(self, parent_key: str) -> Optional[str]:
        """Find existing QA Agent subtask under a parent issue
        
        Returns the subtask key or None if not found
        """
        try:
            # Search for subtasks with "QA Agent" in summary
            jql = f'parent = {parent_key} AND summary ~ "QA Agent"'
            issues = self.client.search_issues(jql, maxResults=1)
            
            if issues:
                subtask_key = issues[0].key
                logger.info(f"Found existing QA Agent subtask: {subtask_key}")
                return subtask_key
            
            return None
        except Exception as e:
            logger.error(f"Failed to find subtask for {parent_key}: {e}")
            return None
    
    def update_subtask_description(
        self, 
        subtask_key: str, 
        new_description: str
    ) -> bool:
        """Update the description of an existing subtask
        
        Args:
            subtask_key: Subtask issue key
            new_description: New description content
        """
        try:
            subtask = self.client.issue(subtask_key)
            subtask.update(description=new_description)
            logger.info(f"Updated description of {subtask_key}")
            return True
        except Exception as e:
            logger.error(f"Failed to update subtask description {subtask_key}: {e}")
            return False
    
    def append_to_subtask_description(
        self, 
        subtask_key: str, 
        additional_content: str
    ) -> bool:
        """Append content to existing subtask description
        
        Args:
            subtask_key: Subtask issue key
            additional_content: Content to append
        """
        try:
            subtask = self.client.issue(subtask_key)
            existing_description = subtask.fields.description or ""
            
            # Add separator and new content
            new_description = f"""{existing_description}

----

{additional_content}"""
            
            subtask.update(description=new_description)
            logger.info(f"Appended to description of {subtask_key}")
            return True
        except Exception as e:
            logger.error(f"Failed to append to subtask description {subtask_key}: {e}")
            return False
    
    def create_test_cases_subtask(self, parent_key: str, description: str) -> Optional[str]:
        """Create a subtask with test cases under a parent issue
        
        Returns the subtask key or None if failed
        """
        # Create with placeholder, then update with actual key
        temp_summary = f"QA Agent - Test Cases"
        
        subtask_key = self.create_subtask(
            parent_key=parent_key,
            summary=temp_summary,
            description=description
        )
        
        if subtask_key:
            # Update the summary with the actual subtask key
            try:
                final_summary = f"QA Agent - {subtask_key} - Test Cases"
                subtask = self.client.issue(subtask_key)
                subtask.update(summary=final_summary)
                logger.info(f"✅ Updated subtask summary to: {final_summary}")
            except Exception as e:
                logger.warning(f"Could not update subtask summary: {e}")
        
        return subtask_key
    
    def add_attachment(
        self, 
        issue_key: str, 
        file_path: str,
        filename: str = None
    ) -> bool:
        """Add an attachment to a Jira issue
        
        Args:
            issue_key: Jira issue key (e.g., 'DT-1234')
            file_path: Path to the file to attach
            filename: Optional custom filename for the attachment
        
        Returns:
            True if attachment was added successfully
        """
        try:
            import os
            
            if not os.path.exists(file_path):
                logger.error(f"Attachment file not found: {file_path}")
                return False
            
            # Use custom filename or extract from path
            if filename is None:
                filename = os.path.basename(file_path)
            
            # Add attachment to issue
            with open(file_path, 'rb') as f:
                self.client.add_attachment(
                    issue=issue_key,
                    attachment=f,
                    filename=filename
                )
            
            logger.info(f"✅ Added attachment '{filename}' to {issue_key}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to add attachment to {issue_key}: {e}")
            return False
    
    def add_test_report_attachment(
        self,
        issue_key: str,
        report_path: str,
        pr_number: int = None
    ) -> bool:
        """Add a test report as attachment with standardized naming
        
        Args:
            issue_key: Jira issue key
            report_path: Path to the HTML report file
            pr_number: PR number for naming
        
        Returns:
            True if attachment was added successfully
        """
        try:
            import os
            from datetime import datetime
            
            # Generate standardized filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            if pr_number:
                filename = f"Test_Case_Outcome_PR{pr_number}_{timestamp}.html"
            else:
                filename = f"Test_Case_Outcome_{timestamp}.html"
            
            return self.add_attachment(issue_key, report_path, filename)
            
        except Exception as e:
            logger.error(f"Failed to add test report to {issue_key}: {e}")
            return False


# Webhook payload parser
def parse_jira_webhook(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Parse incoming Jira webhook payload"""
    try:
        event_type = payload.get("webhookEvent", "")
        issue_data = payload.get("issue", {})
        
        if not issue_data:
            return None
        
        return {
            "event_type": event_type,
            "issue_key": issue_data.get("key"),
            "issue_id": issue_data.get("id"),
            "summary": issue_data.get("fields", {}).get("summary"),
            "issue_type": issue_data.get("fields", {}).get("issuetype", {}).get("name"),
            "project_key": issue_data.get("fields", {}).get("project", {}).get("key"),
            "raw": payload
        }
    except Exception as e:
        logger.error(f"Failed to parse Jira webhook: {e}")
        return None

