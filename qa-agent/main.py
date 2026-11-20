"""
QA Agent - Main Orchestrator
Coordinates Jira, GitHub, and AI components to generate test cases
"""

import os
import sys
from datetime import datetime
from typing import Optional
from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

from config import settings
from jira_client import JiraClient, JiraIssue
from github_client import GitHubClient, PRDetails
from qa_agent import QAAgent, TestSuite

# Configure logging
logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | {message}")

console = Console()


class QAAgentOrchestrator:
    """Main orchestrator that ties everything together"""
    
    def __init__(self):
        self.jira = JiraClient()
        self.github = GitHubClient()
        self.qa_agent = QAAgent()
        self._connected = False
    
    def connect_all(self) -> bool:
        """Connect to all services"""
        console.print("\n[bold blue]🔌 Connecting to services...[/bold blue]\n")
        
        errors = settings.validate()
        if errors:
            console.print("[bold red]❌ Configuration errors:[/bold red]")
            for error in errors:
                console.print(f"  • {error}")
            return False
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            # Connect to Jira
            task = progress.add_task("Connecting to Jira...", total=None)
            jira_ok = self.jira.connect()
            progress.remove_task(task)
            
            # Connect to GitHub
            task = progress.add_task("Connecting to GitHub...", total=None)
            github_ok = self.github.connect()
            progress.remove_task(task)
            
            # Initialize OpenAI
            task = progress.add_task("Initializing OpenAI...", total=None)
            openai_ok = self.qa_agent.connect()
            progress.remove_task(task)
        
        self._connected = jira_ok and github_ok and openai_ok
        
        if self._connected:
            console.print("\n[bold green]✅ All services connected successfully![/bold green]\n")
        else:
            console.print("\n[bold red]❌ Some services failed to connect[/bold red]\n")
        
        return self._connected
    
    def process_jira_issue(
        self,
        issue_key: str,
        post_to_jira: bool = False,
        post_to_github: bool = False,
        save_to_file: bool = True
    ) -> Optional[TestSuite]:
        """Process a Jira issue and generate test cases"""
        
        console.print(Panel(f"Processing Jira Issue: [bold]{issue_key}[/bold]", style="blue"))
        
        # 1. Fetch Jira issue
        console.print("📋 Fetching Jira issue...")
        jira_issue = self.jira.get_issue(issue_key)
        
        if not jira_issue:
            console.print(f"[red]Could not fetch Jira issue {issue_key}[/red]")
            return None
        
        self._display_jira_issue(jira_issue)
        
        # 2. Find associated PRs
        console.print("\n🔍 Searching for associated PRs...")
        prs = self.github.search_prs_by_jira_key(issue_key)
        
        # Also check PR numbers mentioned in the issue
        mentioned_pr_numbers = jira_issue.get_github_pr_numbers()
        for pr_num in mentioned_pr_numbers:
            pr = self.github.get_pr(pr_num)
            if pr and pr.number not in [p.number for p in prs]:
                prs.append(pr)
        
        pr_details = None
        files = []
        
        if prs:
            console.print(f"[green]Found {len(prs)} associated PR(s)[/green]")
            pr_details = prs[0]  # Use the first/most relevant PR
            self._display_pr_details(pr_details)
            
            # 3. Fetch file contents
            console.print("\n📂 Fetching repository files...")
            files = self.github.get_pr_file_contents(pr_details)
            console.print(f"[green]Loaded {len(files)} file(s)[/green]")
        else:
            console.print("[yellow]No associated PRs found[/yellow]")
        
        # 4. Generate test cases
        console.print("\n🤖 Generating test cases with AI...")
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("AI is analyzing and generating tests...", total=None)
            test_suite = self.qa_agent.generate_test_cases(
                jira_issue=jira_issue,
                pr_details=pr_details,
                files=files
            )
            progress.remove_task(task)
        
        if not test_suite:
            console.print("[red]Failed to generate test cases[/red]")
            return None
        
        # 5. Display results
        self._display_test_suite(test_suite)
        
        # 6. Save to file
        if save_to_file:
            self._save_test_suite(test_suite)
        
        # 7. Post to Jira
        if post_to_jira and jira_issue:
            console.print("\n📝 Posting test cases to Jira...")
            markdown = self.qa_agent.format_test_cases_markdown(test_suite)
            if self.jira.add_test_cases_comment(issue_key, markdown):
                console.print("[green]✅ Posted to Jira[/green]")
        
        # 8. Post to GitHub PR
        if post_to_github and pr_details:
            console.print("\n📝 Posting test cases to GitHub PR...")
            markdown = self.qa_agent.format_test_cases_markdown(test_suite)
            if self.github.add_pr_comment(pr_details.number, f"## 🤖 QA Agent - Generated Test Cases\n\n{markdown}"):
                console.print("[green]✅ Posted to GitHub PR[/green]")
        
        return test_suite
    
    def process_pr(
        self,
        pr_number: int,
        post_to_github: bool = False,
        save_to_file: bool = True
    ) -> Optional[TestSuite]:
        """Process a GitHub PR directly"""
        
        console.print(Panel(f"Processing PR: [bold]#{pr_number}[/bold]", style="blue"))
        
        # 1. Fetch PR details
        console.print("🔍 Fetching PR details...")
        pr_details = self.github.get_pr(pr_number)
        
        if not pr_details:
            console.print(f"[red]Could not fetch PR #{pr_number}[/red]")
            return None
        
        self._display_pr_details(pr_details)
        
        # 2. Fetch file contents
        console.print("\n📂 Fetching repository files...")
        files = self.github.get_pr_file_contents(pr_details)
        console.print(f"[green]Loaded {len(files)} file(s)[/green]")
        
        # 3. Generate test cases
        console.print("\n🤖 Generating test cases with AI...")
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("AI is analyzing and generating tests...", total=None)
            test_suite = self.qa_agent.generate_test_cases(
                pr_details=pr_details,
                files=files
            )
            progress.remove_task(task)
        
        if not test_suite:
            console.print("[red]Failed to generate test cases[/red]")
            return None
        
        # 4. Display results
        self._display_test_suite(test_suite)
        
        # 5. Save to file
        if save_to_file:
            self._save_test_suite(test_suite)
        
        # 6. Post to GitHub
        if post_to_github:
            console.print("\n📝 Posting test cases to GitHub PR...")
            markdown = self.qa_agent.format_test_cases_markdown(test_suite)
            if self.github.add_pr_comment(pr_number, f"## 🤖 QA Agent - Generated Test Cases\n\n{markdown}"):
                console.print("[green]✅ Posted to GitHub PR[/green]")
        
        return test_suite
    
    def _display_jira_issue(self, issue: JiraIssue):
        """Display Jira issue details"""
        table = Table(title=f"Jira Issue: {issue.key}", show_header=False)
        table.add_column("Field", style="cyan")
        table.add_column("Value")
        
        table.add_row("Summary", issue.summary)
        table.add_row("Type", issue.issue_type)
        table.add_row("Status", issue.status)
        table.add_row("Assignee", issue.assignee or "Unassigned")
        table.add_row("Labels", ", ".join(issue.labels) or "None")
        
        console.print(table)
    
    def _display_pr_details(self, pr: PRDetails):
        """Display PR details"""
        table = Table(title=f"PR #{pr.number}: {pr.title}", show_header=False)
        table.add_column("Field", style="cyan")
        table.add_column("Value")
        
        table.add_row("Author", pr.author)
        table.add_row("Branch", f"{pr.branch} → {pr.base_branch}")
        table.add_row("State", pr.state)
        table.add_row("Changes", f"+{pr.additions}/-{pr.deletions}")
        table.add_row("Files", str(len(pr.files_changed)))
        
        console.print(table)
    
    def _display_test_suite(self, suite: TestSuite):
        """Display generated test cases"""
        console.print(f"\n[bold green]✅ Generated {len(suite.test_cases)} test cases[/bold green]\n")
        
        table = Table(title="Generated Test Cases")
        table.add_column("ID", style="cyan")
        table.add_column("Title")
        table.add_column("Type", style="blue")
        table.add_column("Priority", style="yellow")
        table.add_column("Steps")
        
        for tc in suite.test_cases:
            priority_color = {"high": "red", "medium": "yellow", "low": "green"}.get(tc.priority, "white")
            table.add_row(
                tc.id,
                tc.title[:50] + "..." if len(tc.title) > 50 else tc.title,
                tc.test_type,
                f"[{priority_color}]{tc.priority}[/{priority_color}]",
                str(len(tc.steps))
            )
        
        console.print(table)
        
        if suite.summary:
            console.print(Panel(suite.summary, title="Summary", style="blue"))
    
    def _save_test_suite(self, suite: TestSuite):
        """Save test suite to files"""
        output_dir = settings.agent.output_dir
        os.makedirs(output_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = f"{suite.jira_key or f'PR{suite.pr_number}'}_{timestamp}"
        
        # Save Markdown
        md_path = os.path.join(output_dir, f"{base_name}.md")
        with open(md_path, "w") as f:
            f.write(self.qa_agent.format_test_cases_markdown(suite))
        console.print(f"[green]📄 Saved Markdown: {md_path}[/green]")
        
        # Save Python tests
        py_path = os.path.join(output_dir, f"test_{base_name}.py")
        with open(py_path, "w") as f:
            f.write(self.qa_agent.format_test_cases_code(suite, "python"))
        console.print(f"[green]🐍 Saved Python tests: {py_path}[/green]")
        
        # Save JavaScript tests
        js_path = os.path.join(output_dir, f"{base_name}.test.js")
        with open(js_path, "w") as f:
            f.write(self.qa_agent.format_test_cases_code(suite, "javascript"))
        console.print(f"[green]📜 Saved JavaScript tests: {js_path}[/green]")


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="QA Agent - AI-Powered Test Case Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process a Jira issue
  python main.py --jira PROJ-123
  
  # Process a GitHub PR
  python main.py --pr 42
  
  # Process Jira and post results back
  python main.py --jira PROJ-123 --post-jira --post-github
        """
    )
    
    parser.add_argument("--jira", "-j", help="Jira issue key (e.g., PROJ-123)")
    parser.add_argument("--pr", "-p", type=int, help="GitHub PR number")
    parser.add_argument("--post-jira", action="store_true", help="Post results to Jira")
    parser.add_argument("--post-github", action="store_true", help="Post results to GitHub PR")
    parser.add_argument("--no-save", action="store_true", help="Don't save to files")
    
    args = parser.parse_args()
    
    # Banner
    console.print(Panel.fit(
        "[bold blue]🤖 QA Agent - Test Case Generator[/bold blue]\n"
        "[dim]Powered by GPT-4[/dim]",
        border_style="blue"
    ))
    
    if not args.jira and not args.pr:
        parser.print_help()
        console.print("\n[yellow]Please specify --jira or --pr[/yellow]")
        return
    
    # Initialize orchestrator
    orchestrator = QAAgentOrchestrator()
    
    if not orchestrator.connect_all():
        console.print("[red]Failed to connect to services. Check your .env configuration.[/red]")
        return
    
    # Process based on input
    if args.jira:
        orchestrator.process_jira_issue(
            args.jira,
            post_to_jira=args.post_jira,
            post_to_github=args.post_github,
            save_to_file=not args.no_save
        )
    elif args.pr:
        orchestrator.process_pr(
            args.pr,
            post_to_github=args.post_github,
            save_to_file=not args.no_save
        )


if __name__ == "__main__":
    main()

