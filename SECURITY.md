# Security / Credential Protection

## Never commit secrets

Keep these files **local only** (they are gitignored):

- `qa-agent/.env`
- `qa-agent/credentials.env`
- `qa-agent/google_credentials.json`
- `qa-agent/slack_config.json`

Use templates instead:

- `qa-agent/env.example`
- `qa-agent/slack_config.example.json`

## Where credentials live

| Secret | Location |
|--------|----------|
| Jira / GitHub / LLM keys | `qa-agent/.env` |
| Google service account | `qa-agent/google_credentials.json` |
| Slack webhook/token | `qa-agent/slack_config.json` |
| CI dummy values only | GitHub Actions workflow `env:` (never production secrets) |

## CI protection

PRs to `main` run:

1. **Secret Protection** — blocks tracked credential files and common live-token patterns; runs Gitleaks
2. **CI Release Gate** — compile + smoke tests with dummy env values

## If a secret was exposed

1. Rotate it immediately (Jira, GitHub, Gemini/OpenAI, Slack, Google SA key)
2. Remove it from git history if it was committed
3. Put the new value only in local `.env` / ignored JSON files
