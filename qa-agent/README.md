# QA Agent

Automated test case generation and PR analysis for Jira issues.

---

## Quick Start

### Run Agent
```bash
cd ./qa-agent
source venv/bin/activate
python enhanced_qa_agent.py --interval 30
```

### Run in Background
```bash
nohup python enhanced_qa_agent.py --interval 30 > agent.log 2>&1 &
```

### View Logs
```bash
tail -f agent.log
```

---

## Troubleshooting

### Kill & Restart
```bash
# Kill existing agent
pkill -f "enhanced_qa_agent"

# Wait and restart
sleep 2
cd ./qa-agent
source venv/bin/activate
nohup python enhanced_qa_agent.py --interval 30 > agent.log 2>&1 &
```

### Check if Running
```bash
ps aux | grep enhanced_qa_agent | grep -v grep
```

---

## Folder Structure

```
qa-agent/
├── enhanced_qa_agent.py       # Main agent (polling + PR detection)
├── main.py                    # CLI + orchestrator
├── config.py                  # Settings from .env
├── jira_client.py             # Jira API integration
├── github_client.py           # GitHub API integration
├── qa_agent.py                # Test case generation (OpenAI)
├── pr_analyzer.py             # PR impact analysis
├── product_knowledge.py       # Product knowledge helper
├── pipeline_trigger.py        # Pipeline trigger
├── sheets_client.py           # Google Sheets integration
├── slack_notifier.py          # Slack notifications
├── test_execution_service.py  # API test orchestration
├── test_data_finder.py        # Find API test data
├── api_executor.py            # Execute API tests
├── test_report_generator.py   # HTML report generation
├── report_server.py           # Serves reports at localhost:8080
│
├── env.example                # Env template (copy to .env)
├── slack_config.example.json  # Slack config template
├── pipeline_config.json       # Pipeline IDs
├── component_mapping.json     # Repo/feature mapping
├── product_knowledge.json     # Product knowledge base
└── requirements.txt
```

---

## Configuration Files

| File | Purpose |
|------|---------|
| `.env` | API keys (JIRA, GitHub, OpenAI) |
| `google_credentials.json` | Google Sheets service account |
| `slack_config.json` | Slack webhook URL |
| `pipeline_config.json` | QA pipeline IDs |

---

## Tools & Technologies

| Tool | Purpose |
|------|---------|
| **Python 3.13** | Runtime |
| **OpenAI GPT-4o** | Test case generation & code alignment |
| **Jira API** | Issue tracking, subtasks, comments |
| **GitHub API** | PR detection, file changes |
| **Google Sheets API** | Test case tracking |
| **Slack API** | Notifications |
| **Pattern Analysis** | Code quality checks |
| **Semgrep** (optional) | Static code analysis |

---

## Features

- ✅ Auto-detect new Jira issues (polling every 30s)
- ✅ Auto-detect PRs linked to Jira (every 35s)
- ✅ Generate AI-powered test cases
- ✅ Create Jira subtasks with test details
- ✅ PR impact analysis (API/Kafka detection)
- ✅ Code quality analysis (pattern-based)
- ✅ Code alignment analysis (AI-powered)
- ✅ HTML test reports with charts
- ✅ Google Sheets integration
- ✅ Slack notifications

---

## View Reports

```bash
# Start report server (usually auto-started)
python report_server.py
```

Open: http://localhost:8080

---

## Environment Variables

```env
JIRA_URL=https://your-domain.atlassian.net
JIRA_EMAIL=your-email@company.com
JIRA_API_TOKEN=your-jira-token
JIRA_PROJECT=DT

GITHUB_TOKEN=your-github-pat
GITHUB_REPO=your-org/your-repo
GITHUB_ORGANIZATIONS=your-org

OPENAI_API_KEY=your-openai-key

GOOGLE_SHEET_ID=your-sheet-id
```

---

## FAQ / Q&A

### General

**Q: What does this agent do?**
> Automatically generates test cases for Jira issues, analyzes PRs, and creates detailed reports.

**Q: What tools/technologies are used?**
| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.13 | Runtime |
| OpenAI GPT-4o | Latest | AI test generation |
| Jira Cloud API | v3 | Issue management |
| GitHub REST API | v3 | PR detection |
| Google Sheets API | v4 | Test tracking |
| Slack API | Latest | Notifications |
| Semgrep | Optional | Static analysis |

---

### Jira Setup

**Q: How to get Jira API token?**
1. Go to https://id.atlassian.com/manage-profile/security/api-tokens
2. Click "Create API token"
3. Copy token to `.env` as `JIRA_API_TOKEN`

**Q: How to configure Jira?**
```env
# .env file
JIRA_URL=https://your-org.atlassian.net
JIRA_EMAIL=your-email@company.com
JIRA_API_TOKEN=your-api-token
JIRA_PROJECT=DT
```

---

### GitHub Setup

**Q: How to get GitHub token?**
1. Go to https://github.com/settings/tokens
2. Generate new token (classic)
3. Select scopes: `repo`, `read:org`
4. If using SSO, authorize token for your org

**Q: How to configure GitHub?**
```env
# .env file
GITHUB_TOKEN=your-github-token
GITHUB_REPO=your-org/your-repo
GITHUB_ORGANIZATIONS=your-org
```

---

### OpenAI Setup

**Q: How to get OpenAI API key?**
1. Go to https://platform.openai.com/api-keys
2. Create new secret key
3. Copy to `.env`

**Q: How to configure OpenAI?**
```env
# .env file
OPENAI_API_KEY=sk-xxxxxxxxxxxx
```

---

### Google Sheets Setup

**Q: How to setup Google Sheets?**
1. Go to https://console.cloud.google.com
2. Create project → Enable "Google Sheets API" & "Google Drive API"
3. Create Service Account → Download JSON key
4. Save as `google_credentials.json`
5. Share your Google Sheet with the service account email

**Q: How to configure Google Sheets?**
```env
# .env file
GOOGLE_SHEET_ID=your-sheet-id-from-url
```
> Sheet ID is in URL: `docs.google.com/spreadsheets/d/{SHEET_ID}/edit`

---

### Slack Setup

**Q: How to get Slack webhook URL?**
1. Go to https://api.slack.com/apps
2. Create New App → From scratch
3. Add feature: "Incoming Webhooks" → Activate
4. Click "Add New Webhook to Workspace"
5. Select channel → Copy webhook URL

**Q: How to configure Slack?**
```json
// slack_config.json
{
  "webhook_url": "https://hooks.slack.com/services/YOUR/WEBHOOK/URL",
  "channel": "qaagent",
  "username": "QA Agent",
  "enabled": true
}
```

**Q: How to get Slack Bot Token (alternative)?**
1. Go to https://api.slack.com/apps
2. Create App → OAuth & Permissions
3. Add scopes: `chat:write`, `chat:write.public`
4. Install to workspace → Copy Bot Token (`xoxb-...`)

---

### Troubleshooting

**Q: How to kill everything and restart fresh?**
```bash
# Kill all QA Agent processes
pkill -f "enhanced_qa_agent"
pkill -f "report_server"

# Wait for cleanup
sleep 3

# Restart fresh
cd ./qa-agent
source venv/bin/activate

# Start report server
nohup python report_server.py > report_server.log 2>&1 &

# Start agent
nohup python enhanced_qa_agent.py --interval 30 > agent.log 2>&1 &

# Verify running
sleep 2
ps aux | grep -E "enhanced_qa_agent|report_server" | grep -v grep
```

**Q: One-liner to kill & restart?**
```bash
pkill -f "enhanced_qa_agent"; pkill -f "report_server"; sleep 2; cd ./qa-agent && source venv/bin/activate && nohup python report_server.py > report_server.log 2>&1 & nohup python enhanced_qa_agent.py --interval 30 > agent.log 2>&1 & echo "Restarted!"
```

**Q: Agent not detecting new Jira issues?**
> Check polling interval. Default is 30 seconds. View logs:
```bash
tail -f agent.log | grep "Polling"
```

**Q: Agent not detecting PRs?**
> Ensure PR title/description/branch contains Jira key (e.g., `DT-1234`)
```bash
tail -f agent.log | grep "PR"
```

**Q: Google Sheets not updating?**
> 1. Check if sheet is shared with service account email
> 2. Verify `GOOGLE_SHEET_ID` is correct
> 3. Check `google_credentials.json` exists

**Q: Slack notifications not working?**
> 1. Verify webhook URL in `slack_config.json`
> 2. Check `enabled: true`
> 3. Test manually:
```bash
curl -X POST -H 'Content-type: application/json' \
  --data '{"text":"Test"}' \
  YOUR_WEBHOOK_URL
```

**Q: Reports not generating?**
> Check `test_reports/` folder and logs:
```bash
ls -la test_reports/
tail -f agent.log | grep "report"
```

**Q: How to view HTML reports?**
> Reports served at http://localhost:8080
```bash
python report_server.py
```

---

### Configuration Files Reference

| File | Location | Purpose |
|------|----------|---------|
| `.env` | Root | All API credentials |
| `google_credentials.json` | Root | Google service account |
| `slack_config.json` | Root | Slack webhook/settings |
| `pipeline_config.json` | Root | QA pipeline IDs |
| `product_knowledge.json` | Root | AI knowledge base |
| `component_mapping.json` | Root | PR file → feature mapping |

---

### Common Commands

```bash
# Start agent
python enhanced_qa_agent.py --interval 30

# Start in background
nohup python enhanced_qa_agent.py --interval 30 > agent.log 2>&1 &

# Check status
ps aux | grep enhanced_qa_agent

# Kill agent
pkill -f "enhanced_qa_agent"

# View logs
tail -f agent.log

# Start report server
python report_server.py

# Test Slack
python -c "from slack_notifier import SlackNotifier; s=SlackNotifier(); s._send_message(text='Test')"

# Test Jira connection
python -c "from jira_client import JiraClient; j=JiraClient(); j.connect(); print('OK')"
```

---

## Support

For issues, check:
1. `agent.log` for errors
2. Jira/GitHub API tokens validity
3. Network connectivity
4. Service account permissions (Google Sheets)
