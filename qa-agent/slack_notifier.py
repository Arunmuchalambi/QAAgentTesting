"""
Slack Notifier - Sends test results and notifications to Slack
Supports message updates for cleaner conversation threads
"""

import json
import os
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
import requests
from loguru import logger

from api_executor import TestExecutionSummary, TestStatus


@dataclass
class SlackConfig:
    """Slack configuration"""
    bot_token: str = ""
    channel: str = "qaagent"
    username: str = "QA Agent"
    icon_emoji: str = ""  # Fallback emoji
    icon_url: str = ""  # QA logo
    webhook_url: str = ""
    enabled: bool = True
    notify_on: Dict[str, bool] = None
    
    def __post_init__(self):
        if self.notify_on is None:
            self.notify_on = {
                "test_execution": True,
                "test_pass": True,
                "test_fail": True,
                "new_jira": True,
                "pr_detected": True
            }


@dataclass
class JiraTestHistory:
    """Tracks test history for a Jira issue"""
    jira_key: str
    subtask_key: str
    message_ts: str  # Slack message timestamp for updates
    channel: str
    pr_results: List[Dict[str, Any]] = field(default_factory=list)  # List of PR test results
    created_at: str = ""
    updated_at: str = ""


class SlackNotifier:
    """
    Sends notifications to Slack about QA Agent activities
    
    Supports:
    - Test execution results with pass/fail summary
    - New Jira issue detection
    - PR analysis results
    - Code quality suggestions
    - MESSAGE UPDATES: Modifies existing messages when new PRs are detected
    """
    
    # Emoji mappings for different statuses
    EMOJIS = {
        "pass": "✅",
        "fail": "❌",
        "warning": "⚠️",
        "info": "ℹ️",
        "test": "🧪",
        "jira": "🎫",
        "pr": "🔀",
        "report": "📊",
        "bird": "🐦",  # Hummingbird representation
        "rocket": "🚀",
        "fire": "🔥",
        "star": "⭐",
    }
    
    # File to persist message tracking
    MESSAGE_TRACKING_FILE = "slack_message_tracking.json"
    
    def __init__(self, config_path: str = "slack_config.json"):
        self.config = self._load_config(config_path)
        self._session = requests.Session()
        self._message_tracking: Dict[str, JiraTestHistory] = {}
        self._load_message_tracking()
    
    def _load_config(self, config_path: str) -> SlackConfig:
        """Load Slack configuration from file"""
        try:
            config_file = os.path.join(os.path.dirname(__file__), config_path)
            if os.path.exists(config_file):
                with open(config_file) as f:
                    data = json.load(f)
                    return SlackConfig(**data)
            logger.warning(f"Slack config not found: {config_path}")
        except Exception as e:
            logger.error(f"Failed to load Slack config: {e}")
        
        return SlackConfig(enabled=False)
    
    def _load_message_tracking(self):
        """Load message tracking from file"""
        try:
            tracking_file = os.path.join(os.path.dirname(__file__), self.MESSAGE_TRACKING_FILE)
            if os.path.exists(tracking_file):
                with open(tracking_file) as f:
                    data = json.load(f)
                    for jira_key, history_data in data.items():
                        self._message_tracking[jira_key] = JiraTestHistory(**history_data)
                logger.info(f"Loaded {len(self._message_tracking)} tracked Slack messages")
        except Exception as e:
            logger.warning(f"Could not load message tracking: {e}")
    
    def _save_message_tracking(self):
        """Save message tracking to file"""
        try:
            tracking_file = os.path.join(os.path.dirname(__file__), self.MESSAGE_TRACKING_FILE)
            data = {}
            for jira_key, history in self._message_tracking.items():
                data[jira_key] = {
                    "jira_key": history.jira_key,
                    "subtask_key": history.subtask_key,
                    "message_ts": history.message_ts,
                    "channel": history.channel,
                    "pr_results": history.pr_results,
                    "created_at": history.created_at,
                    "updated_at": history.updated_at
                }
            with open(tracking_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Could not save message tracking: {e}")
    
    def is_enabled(self) -> bool:
        """Check if Slack notifications are enabled"""
        return self.config.enabled and (self.config.bot_token or self.config.webhook_url)
    
    def has_existing_message(self, jira_key: str) -> bool:
        """Check if we have an existing message for this Jira"""
        return jira_key in self._message_tracking
    
    def send_test_execution_result(
        self,
        summary: TestExecutionSummary,
        jira_key: str,
        pr_number: int = None,
        report_url: str = None,
        subtask_key: str = None
    ) -> bool:
        """Send or UPDATE test execution results to Slack
        
        If a message already exists for this Jira, UPDATE it with new PR results.
        Otherwise, send a new message.
        
        Args:
            summary: Test execution summary
            jira_key: Jira issue key
            pr_number: PR number (optional)
            report_url: URL to the test report (optional)
            subtask_key: Subtask key (optional)
        """
        if not self.is_enabled():
            return False
        
        if not self.config.notify_on.get("test_execution", True):
            return False
        
        # Skip if configured to not notify on specific outcomes
        if summary.overall_status == TestStatus.PASSED and not self.config.notify_on.get("test_pass", True):
            return False
        if summary.overall_status == TestStatus.FAILED and not self.config.notify_on.get("test_fail", True):
            return False
        
        # Check if we should UPDATE an existing message
        if self.has_existing_message(jira_key):
            return self._update_existing_message(jira_key, summary, pr_number, report_url)
        
        # Build the NEW consolidated message with extracted summary fields
        blocks = self._build_consolidated_message(
            jira_key=jira_key,
            subtask_key=subtask_key,
            pr_results=[{
                "pr_number": pr_number,
                "passed": summary.passed,
                "failed": summary.failed,
                "total": summary.total_tests,
                "status": summary.overall_status.value,
                "timestamp": datetime.now().isoformat()
            }]
        )
        
        # Send and track the message
        result = self._send_message(blocks=blocks, return_ts=True)
        
        if result and isinstance(result, tuple):
            success, message_ts = result
            if success and message_ts:
                # Track this message for future updates
                self._message_tracking[jira_key] = JiraTestHistory(
                    jira_key=jira_key,
                    subtask_key=subtask_key or "",
                    message_ts=message_ts,
                    channel=self.config.channel,
                    pr_results=[{
                        "pr_number": pr_number,
                        "passed": summary.passed,
                        "failed": summary.failed,
                        "total": summary.total_tests,
                        "status": summary.overall_status.value,
                        "timestamp": datetime.now().isoformat()
                    }],
                    created_at=datetime.now().isoformat(),
                    updated_at=datetime.now().isoformat()
                )
                self._save_message_tracking()
                logger.info(f"Tracking Slack message for {jira_key}: {message_ts}")
            return success
        
        return result if isinstance(result, bool) else False
    
    def _update_existing_message(
        self,
        jira_key: str,
        summary: TestExecutionSummary,
        pr_number: int,
        report_url: str = None
    ) -> bool:
        """Update an existing Slack message with new PR test results"""
        try:
            history = self._message_tracking.get(jira_key)
            if not history:
                return False
            
            # Add new PR result to history
            new_result = {
                "pr_number": pr_number,
                "passed": summary.passed,
                "failed": summary.failed,
                "total": summary.total_tests,
                "status": summary.overall_status.value,
                "timestamp": datetime.now().isoformat()
            }
            
            # Check if this PR already exists (update it)
            pr_exists = False
            for i, result in enumerate(history.pr_results):
                if result.get("pr_number") == pr_number:
                    history.pr_results[i] = new_result
                    pr_exists = True
                    break
            
            if not pr_exists:
                history.pr_results.append(new_result)
            
            history.updated_at = datetime.now().isoformat()
            
            # Build updated consolidated message
            blocks = self._build_consolidated_message(
                jira_key=jira_key,
                subtask_key=history.subtask_key,
                pr_results=history.pr_results
            )
            
            # Update the message
            success = self._update_message(
                channel=history.channel,
                ts=history.message_ts,
                blocks=blocks
            )
            
            if success:
                self._save_message_tracking()
                logger.info(f"Updated Slack message for {jira_key} with PR #{pr_number}")
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to update Slack message: {e}")
            return False
    
    def _build_consolidated_message(
        self,
        jira_key: str,
        subtask_key: str,
        pr_results: List[Dict]
    ) -> List[Dict]:
        """Build a compact consolidated message showing all PR test results for a Jira"""
        
        jira_url = f"https://your-domain.atlassian.net/browse/{jira_key}"
        subtask_url = f"https://your-domain.atlassian.net/browse/{subtask_key}" if subtask_key else None
        
        # Calculate overall stats
        total_prs = len(pr_results)
        total_tests = sum(r.get("total", 0) for r in pr_results)
        total_passed = sum(r.get("passed", 0) for r in pr_results)
        total_failed = sum(r.get("failed", 0) for r in pr_results)
        
        # Determine overall status
        overall_pass = all(r.get("status") == "passed" for r in pr_results)
        status_emoji = "✅" if overall_pass else "❌"
        
        # Build compact message
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{status_emoji} *<{jira_url}|{jira_key}>* | Tests: {total_passed}/{total_tests} passed"
                }
            }
        ]
        
        # Add subtask link
        if subtask_key and subtask_url:
            blocks[0]["text"]["text"] += f" | <{subtask_url}|{subtask_key}>"
        
        # PR results in compact format
        pr_lines = []
        for result in pr_results:
            pr_num = result.get("pr_number", "?")
            passed = result.get("passed", 0)
            failed = result.get("failed", 0)
            total = result.get("total", 0)
            status = result.get("status", "unknown")
            
            pr_emoji = "✅" if status == "passed" else "❌"
            pr_url = f"https://github.com/your-org/your-repo/pull/{pr_num}"
            
            pr_lines.append(f"{pr_emoji} <{pr_url}|PR #{pr_num}>: {passed}/{total} passed")
        
        if pr_lines:
            blocks.append({
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": " | ".join(pr_lines)
                    }
                ]
            })
        
        return blocks
    
    def send_new_jira_notification(
        self,
        jira_key: str,
        summary: str,
        test_count: int = 0,
        subtask_key: str = None
    ) -> bool:
        """Send notification about new Jira issue processed (legacy - use send_initial_jira_message)"""
        return self.send_initial_jira_message(jira_key, summary, subtask_key, test_count)
    
    def send_initial_jira_message(
        self,
        jira_key: str,
        jira_summary: str,
        subtask_key: str = None,
        test_count: int = 0
    ) -> bool:
        """Send initial tracked message for a Jira issue
        
        This message will be UPDATED when PRs are detected, keeping everything in one place.
        """
        if not self.is_enabled() or not self.config.notify_on.get("new_jira", True):
            return False
        
        jira_url = f"https://your-domain.atlassian.net/browse/{jira_key}"
        subtask_url = f"https://your-domain.atlassian.net/browse/{subtask_key}" if subtask_key else None
        
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"🐦🧪 QA Agent Test Results",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Parent Jira:* <{jira_url}|{jira_key}>"
                }
            }
        ]
        
        if subtask_key:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"└── *Subtask:* <{subtask_url}|{subtask_key}> (QA Agent Test Cases)"
                }
            })
        
        blocks.append({"type": "divider"})
        
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Summary:* {jira_summary[:100]}{'...' if len(jira_summary) > 100 else ''}"
            }
        })
        
        blocks.append({
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Test Cases Generated:* {test_count}"},
                {"type": "mrkdwn", "text": "*PRs Tested:* _Waiting for PRs..._"}
            ]
        })
        
        blocks.append({"type": "divider"})
        
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*📋 Test Details by PR:*\n_No PRs tested yet. This message will be updated when PRs are created/merged._"
            }
        })
        
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"🐦 QA Agent | Created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                }
            ]
        })
        
        # Send and track the message
        result = self._send_message(blocks=blocks, return_ts=True)
        
        if result and isinstance(result, tuple):
            success, message_ts = result
            if success and message_ts:
                # Track this message for future updates
                self._message_tracking[jira_key] = JiraTestHistory(
                    jira_key=jira_key,
                    subtask_key=subtask_key or "",
                    message_ts=message_ts,
                    channel=self.config.channel,
                    pr_results=[],  # No PR results yet
                    created_at=datetime.now().isoformat(),
                    updated_at=datetime.now().isoformat()
                )
                self._save_message_tracking()
                logger.info(f"Created tracked Slack message for {jira_key}: {message_ts}")
            return success
        
        return result if isinstance(result, bool) else False
    
    def send_pr_detected_notification(
        self,
        jira_key: str,
        pr_number: int,
        pr_title: str,
        files_changed: int = 0,
        critical_changes: bool = False
    ) -> bool:
        """Send notification about PR detected for Jira"""
        if not self.is_enabled() or not self.config.notify_on.get("pr_detected", True):
            return False
        
        status_emoji = "🔴" if critical_changes else "🟢"
        
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"🐦🔀 PR Detected for {jira_key}",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*PR:*\n#{pr_number}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Files Changed:*\n{files_changed}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Critical:*\n{status_emoji} {'Yes' if critical_changes else 'No'}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Title:*\n{pr_title[:50]}..."
                    }
                ]
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"🤖 Analyzing PR and generating test cases..."
                    }
                ]
            }
        ]
        
        return self._send_message(blocks=blocks)
    
    def _build_test_result_blocks(
        self,
        summary: TestExecutionSummary,
        jira_key: str,
        pr_number: int = None,
        report_url: str = None
    ) -> List[Dict]:
        """Build Slack blocks for test execution results"""
        
        # Determine overall status styling
        if summary.overall_status == TestStatus.PASSED:
            status_text = "✅ ALL TESTS PASSED"
            status_color = "#10B981"
        else:
            status_text = "❌ TESTS FAILED"
            status_color = "#EF4444"
        
        pass_rate = (summary.passed / summary.total_tests * 100) if summary.total_tests > 0 else 0
        
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"🐦🧪 Test Execution Complete",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{status_text}*"
                }
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Jira:*\n<https://your-domain.atlassian.net/browse/{jira_key}|{jira_key}>"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*PR:*\n#{pr_number or 'N/A'}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Pass Rate:*\n{pass_rate:.1f}%"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Duration:*\n{summary.total_time_ms:.0f}ms"
                    }
                ]
            },
            {
                "type": "divider"
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Total:* {summary.total_tests}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*✅ Passed:* {summary.passed}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*❌ Failed:* {summary.failed}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*⚠️ Errors:* {summary.errors}"
                    }
                ]
            }
        ]
        
        # Add progress bar visualization
        progress_bar = self._create_progress_bar(summary)
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Progress:* {progress_bar}"
            }
        })
        
        # Add failed test details (if any)
        failed_tests = [r for r in summary.results if r.status == TestStatus.FAILED]
        if failed_tests[:3]:  # Show max 3 failed tests
            blocks.append({
                "type": "divider"
            })
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*❌ Failed Tests:*"
                }
            })
            
            for test in failed_tests[:3]:
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"• `{test.test_id}`: {test.test_name}\n  Status: {test.actual_status} (expected {test.expected_status})"
                    }
                })
        
        # Add suggestions if there are failures
        all_suggestions = []
        for result in summary.results:
            if result.suggestions:
                all_suggestions.extend(result.suggestions[:2])
        
        if all_suggestions:
            unique_suggestions = list(dict.fromkeys(all_suggestions))[:5]
            blocks.append({
                "type": "divider"
            })
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*💡 Suggestions:*\n" + "\n".join(f"• {s}" for s in unique_suggestions)
                }
            })
        
        # Add report link if available
        if report_url:
            blocks.append({
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "📊 View Full Report",
                            "emoji": True
                        },
                        "url": report_url,
                        "style": "primary"
                    }
                ]
            })
        
        # Add footer
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"🐦 QA Agent | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                }
            ]
        })
        
        return blocks
    
    def _create_progress_bar(self, summary: TestExecutionSummary) -> str:
        """Create a text-based progress bar"""
        total = summary.total_tests
        if total == 0:
            return "No tests"
        
        width = 20
        passed_blocks = int((summary.passed / total) * width)
        failed_blocks = int((summary.failed / total) * width)
        error_blocks = int((summary.errors / total) * width)
        
        # Ensure at least 1 block for non-zero values
        if summary.passed > 0 and passed_blocks == 0:
            passed_blocks = 1
        if summary.failed > 0 and failed_blocks == 0:
            failed_blocks = 1
        if summary.errors > 0 and error_blocks == 0:
            error_blocks = 1
        
        bar = "🟢" * passed_blocks + "🔴" * failed_blocks + "🟡" * error_blocks
        remaining = width - len(bar.replace("🟢", "X").replace("🔴", "X").replace("🟡", "X"))
        bar += "⚪" * remaining
        
        return bar
    
    def _send_message(
        self,
        text: str = None,
        blocks: List[Dict] = None,
        attachments: List[Dict] = None,
        return_ts: bool = False
    ):
        """Send message to Slack
        
        Args:
            text: Simple text message
            blocks: Rich message blocks
            attachments: Message attachments
            return_ts: If True, return (success, message_ts) tuple
        
        Returns:
            bool or (bool, str): Success status, optionally with message timestamp
        """
        try:
            payload = {
                "channel": self.config.channel,
                "username": self.config.username,
            }
            
            # Use icon_url (QA logo) if available, otherwise fallback to emoji
            if self.config.icon_url:
                payload["icon_url"] = self.config.icon_url
            elif self.config.icon_emoji:
                payload["icon_emoji"] = self.config.icon_emoji
            
            if text:
                payload["text"] = text
            if blocks:
                payload["blocks"] = blocks
            if attachments:
                payload["attachments"] = attachments
            
            # Use webhook URL if available, otherwise use bot token
            if self.config.webhook_url:
                response = self._session.post(
                    self.config.webhook_url,
                    json=payload,
                    timeout=10
                )
                # Webhooks don't return message_ts
                if response.status_code == 200:
                    logger.info(f"Slack notification sent to #{self.config.channel}")
                    return (True, None) if return_ts else True
                return (False, None) if return_ts else False
            else:
                # Use Slack API with bot token
                headers = {
                    "Authorization": f"Bearer {self.config.bot_token}",
                    "Content-Type": "application/json"
                }
                response = self._session.post(
                    "https://slack.com/api/chat.postMessage",
                    headers=headers,
                    json=payload,
                    timeout=10
                )
            
            if response.status_code == 200:
                result = response.json() if response.headers.get('content-type', '').startswith('application/json') else {}
                if result.get("ok", True):
                    logger.info(f"Slack notification sent to #{self.config.channel}")
                    message_ts = result.get("ts")
                    return (True, message_ts) if return_ts else True
                else:
                    logger.error(f"Slack API error: {result.get('error', 'Unknown')}")
            else:
                logger.error(f"Slack request failed: {response.status_code}")
            
            return (False, None) if return_ts else False
            
        except Exception as e:
            logger.error(f"Failed to send Slack notification: {e}")
            return (False, None) if return_ts else False
    
    def _update_message(
        self,
        channel: str,
        ts: str,
        text: str = None,
        blocks: List[Dict] = None
    ) -> bool:
        """Update an existing Slack message
        
        Args:
            channel: Channel where message exists
            ts: Message timestamp (unique ID)
            text: Updated text
            blocks: Updated blocks
        """
        try:
            if not self.config.bot_token:
                logger.warning("Cannot update message without bot token (webhooks don't support updates)")
                return False
            
            payload = {
                "channel": channel,
                "ts": ts,
            }
            
            if text:
                payload["text"] = text
            if blocks:
                payload["blocks"] = blocks
            
            headers = {
                "Authorization": f"Bearer {self.config.bot_token}",
                "Content-Type": "application/json"
            }
            
            response = self._session.post(
                "https://slack.com/api/chat.update",
                headers=headers,
                json=payload,
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get("ok"):
                    logger.info(f"Updated Slack message {ts}")
                    return True
                else:
                    logger.error(f"Slack update error: {result.get('error', 'Unknown')}")
            else:
                logger.error(f"Slack update request failed: {response.status_code}")
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to update Slack message: {e}")
            return False
    
    def send_simple_message(self, message: str) -> bool:
        """Send a simple text message to Slack"""
        if not self.is_enabled():
            return False
        
        return self._send_message(text=message)


# Singleton instance
_slack_notifier: Optional[SlackNotifier] = None


def get_slack_notifier() -> SlackNotifier:
    """Get or create Slack notifier instance"""
    global _slack_notifier
    if _slack_notifier is None:
        _slack_notifier = SlackNotifier()
    return _slack_notifier


def notify_test_execution(
    summary: TestExecutionSummary,
    jira_key: str,
    pr_number: int = None
) -> bool:
    """Convenience function to send test execution notification"""
    notifier = get_slack_notifier()
    return notifier.send_test_execution_result(summary, jira_key, pr_number)


# Quick test
if __name__ == "__main__":
    from api_executor import TestStatus, TestResult, APIRequest, APIResponse
    
    # Create sample test summary
    sample_summary = TestExecutionSummary(
        total_tests=10,
        passed=7,
        failed=2,
        errors=1,
        skipped=0,
        total_time_ms=5432,
        results=[
            TestResult(
                test_id="TC_001",
                test_name="GET /api/users",
                description="Test getting users",
                status=TestStatus.FAILED,
                request=APIRequest(method="GET", url="/api/users"),
                response=APIResponse(status_code=401, response_time_ms=100),
                expected_status=200,
                actual_status=401,
                suggestions=["🔐 Check authentication token"],
                execution_time_ms=100,
                source_file="test.json"
            )
        ],
        pr_number=123,
        overall_status=TestStatus.FAILED
    )
    
    notifier = SlackNotifier()
    
    if notifier.is_enabled():
        print("Sending test notification to Slack...")
        success = notifier.send_test_execution_result(
            summary=sample_summary,
            jira_key="DT-1234",
            pr_number=123
        )
        print(f"Notification sent: {success}")
    else:
        print("Slack notifications not enabled. Configure slack_config.json")
        print("\nSample message blocks:")
        blocks = notifier._build_test_result_blocks(sample_summary, "DT-1234", 123)
        print(json.dumps(blocks, indent=2))

