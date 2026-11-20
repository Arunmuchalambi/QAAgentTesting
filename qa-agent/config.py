"""
Configuration management for QA Agent
"""

import os
from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import Field
from dotenv import load_dotenv
from pathlib import Path

# Load from .env or credentials.env (whichever exists)
env_path = Path(__file__).parent / ".env"
credentials_path = Path(__file__).parent / "credentials.env"

if env_path.exists():
    load_dotenv(env_path)
elif credentials_path.exists():
    load_dotenv(credentials_path)
else:
    load_dotenv()  # Try default


class JiraConfig(BaseSettings):
    """Jira configuration settings"""
    server: str = Field(default="", alias="JIRA_SERVER")
    email: str = Field(default="", alias="JIRA_EMAIL")
    api_token: str = Field(default="", alias="JIRA_API_TOKEN")
    project_key: str = Field(default="", alias="JIRA_PROJECT_KEY")
    webhook_secret: Optional[str] = Field(default=None, alias="JIRA_WEBHOOK_SECRET")

    class Config:
        env_file = ".env"
        extra = "ignore"


class GitHubConfig(BaseSettings):
    """GitHub configuration settings"""
    token: str = Field(default="", alias="GITHUB_TOKEN")
    repo: str = Field(default="", alias="GITHUB_REPO")  # Default/primary repo
    api_url: str = Field(default="https://api.github.com", alias="GITHUB_API_URL")
    # Multiple organizations to search (comma-separated)
    organizations: str = Field(default="", alias="GITHUB_ORGANIZATIONS")

    class Config:
        env_file = ".env"
        extra = "ignore"
    
    @property
    def organizations_list(self) -> List[str]:
        """Get list of organizations to search"""
        if self.organizations:
            return [org.strip() for org in self.organizations.split(",") if org.strip()]
        # Fallback: extract org from repo if no orgs specified
        if self.repo and "/" in self.repo:
            return [self.repo.split("/")[0]]
        return []


class OpenAIConfig(BaseSettings):
    """OpenAI configuration settings"""
    api_key: str = Field(default="", alias="OPENAI_API_KEY")
    model: str = Field(default="gpt-4", alias="OPENAI_MODEL")

    class Config:
        env_file = ".env"
        extra = "ignore"


class AgentConfig(BaseSettings):
    """Agent behavior configuration"""
    max_files_to_read: int = Field(default=20, alias="MAX_FILES_TO_READ")
    include_extensions: str = Field(
        default=".py,.js,.ts,.java,.go,.rs,.cpp,.c,.h,.jsx,.tsx",
        alias="INCLUDE_EXTENSIONS"
    )
    exclude_dirs: str = Field(
        default="node_modules,venv,.git,__pycache__,dist,build,.next",
        alias="EXCLUDE_DIRS"
    )
    output_dir: str = Field(default="./generated_tests", alias="OUTPUT_DIR")
    webhook_port: int = Field(default=8000, alias="WEBHOOK_PORT")

    class Config:
        env_file = ".env"
        extra = "ignore"

    @property
    def include_extensions_list(self) -> List[str]:
        return [ext.strip() for ext in self.include_extensions.split(",")]

    @property
    def exclude_dirs_list(self) -> List[str]:
        return [d.strip() for d in self.exclude_dirs.split(",")]


class Settings:
    """Main settings container"""
    def __init__(self):
        self.jira = JiraConfig()
        self.github = GitHubConfig()
        self.openai = OpenAIConfig()
        self.agent = AgentConfig()

    def validate(self) -> List[str]:
        """Validate all required settings are present"""
        errors = []
        
        if not self.jira.server:
            errors.append("JIRA_SERVER is required")
        if not self.jira.email:
            errors.append("JIRA_EMAIL is required")
        if not self.jira.api_token:
            errors.append("JIRA_API_TOKEN is required")
        if not self.github.token:
            errors.append("GITHUB_TOKEN is required")
        if not self.github.repo:
            errors.append("GITHUB_REPO is required")
        if not self.openai.api_key:
            errors.append("OPENAI_API_KEY is required")
            
        return errors


# Global settings instance
settings = Settings()

