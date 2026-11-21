#!/usr/bin/env python3
"""
Enhanced QA Agent - Handles both Jira issues AND PR changes
Generates comprehensive test cases with impact analysis

Flow:
1. Jira Created → Generate basic test cases from description
2. PR Linked/Created → Analyze code changes → Enhanced test cases with impact analysis
"""

import time
import sys
import queue
import threading
import re
from datetime import datetime
from typing import Set, Optional, List, Tuple, Dict
from dataclasses import dataclass
from loguru import logger
from rich.console import Console
from rich.panel import Panel

from config import settings
from jira_client import JiraClient, JiraIssue
from github_client import GitHubClient
from main import QAAgentOrchestrator
from qa_agent import QAAgent, TestSuite
from pr_analyzer import PRAnalyzer, PRImpactAnalysis, format_impact_for_jira
from sheets_client import add_test_cases_to_sheet, get_sheets_client
from pipeline_trigger import get_pipeline_trigger, PipelineTrigger
from test_execution_service import TestExecutionService, TestExecutionConfig, TestExecutionResult
from slack_notifier import get_slack_notifier, SlackNotifier
from report_server import get_report_server, start_report_server

# Configure logging
logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | {message}")

console = Console()


@dataclass 
class ProcessingResult:
    """Result of processing a Jira issue"""
    issue_key: str
    test_suite: Optional[TestSuite]
    pr_analysis: Optional[PRImpactAnalysis]
    subtask_key: Optional[str]
    success: bool
    error: Optional[str] = None


def format_enhanced_test_cases_for_jira(
    test_suite: TestSuite,
    pr_analysis: Optional[PRImpactAnalysis],
    parent_key: str
) -> str:
    """Format test cases with PR impact analysis for Jira"""
    
    lines = [
        "h2. 🤖 QA Agent - Enhanced Test Cases",
        "",
        f"*Parent Issue:* {parent_key}",
        f"*Feature:* {test_suite.feature_name}",
        f"*Total Test Cases:* {len(test_suite.test_cases)}",
    ]
    
    # Add PR impact analysis if available
    if pr_analysis:
        lines.extend([
            "",
            "h3. 🔍 PR Impact Analysis",
            f"*PR:* #{pr_analysis.pr_number} - {pr_analysis.pr_title}",
            f"*Files Changed:* {pr_analysis.total_files_changed}",
            f"*Critical Changes:* {'⚠️ YES - Requires thorough testing!' if pr_analysis.critical_changes else '✅ No'}",
            "",
            f"*Summary:* {pr_analysis.summary}",
            "",
        ])
        
        if pr_analysis.impacted_features:
            lines.extend([
                "h4. Impacted Features (Must Test)",
                "||Feature||Impact Level||Files Affected||Required Tests||",
            ])
            for f in pr_analysis.impacted_features:
                impact_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(f.impact_level, "⚪")
                lines.append(
                    f"|{f.feature_name}|{impact_icon} {f.impact_level.upper()}|"
                    f"{len(f.files_affected)}|{', '.join(f.test_types)}|"
                )
            lines.append("")
        
        if pr_analysis.api_changes:
            lines.extend([
                "h4. API Endpoints Modified",
                "||Type||Function||File||",
            ])
            for api in pr_analysis.api_changes:
                lines.append(f"|{api.endpoint_type}|{api.function_name}|{api.file_path}|")
            lines.append("")
        
        if pr_analysis.test_recommendations:
            lines.extend([
                "h4. 🎯 Test Recommendations",
            ])
            for rec in pr_analysis.test_recommendations:
                lines.append(f"* {rec}")
            lines.append("")
    
    # Count critical tests
    high_priority_count = sum(1 for tc in test_suite.test_cases if tc.priority.lower() in ['high', 'critical'])
    
    # Test Cases - Full Table with all details
    lines.extend([
        "h3. 📋 Test Cases",
        "",
        f"*Summary:* {test_suite.summary}",
    ])
    
    # Add legend for highlighting
    if high_priority_count > 0:
        lines.extend([
            "",
            "{panel:bgColor=#ffebee}",
            f"⚠️ *CRITICAL/HIGH PRIORITY:* {high_priority_count} test case(s) marked in {{color:red}}*RED*{{color}} require immediate attention!",
            "{panel}",
        ])
    
    lines.extend([
        "",
        "||ID||Title||Type||Priority||Description||Preconditions||Test Steps||Expected Results||",
    ])
    
    for tc in test_suite.test_cases:
        # Format preconditions as bullet list
        preconditions_str = " ".join([f"• {p}" for p in tc.preconditions]) if tc.preconditions else "N/A"
        
        # Format steps as numbered list
        steps_str = " ".join([f"{i+1}. {s}" for i, s in enumerate(tc.steps)]) if tc.steps else "N/A"
        
        # Format expected results as bullet list
        expected_str = " ".join([f"• {r}" for r in tc.expected_results]) if tc.expected_results else "N/A"
        
        # Highlight HIGH/CRITICAL priority rows in RED
        is_critical = tc.priority.lower() in ['high', 'critical']
        
        if is_critical:
            # Use Jira color markup for red highlighting on key columns
            tc_id = f"{{color:red}}*{tc.id}*{{color}}"
            tc_title = f"{{color:red}}*{tc.title}*{{color}}"
            tc_priority = f"{{color:red}}*🔴 {tc.priority.upper()}*{{color}}"
            tc_desc = f"{{color:red}}{tc.description}{{color}}"
        else:
            tc_id = tc.id
            tc_title = tc.title
            tc_priority = f"🟢 {tc.priority}" if tc.priority.lower() == 'low' else f"🟡 {tc.priority}"
            tc_desc = tc.description
        
        lines.append(
            f"|{tc_id}|{tc_title}|{tc.test_type}|{tc_priority}|{tc_desc}|{preconditions_str}|{steps_str}|{expected_str}|"
        )
    
    lines.append("")
    
    if test_suite.coverage_notes:
        lines.extend([
            "h3. Coverage Notes",
            test_suite.coverage_notes,
            ""
        ])
    
    lines.append("_Generated automatically by QA Agent_")
    
    return "\n".join(lines)


class EnhancedQAAgent:
    """Enhanced QA Agent with PR analysis capabilities"""
    
    # File to persist processed PRs (prevent duplicates across restarts)
    PROCESSED_PRS_FILE = "processed_prs_tracking.json"
    
    def __init__(self, poll_interval: int = 30):
        self.poll_interval = poll_interval
        self.jira = JiraClient()
        self.github = GitHubClient()
        self.orchestrator = QAAgentOrchestrator()
        self.pr_analyzer = PRAnalyzer()
        self.qa_agent = QAAgent()
        
        self.processed_issues: Set[str] = set()
        self.processed_prs: Dict[str, Set[int]] = {}  # issue_key -> set of PR numbers
        self.issue_queue = queue.Queue()
        self.processing_thread = None
        self.pr_check_thread = None
        
        # Load previously processed PRs from file (prevents duplicates)
        self._load_processed_prs()
        
        self.stats = {
            "issues_detected": 0,
            "issues_processed": 0,
            "tests_generated": 0,
            "subtasks_created": 0,
            "prs_analyzed": 0,
            "pr_updates": 0,
            "sheets_rows": 0,
            "test_executions": 0,
            "test_reports_attached": 0,
            "errors": 0,
            "last_check": None,
            "last_issue": None
        }
        
        # Initialize Google Sheets connection
        self.sheets_client = get_sheets_client()
        if self.sheets_client.is_connected():
            logger.info("📊 Google Sheets connected")
        
        # Initialize Test Execution Service
        self.test_executor = TestExecutionService(TestExecutionConfig(
            output_dir="test_reports",
            attach_to_jira=True,
            dry_run=True,  # Set to False to actually execute APIs
            max_tests=20
        ))
        logger.info("🧪 Test Execution Service initialized")
        
        # Initialize Slack Notifier
        self.slack = get_slack_notifier()
        if self.slack.is_enabled():
            logger.info("🔔 Slack notifications enabled")
        else:
            logger.info("🔕 Slack notifications disabled")
        
        # Initialize Report Server
        self.report_server = get_report_server()
        self.report_server_url = None
    
    def _load_processed_prs(self):
        """Load previously processed PRs from file to prevent duplicates"""
        try:
            import json
            import os
            filepath = os.path.join(os.path.dirname(__file__), self.PROCESSED_PRS_FILE)
            if os.path.exists(filepath):
                with open(filepath) as f:
                    data = json.load(f)
                    for jira_key, pr_list in data.items():
                        self.processed_prs[jira_key] = set(pr_list)
                logger.info(f"Loaded {len(self.processed_prs)} Jira issues with processed PRs")
        except Exception as e:
            logger.warning(f"Could not load processed PRs: {e}")
    
    def _save_processed_prs(self):
        """Save processed PRs to file"""
        try:
            import json
            import os
            filepath = os.path.join(os.path.dirname(__file__), self.PROCESSED_PRS_FILE)
            data = {k: list(v) for k, v in self.processed_prs.items()}
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Could not save processed PRs: {e}")
    
    def _is_pr_already_processed(self, jira_key: str, pr_number: int) -> bool:
        """Check if a PR has already been processed for a Jira issue"""
        return pr_number in self.processed_prs.get(jira_key, set())
    
    def _mark_pr_processed(self, jira_key: str, pr_number: int):
        """Mark a PR as processed for a Jira issue"""
        if jira_key not in self.processed_prs:
            self.processed_prs[jira_key] = set()
        self.processed_prs[jira_key].add(pr_number)
        self._save_processed_prs()
    
    def start(self):
        """Start the enhanced agent"""
        console.print(Panel.fit(
            "[bold blue]🤖 QA AGENT - ENHANCED MODE[/bold blue]\n"
            "[dim]Jira + PR Analysis + Impact Detection[/dim]",
            border_style="blue"
        ))
        
        console.print("\n[bold]🔌 Connecting to services...[/bold]\n")
        
        if not self.orchestrator.connect_all():
            console.print("[red]❌ Failed to connect. Check credentials.[/red]")
            return
        
        self.jira.connect()
        self.qa_agent.connect()
        
        # Start Report Server for direct viewing
        try:
            self.report_server_url = start_report_server(port=8080)
            report_server_status = f"[green]✅ {self.report_server_url}[/green]"
        except Exception as e:
            logger.warning(f"Could not start report server: {e}")
            report_server_status = "[yellow]⚠️ Not running[/yellow]"
            self.report_server_url = None
        
        # Show Google Sheets status
        sheets_status = "[green]✅ Connected[/green]" if self.sheets_client.is_connected() else "[yellow]⚠️ Not connected[/yellow]"
        slack_status = "[green]✅ Enabled[/green]" if self.slack.is_enabled() else "[yellow]⚠️ Disabled[/yellow]"
        
        console.print(f"""
[green]✅ Enhanced Agent is running![/green]

[bold]Features:[/bold]
  • 📋 Auto-detect new Jira issues
  • 🔍 Analyze linked PRs for code impact
  • 🎯 Identify impacted features & APIs
  • 📝 Generate enhanced test cases
  • 🔗 Create subtasks with full analysis
  • 📊 Sync test cases to Google Sheets
  • 🧪 Execute API tests & generate HTML reports
  • 📎 Attach test outcome reports to Jira
  • 🔔 Slack notifications for test results

[bold]Configuration:[/bold]
  • Project: [cyan]{settings.jira.project_key}[/cyan]
  • Poll interval: [cyan]{self.poll_interval} seconds[/cyan]
  • Component mapping: [cyan]component_mapping.json[/cyan]
  • Google Sheets: {sheets_status}
  • Slack Notifications: {slack_status}
  • Report Viewer: {report_server_status}

[bold yellow]🔍 Watching for NEW Jira issues...[/bold yellow]

Press Ctrl+C to stop.
""")
        
        # Start processing thread
        self.processing_thread = threading.Thread(target=self._process_queue, daemon=True)
        self.processing_thread.start()
        
        # Re-enabled PR checking - now only checks main repo (not all 200)
        self.pr_check_thread = threading.Thread(target=self._check_for_new_prs_loop, daemon=True)
        self.pr_check_thread.start()
        
        console.print("[dim]PR checking enabled for QAAgentTesting repo[/dim]")

        # Process recent backlog once at startup (not only issues created in last 5m)
        self._seed_recent_unprocessed_issues()
        
        # Main polling loop
        try:
            while True:
                self._check_for_new_issues()
                self._show_status()
                time.sleep(self.poll_interval)
        except KeyboardInterrupt:
            console.print("\n\n[yellow]👋 Stopping agent...[/yellow]")
            self._show_summary()

    def _enqueue_issue(self, issue_key: str, summary: str, reason: str = "NEW ISSUE"):
        """Add an issue to the processing queue if not already seen this session."""
        if issue_key in self.processed_issues:
            return False
        self.processed_issues.add(issue_key)
        self.stats["issues_detected"] += 1
        self.issue_queue.put({
            "key": issue_key,
            "summary": summary
        })
        console.print(f"\n[bold green]🆕 {reason} DETECTED![/bold green]")
        console.print(f"   [cyan]{issue_key}[/cyan]: {summary}")
        console.print(f"   [dim]Added to queue ({self.issue_queue.qsize()} pending)[/dim]\n")
        return True

    def _seed_recent_unprocessed_issues(self):
        """Queue recent parent issues that do not yet have a QA Agent subtask."""
        try:
            jql = f'''
                project = {settings.jira.project_key}
                AND created >= -30d
                AND issuetype != Sub-task
                ORDER BY created DESC
            '''
            issues = self.jira.search_issues(jql, max_results=20)
            console.print(f"[dim]Startup scan: {len(issues)} recent parent issue(s) in {settings.jira.project_key}[/dim]")
            for issue in issues:
                existing = self.jira.find_qa_agent_subtask(issue.key)
                if existing:
                    self.processed_issues.add(issue.key)
                    console.print(f"[dim]   skip {issue.key} (already has {existing})[/dim]")
                    continue
                self._enqueue_issue(issue.key, issue.fields.summary, reason="BACKLOG ISSUE")
        except Exception as e:
            logger.error(f"Error seeding recent issues: {e}")
    
    def _check_for_new_issues(self):
        """Check for newly created issues"""
        self.stats["last_check"] = datetime.now().strftime("%H:%M:%S")
        
        try:
            # Query for issues created in last 5 minutes
            jql = f'''
                project = {settings.jira.project_key} 
                AND created >= -5m
                ORDER BY created ASC
            '''
            
            issues = self.jira.search_issues(jql, max_results=50)
            
            for issue in issues:
                self._enqueue_issue(issue.key, issue.fields.summary, reason="NEW ISSUE")
                    
        except Exception as e:
            logger.error(f"Error checking for new issues: {e}")
    
    def _process_queue(self):
        """Background thread to process issues"""
        while True:
            try:
                issue_data = self.issue_queue.get(timeout=1)
                issue_key = issue_data["key"]
                is_pr_update = issue_data.get("is_pr_update", False)
                
                if is_pr_update:
                    console.print(f"[magenta]🔄 Re-processing {issue_key} (New PR detected)...[/magenta]")
                else:
                    console.print(f"[yellow]🤖 Processing {issue_key}...[/yellow]")
                
                result = self._process_issue_with_pr(issue_key, is_pr_update=is_pr_update)
                
                if result.success:
                    if is_pr_update:
                        self.stats["pr_updates"] += 1
                    else:
                        self.stats["issues_processed"] += 1
                    
                    if result.test_suite:
                        self.stats["tests_generated"] += len(result.test_suite.test_cases)
                    if result.subtask_key:
                        self.stats["subtasks_created"] += 1
                    if result.pr_analysis:
                        self.stats["prs_analyzed"] += 1
                    
                    # Track processed PRs for this issue (in memory and persisted)
                    if issue_key not in self.processed_prs:
                        self.processed_prs[issue_key] = set()
                    if result.pr_analysis:
                        self.processed_prs[issue_key].add(result.pr_analysis.pr_number)
                        # Persist to file to prevent duplicates across restarts
                        self._mark_pr_processed(issue_key, result.pr_analysis.pr_number)
                else:
                    self.stats["errors"] += 1
                
                self.issue_queue.task_done()
                time.sleep(2)
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error in processing: {e}")
                self.stats["errors"] += 1
    
    def _process_issue_with_pr(self, issue_key: str, is_pr_update: bool = False) -> ProcessingResult:
        """Process issue with PR analysis if available
        
        Args:
            issue_key: Jira issue key
            is_pr_update: If True, this is a re-processing due to new PR
        """
        try:
            # 1. Fetch Jira issue
            jira_issue = self.jira.get_issue(issue_key)
            if not jira_issue:
                return ProcessingResult(
                    issue_key=issue_key,
                    test_suite=None,
                    pr_analysis=None,
                    subtask_key=None,
                    success=False,
                    error="Could not fetch Jira issue"
                )
            
            console.print(f"   📋 Issue: {jira_issue.summary[:50]}...")
            
            # 2. Find linked PRs
            pr_numbers = self._find_linked_prs(jira_issue)
            pr_analysis = None
            pr_details = None
            files = []
            
            if pr_numbers:
                console.print(f"   🔗 Found {len(pr_numbers)} linked PR(s): {pr_numbers}")
                
                # Analyze the first/main PR
                pr_num = pr_numbers[0]
                console.print(f"   🔍 Analyzing PR #{pr_num}...")
                
                pr_analysis = self.pr_analyzer.analyze_pr(pr_num)
                pr_details = self.github.get_pr(pr_num)
                
                if pr_details:
                    files = self.github.get_pr_file_contents(pr_details)
                    console.print(f"   📂 Read {len(files)} file(s) from PR")
                
                if pr_analysis:
                    console.print(f"   ✅ Impact analysis complete")
                    if pr_analysis.critical_changes:
                        console.print(f"   [red]⚠️ CRITICAL CHANGES DETECTED![/red]")
            else:
                console.print(f"   [dim]No linked PRs found[/dim]")
            
            # 3. Generate test cases
            # If PR is detected, generate test cases ONLY from PR code changes (pr_only=True)
            # If no PR, generate from Jira description
            has_pr = pr_details is not None and len(files) > 0
            
            if has_pr:
                console.print(f"   🤖 Generating test cases from PR code changes ONLY...")
            else:
                console.print(f"   🤖 Generating test cases from Jira description...")
            
            test_suite = self.qa_agent.generate_test_cases(
                jira_issue=jira_issue,
                pr_details=pr_details,
                files=files,
                pr_only=has_pr  # Focus only on PR changes when PR is detected
            )
            
            if not test_suite:
                return ProcessingResult(
                    issue_key=issue_key,
                    test_suite=None,
                    pr_analysis=pr_analysis,
                    subtask_key=None,
                    success=False,
                    error="Could not generate test cases"
                )
            
            console.print(f"   [green]✅ Generated {len(test_suite.test_cases)} test cases[/green]")
            
            # 4. Save to files
            self._save_test_suite(test_suite, issue_key)
            
            # 5. Create subtask or add comment (for PR updates)
            description = format_enhanced_test_cases_for_jira(
                test_suite, pr_analysis, issue_key
            )
            
            subtask_key = None
            
            if is_pr_update:
                # For PR updates, find existing subtask and UPDATE ITS DESCRIPTION
                console.print(f"   🔍 Finding existing subtask...")
                
                existing_subtask = self.jira.find_qa_agent_subtask(issue_key)
                
                if existing_subtask:
                    console.print(f"   📝 Updating subtask {existing_subtask} description with PR details...")
                    
                    # Get PR URL
                    pr_url = f"https://github.com/{settings.github.repo}/pull/{pr_analysis.pr_number}" if pr_analysis else ""
                    pr_title = pr_analysis.pr_title if pr_analysis else "Unknown"
                    pr_num = pr_analysis.pr_number if pr_analysis else 0
                    
                    # Build PR update section to append to description
                    pr_update_section = f"""
h2. 🔄 PR Update - #{pr_num}

*PR:* [#{pr_num} - {pr_title}|{pr_url}]
*Updated:* {datetime.now().strftime("%Y-%m-%d %H:%M")}

h3. 📝 What Changed in This PR
"""
                    # List files changed
                    if pr_details:
                        pr_update_section += f"*Files Changed:* {len(pr_details.files_changed)}\n"
                        for f in pr_details.files_changed[:10]:
                            pr_update_section += f"• {f.filename} ({f.status})\n"
                        if len(pr_details.files_changed) > 10:
                            pr_update_section += f"• ... and {len(pr_details.files_changed) - 10} more files\n"
                        pr_update_section += "\n"
                    
                    if pr_analysis and pr_analysis.critical_changes:
                        pr_update_section += "\n⚠️ *CRITICAL CHANGES DETECTED* - Thorough testing required!\n"
                    
                    # Add API Impacts section
                    if pr_analysis and pr_analysis.class_impacts:
                        api_classes = [c for c in pr_analysis.class_impacts if c.api_endpoints or c.is_controller]
                        kafka_classes = [c for c in pr_analysis.class_impacts if c.kafka_impacts or c.is_kafka_related]
                        
                        if api_classes:
                            pr_update_section += "\nh3. 🔌 API Endpoints Impacted\n"
                            pr_update_section += "||Class||HTTP Method||Endpoint Path||File||\n"
                            for cls in api_classes:
                                if cls.api_endpoints:
                                    for api in cls.api_endpoints:
                                        pr_update_section += f"|{cls.class_name}|{api.get('http_method', 'N/A')}|{api.get('path', 'N/A')}|{cls.file_path}|\n"
                                elif cls.is_controller:
                                    pr_update_section += f"|{cls.class_name}|Controller|Check manually|{cls.file_path}|\n"
                            pr_update_section += "\n"
                        
                        if kafka_classes:
                            pr_update_section += "\nh3. 📨 Kafka Impacts\n"
                            pr_update_section += "||Class||Type||Topic||File||\n"
                            for cls in kafka_classes:
                                if cls.kafka_impacts:
                                    for kafka in cls.kafka_impacts:
                                        pr_update_section += f"|{cls.class_name}|{kafka.get('type', 'N/A')}|{kafka.get('topic', 'N/A')}|{cls.file_path}|\n"
                                elif cls.is_kafka_related:
                                    pr_update_section += f"|{cls.class_name}|Kafka-related|Check manually|{cls.file_path}|\n"
                            pr_update_section += "\n"
                    
                    if pr_analysis and pr_analysis.impacted_features:
                        pr_update_section += "\n*Impacted Features:*\n"
                        for f in pr_analysis.impacted_features:
                            pr_update_section += f"• {f.feature_name}\n"
                    
                    # PR-SPECIFIC Test Cases (only for this PR's changes)
                    pr_update_section += f"\nh3. 🎯 Test Cases for THIS PR (Verify These)\n"
                    pr_update_section += "_These test cases are specifically generated based on the code changes in this PR._\n\n"
                    pr_update_section += "||ID||Title||Type||Priority||Description||Preconditions||Test Steps||Expected Results||\n"
                    
                    for tc in test_suite.test_cases:
                        # Format for table
                        preconditions_str = " ".join([f"• {p}" for p in tc.preconditions]) if tc.preconditions else "N/A"
                        steps_str = " ".join([f"{i+1}. {s}" for i, s in enumerate(tc.steps)]) if tc.steps else "N/A"
                        expected_str = " ".join([f"• {r}" for r in tc.expected_results]) if tc.expected_results else "N/A"
                        pr_update_section += f"|{tc.id}|{tc.title}|{tc.test_type}|{tc.priority}|{tc.description}|{preconditions_str}|{steps_str}|{expected_str}|\n"
                    
                    pr_update_section += "\n_Updated automatically by QA Agent_"
                    
                    # Append to existing subtask description
                    self.jira.append_to_subtask_description(existing_subtask, pr_update_section)
                    
                    # Also add brief comment to parent issue with PR link
                    parent_comment = f"🔄 *PR Update:* [#{pr_num} - {pr_title}|{pr_url}] linked.\nSubtask [{existing_subtask}] description updated with new test analysis."
                    self.jira.add_comment(issue_key, parent_comment)
                    
                    console.print(f"   [green]✅ Updated subtask {existing_subtask} description[/green]")
                    self.stats["last_issue"] = f"{issue_key} → {existing_subtask} (PR update)"
                    subtask_key = existing_subtask
                else:
                    # No existing subtask found, create one
                    console.print(f"   [yellow]⚠️ No existing subtask found, creating new one...[/yellow]")
                    subtask_key = self.jira.create_test_cases_subtask(
                        parent_key=issue_key,
                        description=description
                    )
                    if subtask_key:
                        console.print(f"   [green]✅ Created subtask {subtask_key}[/green]")
                        self.stats["last_issue"] = f"{issue_key} → {subtask_key}"
                
                # Add to Google Sheets (will append to existing Jira section)
                self._add_to_google_sheets(
                    issue_key=issue_key,
                    issue_summary=jira_issue.summary,
                    subtask_key=subtask_key or existing_subtask,
                    test_suite=test_suite,
                    pr_analysis=pr_analysis,
                    is_pr_update=True
                )
                
                # 🧪 Execute tests and attach HTML report
                if pr_analysis and pr_analysis.pr_number:
                    # Get file changes with patches for code analysis
                    files_with_patches = []
                    if pr_details and pr_details.files_changed:
                        for f in pr_details.files_changed:
                            files_with_patches.append({
                                'filename': f.filename,
                                'patch': getattr(f, 'patch', ''),
                                'additions': getattr(f, 'additions', 0),
                                'deletions': getattr(f, 'deletions', 0),
                                'status': getattr(f, 'status', 'modified')
                            })
                    
                    self._execute_and_attach_test_report(
                        jira_key=issue_key,
                        pr_number=pr_analysis.pr_number,
                        pr_analysis=pr_analysis,
                        subtask_key=subtask_key or existing_subtask,
                        pr_files=[f.filename for f in (pr_details.files_changed if pr_details else [])],
                        jira_summary=jira_issue.summary,
                        jira_description=jira_issue.description or "",
                        pr_title=pr_analysis.pr_title,
                        pr_body=getattr(pr_details, 'body', '') if pr_details else "",
                        files_changed=files_with_patches
                    )
                
            else:
                # First time processing - create subtask
                console.print(f"   📝 Creating subtask in Jira...")
                
                subtask_key = self.jira.create_test_cases_subtask(
                    parent_key=issue_key,
                    description=description
                )
                
                if subtask_key:
                    # Add comment to parent with PR link if available
                    comment_parts = [f"🤖 *QA Agent* has generated test cases."]
                    comment_parts.append(f"\nSee subtask: [{subtask_key}]")
                    
                    if pr_analysis:
                        pr_url = f"https://github.com/{settings.github.repo}/pull/{pr_analysis.pr_number}"
                        comment_parts.append(f"\n\n*PR:* [#{pr_analysis.pr_number} - {pr_analysis.pr_title}|{pr_url}]")
                        if pr_analysis.critical_changes:
                            comment_parts.append("\n⚠️ *CRITICAL CHANGES DETECTED* - Thorough testing required!")
                        if pr_analysis.impacted_features:
                            comment_parts.append(f"\n*Impacted Features:* {', '.join([f.feature_name for f in pr_analysis.impacted_features])}")
                    
                    self.jira.add_comment(issue_key, "".join(comment_parts))
                    
                    console.print(f"   [green]✅ Created subtask {subtask_key}[/green]")
                    self.stats["last_issue"] = f"{issue_key} → {subtask_key}"
                    
                    # Slack notification for new Jira disabled - only notify on PR test results
                    # if self.slack.is_enabled():
                    #     self.slack.send_initial_jira_message(...)
                    pass
                    
                    # Add to Google Sheets
                    self._add_to_google_sheets(
                        issue_key=issue_key,
                        issue_summary=jira_issue.summary,
                        subtask_key=subtask_key,
                        test_suite=test_suite,
                        pr_analysis=pr_analysis,
                        is_pr_update=False
                    )
                    
                    # 6. Trigger pipelines based on Jira type (Salesforce vs SDLC)
                    self._trigger_pipelines(jira_issue, subtask_key)
            
            console.print("")
            
            return ProcessingResult(
                issue_key=issue_key,
                test_suite=test_suite,
                pr_analysis=pr_analysis,
                subtask_key=subtask_key,
                success=True
            )
            
        except Exception as e:
            logger.error(f"Failed to process {issue_key}: {e}")
            return ProcessingResult(
                issue_key=issue_key,
                test_suite=None,
                pr_analysis=None,
                subtask_key=None,
                success=False,
                error=str(e)
            )
    
    def _find_linked_prs(self, issue: JiraIssue) -> List[int]:
        """Find PR numbers linked to a Jira issue"""
        pr_numbers = []
        
        # 1. From Jira issue (PR links in description/comments) - this is fast!
        pr_numbers.extend(issue.get_github_pr_numbers())
        logger.info(f"Found {len(pr_numbers)} PRs from Jira description for {issue.key}")
        
        # 2. Search only the main configured repo (not all repos - that causes 403 spam)
        try:
            repo = self.github.repo
            if repo:
                # Search PRs in the main repo only
                prs = repo.get_pulls(state='all', sort='updated', direction='desc')
                for pr in prs[:50]:  # Check last 50 PRs
                    # Check if Jira key is in PR title, body, or branch
                    title = pr.title or ""
                    body = pr.body or ""
                    branch = pr.head.ref or ""
                    if issue.key in title or issue.key in body or issue.key in branch:
                        if pr.number not in pr_numbers:
                            pr_numbers.append(pr.number)
                            logger.info(f"Found PR #{pr.number} in main repo for {issue.key}")
        except Exception as e:
            logger.warning(f"Could not search main repo for PRs: {e}")
        
        if pr_numbers:
            logger.info(f"Total PRs for {issue.key}: {pr_numbers}")
        
        return pr_numbers
    
    def _save_test_suite(self, suite: TestSuite, issue_key: str):
        """Save test suite to files"""
        import os
        from datetime import datetime
        
        output_dir = settings.agent.output_dir
        os.makedirs(output_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = f"{issue_key}_{timestamp}"
        
        # Save Markdown
        md_path = os.path.join(output_dir, f"{base_name}.md")
        with open(md_path, "w") as f:
            f.write(self.qa_agent.format_test_cases_markdown(suite))
        
        # Save Python tests
        py_path = os.path.join(output_dir, f"test_{base_name}.py")
        with open(py_path, "w") as f:
            f.write(self.qa_agent.format_test_cases_code(suite, "python"))
        
        console.print(f"   [dim]Saved to {output_dir}/[/dim]")
    
    def _trigger_pipelines(self, jira_issue: JiraIssue, subtask_key: str):
        """Trigger appropriate pipelines based on Jira type (Salesforce vs SDLC)"""
        try:
            pipeline_trigger = get_pipeline_trigger()
            
            console.print(f"   🔍 Detecting Jira type for pipeline selection...")
            
            # Trigger pipelines
            result = pipeline_trigger.trigger_pipelines_for_jira(
                jira_key=jira_issue.key,
                jira_summary=jira_issue.summary,
                jira_description=jira_issue.description or "",
                components=jira_issue.components,
                project_key=jira_issue.key.split("-")[0] if "-" in jira_issue.key else ""
            )
            
            detected_type = result.get("detected_type", "unknown")
            pipelines_triggered = result.get("pipelines_triggered", 0)
            
            if detected_type != "unknown":
                console.print(f"   🏷️  Detected type: [cyan]{detected_type.upper()}[/cyan]")
                
                if pipelines_triggered > 0:
                    console.print(f"   🚀 Triggered {pipelines_triggered} pipeline(s)")
                    
                    # Add pipeline execution info to Jira subtask as comment
                    pipeline_comment = pipeline_trigger.format_trigger_result_for_jira(result)
                    if subtask_key:
                        self.jira.add_comment(subtask_key, pipeline_comment)
                        console.print(f"   [green]✅ Pipeline info added to {subtask_key}[/green]")
                else:
                    console.print(f"   [yellow]⚠️ No pipelines configured for {detected_type}[/yellow]")
            else:
                console.print(f"   [dim]Could not determine Jira type, skipping pipeline trigger[/dim]")
                
        except Exception as e:
            logger.warning(f"Pipeline trigger failed (non-critical): {e}")
            console.print(f"   [dim]Pipeline trigger skipped: {e}[/dim]")
    
    def _add_to_google_sheets(
        self,
        issue_key: str,
        issue_summary: str,
        subtask_key: str,
        test_suite: TestSuite,
        pr_analysis: Optional[PRImpactAnalysis],
        is_pr_update: bool = False
    ):
        """Add test cases to Google Sheets (one row per Jira)"""
        if not self.sheets_client.is_connected():
            console.print(f"   [dim]📊 Sheets not connected, skipping...[/dim]")
            return
        
        try:
            # Convert test cases to dict format for sheets
            test_case_dicts = []
            for tc in test_suite.test_cases:
                tc_dict = {
                    "id": tc.id,
                    "title": tc.title,
                    "type": tc.test_type,
                    "priority": tc.priority,
                    "description": tc.description,
                    "preconditions": tc.preconditions,
                    "steps": tc.steps,
                    "expected_result": tc.expected_results,
                }
                test_case_dicts.append(tc_dict)
            
            # Get PR URL if available
            pr_url = None
            if pr_analysis:
                pr_url = f"https://github.com/{settings.github.repo}/pull/{pr_analysis.pr_number}"
            
            # Add to sheet (one row per Jira)
            success = self.sheets_client.add_test_cases(
                jira_id=issue_key,
                jira_summary=issue_summary,
                subtask_id=subtask_key or issue_key,
                test_cases=test_case_dicts,
                pr_url=pr_url
            )
            
            if success:
                action = "updated" if is_pr_update else "added"
                console.print(f"   [green]📊 {action} {issue_key} in Google Sheet ({len(test_case_dicts)} test cases)[/green]")
                self.stats["sheets_rows"] += 1 if not is_pr_update else 0
            else:
                console.print(f"   [yellow]📊 Could not update Google Sheet[/yellow]")
                
        except Exception as e:
            logger.error(f"Failed to add to Google Sheets: {e}")
            console.print(f"   [red]📊 Error adding to Google Sheet: {e}[/red]")
    
    def _execute_and_attach_test_report(
        self,
        jira_key: str,
        pr_number: int,
        pr_analysis: PRImpactAnalysis,
        subtask_key: str,
        pr_files: List[str] = None,
        jira_summary: str = "",
        jira_description: str = "",
        pr_title: str = "",
        pr_body: str = "",
        files_changed: List[Dict] = None
    ):
        """Execute API tests and attach HTML report to Jira subtask
        
        Args:
            jira_key: Parent Jira issue key
            pr_number: PR number
            pr_analysis: PR impact analysis
            subtask_key: Subtask to attach report to
            pr_files: Files changed in PR
            jira_summary: Jira issue summary for alignment analysis
            jira_description: Jira issue description for alignment analysis
            pr_title: PR title
            pr_body: PR description
            files_changed: Full file change info including patches
        """
        try:
            console.print(f"   🧪 Executing API tests for PR #{pr_number}...")
            
            # Execute tests and generate report with code analysis
            result = self.test_executor.execute_tests_for_pr(
                jira_key=jira_key,
                pr_number=pr_number,
                pr_analysis=pr_analysis,
                subtask_key=subtask_key,
                pr_files=pr_files,
                jira_summary=jira_summary,
                jira_description=jira_description,
                pr_title=pr_title,
                pr_description=pr_body,
                files_changed=files_changed
            )
            
            if result.success:
                self.stats["test_executions"] += 1
                
                # Show results
                status_icon = "✅" if result.failed_count == 0 else "⚠️"
                console.print(
                    f"   {status_icon} Tests executed: {result.passed_count} passed, "
                    f"{result.failed_count} failed"
                )
                
                if result.report_path:
                    console.print(f"   📄 Report: {result.report_path}")
                
                if result.attached_to_jira:
                    self.stats["test_reports_attached"] += 1
                    console.print(f"   [green]📎 Report attached to {subtask_key}[/green]")
                else:
                    console.print(f"   [yellow]📎 Could not attach report to Jira[/yellow]")
                
                # Send Slack notification (will update existing message if one exists)
                if result.summary and self.slack.is_enabled():
                    is_update = self.slack.has_existing_message(jira_key)
                    self.slack.send_test_execution_result(
                        summary=result.summary,
                        jira_key=jira_key,
                        pr_number=pr_number,
                        subtask_key=subtask_key
                    )
                    action = "updated" if is_update else "sent"
                    console.print(f"   [green]🔔 Slack message {action}[/green]")
            else:
                console.print(f"   [red]❌ Test execution failed: {result.error}[/red]")
                
        except Exception as e:
            logger.error(f"Test execution error: {e}")
            console.print(f"   [red]❌ Test execution error: {e}[/red]")
    
    def _check_for_new_prs_loop(self):
        """Background thread to check for new PRs on processed issues"""
        # Wait 15 seconds on startup before first PR check
        time.sleep(15)
        
        while True:
            try:
                self._check_for_new_prs()
                # Wait 35 seconds between PR checks
                time.sleep(35)
            except Exception as e:
                logger.error(f"Error in PR check loop: {e}")
                time.sleep(30)  # Wait on error
    
    def _check_for_new_prs(self):
        """Check if any parent issues (NOT subtasks) have new PRs"""
        
        # 1. Check parent issues we've processed in this session
        for issue_key, known_prs in list(self.processed_prs.items()):
            # Skip if this looks like a subtask key that was mistakenly added
            if self._is_subtask_key(issue_key):
                continue
            self._check_issue_for_new_prs(issue_key, known_prs)
        
        # 2. Also check recent PARENT issues that have QA Agent subtasks
        try:
            # Only check parent issues (issuetype != Sub-task)
            jql = f'''
                project = {settings.jira.project_key}
                AND created >= -7d
                AND issuetype != Sub-task
                ORDER BY created DESC
            '''
            issues = self.jira.search_issues(jql, max_results=20)
            
            for issue in issues:
                if issue.key not in self.processed_prs:
                    # Check if this parent issue has a QA Agent subtask
                    existing_subtask = self.jira.find_qa_agent_subtask(issue.key)
                    if existing_subtask:
                        # Has subtask - check for PRs
                        self._check_issue_for_new_prs(issue.key, set())
                        
        except Exception as e:
            logger.error(f"Error checking for issues with subtasks: {e}")
    
    def _is_subtask_key(self, issue_key: str) -> bool:
        """Check if an issue key belongs to a QA Agent subtask (not a parent issue)"""
        try:
            issue = self.jira.get_issue(issue_key)
            if issue:
                # Check if summary indicates it's a QA Agent subtask
                if issue.summary and "QA Agent" in issue.summary:
                    return True
                # Check issue type
                if hasattr(issue, 'issuetype') and issue.issuetype:
                    type_name = getattr(issue.issuetype, 'name', '')
                    if 'sub' in type_name.lower():
                        return True
        except Exception:
            pass
        return False
    
    def _check_issue_for_new_prs(self, issue_key: str, known_prs: set):
        """Check a specific PARENT issue for new PRs (skip subtasks)"""
        try:
            # Get the Jira issue
            jira_issue = self.jira.get_issue(issue_key)
            if not jira_issue:
                return
            
            # IMPORTANT: Skip if this is a subtask - only process parent issues
            if jira_issue.summary and "QA Agent" in jira_issue.summary:
                return  # This is a subtask, skip it
            
            # Double-check issue type
            if hasattr(jira_issue, 'issuetype') and jira_issue.issuetype:
                type_name = getattr(jira_issue.issuetype, 'name', '')
                if 'sub' in type_name.lower():
                    return  # This is a subtask, skip it
            
            # Find all PRs linked to this issue
            current_prs = set(self._find_linked_prs(jira_issue))
            
            if not current_prs:
                return
            
            # Check for new PRs we haven't processed
            new_prs = current_prs - known_prs
            
            if new_prs:
                # Filter out PRs that were already fully processed (persisted)
                truly_new_prs = {pr for pr in new_prs if not self._is_pr_already_processed(issue_key, pr)}
                
                if not truly_new_prs:
                    # All "new" PRs were actually already processed before
                    return
                
                console.print(f"\n[bold magenta]🔄 NEW PR DETECTED for {issue_key}![/bold magenta]")
                console.print(f"   New PR(s): {list(truly_new_prs)}")
                if known_prs:
                    console.print(f"   [dim]Previously processed: {list(known_prs)}[/dim]")
                
                # Slack notification for PR detection disabled - only notify on test results
                # PR detection notifications are skipped to reduce noise
                
                # Queue for reprocessing - only truly new PRs
                self.issue_queue.put({
                    "key": issue_key,
                    "summary": jira_issue.summary,
                    "new_prs": list(truly_new_prs),  # Only PRs not yet processed
                    "is_pr_update": True
                })
                
                # Mark these PRs as being processed (to prevent duplicate queueing)
                for pr in truly_new_prs:
                    self._mark_pr_processed(issue_key, pr)
                
                # Update tracked PRs
                self.processed_prs[issue_key] = current_prs
                
        except Exception as e:
            logger.error(f"Error checking PRs for {issue_key}: {e}")
    
    def _show_status(self):
        """Show current status"""
        q = self.issue_queue.qsize()
        queue_info = f"[yellow]({q} queued)[/yellow]" if q > 0 else ""
        
        status = (
            f"[dim]Check: {self.stats['last_check']} | "
            f"Issues: {self.stats['issues_processed']} | "
            f"PRs: {self.stats['prs_analyzed']} | "
            f"Tests: {self.stats['tests_generated']} | "
            f"Execs: {self.stats['test_executions']} | "
            f"Reports: {self.stats['test_reports_attached']} {queue_info}[/dim]"
        )
        console.print(status, end="\r")
    
    def _show_summary(self):
        """Show session summary"""
        console.print(f"""
[bold]Session Summary:[/bold]
  • Issues detected: {self.stats['issues_detected']}
  • Issues processed: {self.stats['issues_processed']}
  • PRs analyzed: {self.stats['prs_analyzed']}
  • PR updates detected: {self.stats['pr_updates']}
  • Test cases generated: {self.stats['tests_generated']}
  • Subtasks created: {self.stats['subtasks_created']}
  • Google Sheets rows: {self.stats['sheets_rows']}
  • 🧪 Test executions: {self.stats['test_executions']}
  • 📎 Reports attached: {self.stats['test_reports_attached']}
  • Issues being tracked: {len(self.processed_prs)}
  • Errors: {self.stats['errors']}
""")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Enhanced QA Agent")
    parser.add_argument("--interval", "-i", type=int, default=30)
    args = parser.parse_args()
    
    agent = EnhancedQAAgent(poll_interval=args.interval)
    agent.start()


if __name__ == "__main__":
    main()

