# QAAgentTesting
Automatically create test cases from Jira/PR, Run Automation pipelines and tests, then send reports to Slack and Jira.

What this agent does
Detect work — Watches Jira issues and linked GitHub PRs
Create test cases — Uses AI to generate test cases from Jira + PR changes
Post to Jira — Creates Jira subtasks/comments with the test cases
Run pipeline — Triggers Automation pipelines 
Execute tests — Runs API tests and builds HTML reports
Send reports — Shares results to Slack and Jira (and Google Sheets)
End-to-end flow

------------------------------------------------------------------------------------

Jira Issue / PR
      ↓
Create AI Test Cases
      ↓
Post Test Cases → Jira (subtask + comments)
      ↓
Run Automation Pipeline + Execute Tests
      ↓
Generate HTML Report
      ↓
Send Report → Slack + Jira (+ Google Sheets)

--------------------------------------------------------------------------------------

Scope by capability
Capability	In scope
Create test cases
Generate AI test cases from Jira description and PR code changes
Analyze PR impact
Detect API/Kafka/critical changes and enrich tests
Post to Jira
Create subtasks, add test-case comments, attach reports
Run pipeline
Auto-trigger Automation pipelines from pipeline_config.json
Run tests
Execute API tests and collect pass/fail outcomes
Generate report
Create HTML test outcome reports
Send to Slack
Notify on test execution / pass / fail
Track in Sheets
Log test cases in Google Sheets
