"""
GitHub Integration Client
Handles fetching PR details and repository files
"""

import base64
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from github import Github, GithubException
from github.PullRequest import PullRequest
from github.Repository import Repository
from loguru import logger

from config import settings


@dataclass
class PRFile:
    """Represents a file changed in a PR"""
    filename: str
    status: str  # added, removed, modified, renamed
    additions: int
    deletions: int
    changes: int
    patch: Optional[str]
    content: Optional[str] = None


@dataclass
class PRDetails:
    """Represents Pull Request details"""
    number: int
    title: str
    description: str
    state: str
    author: str
    branch: str
    base_branch: str
    files_changed: List[PRFile]
    commits_count: int
    additions: int
    deletions: int
    labels: List[str]
    url: str
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RepoFile:
    """Represents a file from the repository"""
    path: str
    content: str
    size: int
    encoding: str


class GitHubClient:
    """Client for interacting with GitHub API"""
    
    def __init__(self):
        self.config = settings.github
        self._client: Optional[Github] = None
        self._repo: Optional[Repository] = None
        self._repo_cache: Dict[str, Repository] = {}  # Cache for repos
    
    def connect(self) -> bool:
        """Establish connection to GitHub"""
        try:
            self._client = Github(
                self.config.token,
                base_url=self.config.api_url if "api.github.com" not in self.config.api_url else "https://api.github.com"
            )
            # Test connection
            user = self._client.get_user()
            logger.info(f"✅ Connected to GitHub as: {user.login}")
            
            # Get the default repository
            if self.config.repo:
                self._repo = self._client.get_repo(self.config.repo)
                self._repo_cache[self.config.repo] = self._repo
                logger.info(f"✅ Default repository loaded: {self._repo.full_name}")
            
            # Log configured organizations
            orgs = self.config.organizations_list
            if orgs:
                logger.info(f"✅ Configured organizations: {', '.join(orgs)}")
            
            return True
        except Exception as e:
            logger.error(f"❌ Failed to connect to GitHub: {e}")
            return False
    
    def get_repo_by_name(self, repo_full_name: str) -> Optional[Repository]:
        """Get a repository by full name (org/repo), with caching"""
        if repo_full_name in self._repo_cache:
            return self._repo_cache[repo_full_name]
        try:
            repo = self.client.get_repo(repo_full_name)
            self._repo_cache[repo_full_name] = repo
            return repo
        except Exception as e:
            logger.warning(f"Could not access repo {repo_full_name}: {e}")
            return None
    
    def get_org_repos(self, org_name: str, max_repos: int = 100) -> List[Repository]:
        """Get all repositories for an organization"""
        try:
            org = self.client.get_organization(org_name)
            repos = list(org.get_repos(type='all', sort='updated')[:max_repos])
            logger.info(f"Found {len(repos)} repos in {org_name}")
            return repos
        except Exception as e:
            logger.warning(f"Could not fetch repos for org {org_name}: {e}")
            return []
    
    @property
    def client(self) -> Github:
        """Get the GitHub client, connecting if necessary"""
        if self._client is None:
            self.connect()
        return self._client
    
    @property
    def repo(self) -> Repository:
        """Get the repository object"""
        if self._repo is None:
            self.connect()
        return self._repo
    
    def get_pr(self, pr_number: int) -> Optional[PRDetails]:
        """Fetch PR details by number"""
        try:
            pr = self.repo.get_pull(pr_number)
            return self._parse_pr(pr)
        except GithubException as e:
            logger.error(f"Failed to fetch PR #{pr_number}: {e}")
            return None
    
    def get_open_prs(self, max_results: int = 10) -> List[PRDetails]:
        """Get open pull requests"""
        try:
            prs = self.repo.get_pulls(state='open', sort='updated', direction='desc')
            return [self._parse_pr(pr) for pr in list(prs)[:max_results]]
        except Exception as e:
            logger.error(f"Failed to fetch open PRs: {e}")
            return []
    
    def search_prs_by_jira_key(self, jira_key: str, specific_repo: str = None) -> List[PRDetails]:
        """
        Search for PRs that mention a Jira key across all configured organizations.
        
        Args:
            jira_key: The Jira issue key (e.g., DT-1234)
            specific_repo: Optional specific repo to search (org/repo format)
        
        Returns:
            List of PRDetails matching the Jira key
        """
        try:
            # Ensure connected
            if self._client is None:
                self.connect()
            
            prs = []
            found_prs = set()  # Track by "repo:pr_number" to avoid duplicates
            
            # Determine which repos to search
            repos_to_search = []
            
            if specific_repo:
                # Search specific repo only
                repo = self.get_repo_by_name(specific_repo)
                if repo:
                    repos_to_search.append(repo)
            else:
                # Search across all configured organizations
                orgs = self.config.organizations_list
                if orgs:
                    logger.info(f"Searching PRs in organizations: {orgs}")
                    for org_name in orgs:
                        repos_to_search.extend(self.get_org_repos(org_name))
                
                # Also include default repo if not already in list
                if self.config.repo and self._repo:
                    if self._repo not in repos_to_search:
                        repos_to_search.append(self._repo)
            
            logger.info(f"Searching {len(repos_to_search)} repos for {jira_key}")
            
            # Search across all repos
            for repo in repos_to_search:
                repo_full_name = repo.full_name
                
                # 1. Search in PR titles and body using GitHub search API
                for search_location in ['title', 'body']:
                    try:
                        query = f"repo:{repo_full_name} {jira_key} in:{search_location} is:pr"
                        issues = self.client.search_issues(query)
                        for issue in issues:
                            pr_key = f"{repo_full_name}:{issue.number}"
                            if pr_key not in found_prs:
                                pr = repo.get_pull(issue.number)
                                pr_details = self._parse_pr(pr, repo_full_name)
                                prs.append(pr_details)
                                found_prs.add(pr_key)
                                logger.info(f"Found PR {repo_full_name}#{issue.number} by {search_location} search")
                    except Exception as e:
                        logger.debug(f"{search_location} search failed for {repo_full_name}: {e}")
                
                # 2. Check branch names in PRs (open and closed)
                for state in ['open', 'closed']:
                    try:
                        all_prs = repo.get_pulls(state=state, sort='updated', direction='desc')
                        # Check recent PRs (last 30 per state)
                        for i, pr in enumerate(all_prs):
                            if i >= 30:
                                break
                            pr_key = f"{repo_full_name}:{pr.number}"
                            if pr_key not in found_prs:
                                # Check branch name or title
                                if (jira_key.lower() in pr.head.ref.lower() or 
                                    jira_key.lower() in pr.title.lower()):
                                    pr_details = self._parse_pr(pr, repo_full_name)
                                    prs.append(pr_details)
                                    found_prs.add(pr_key)
                                    logger.info(f"Found PR {repo_full_name}#{pr.number} by branch/title ({pr.head.ref})")
                    except Exception as e:
                        logger.debug(f"Branch search ({state}) failed for {repo_full_name}: {e}")
            
            logger.info(f"Total PRs found for {jira_key}: {len(prs)} across {len(repos_to_search)} repos")
            return prs
            
        except Exception as e:
            logger.error(f"Failed to search PRs for {jira_key}: {e}")
            return []
    
    def _parse_pr(self, pr: PullRequest, repo_name: str = None) -> PRDetails:
        """Parse GitHub PR into our dataclass"""
        files_changed = []
        
        try:
            for f in pr.get_files():
                files_changed.append(PRFile(
                    filename=f.filename,
                    status=f.status,
                    additions=f.additions,
                    deletions=f.deletions,
                    changes=f.changes,
                    patch=f.patch
                ))
        except Exception as e:
            logger.warning(f"Could not fetch files for PR #{pr.number}: {e}")
        
        return PRDetails(
            number=pr.number,
            title=pr.title,
            description=pr.body or "",
            state=pr.state,
            author=pr.user.login,
            branch=pr.head.ref,
            base_branch=pr.base.ref,
            files_changed=files_changed,
            commits_count=pr.commits,
            additions=pr.additions,
            deletions=pr.deletions,
            labels=[label.name for label in pr.labels],
            url=pr.html_url,
            raw_data={"repo": repo_name or self.config.repo}
        )
    
    def get_file_content(self, file_path: str, ref: str = "main") -> Optional[RepoFile]:
        """Get content of a specific file from the repository"""
        try:
            content = self.repo.get_contents(file_path, ref=ref)
            
            if isinstance(content, list):
                logger.warning(f"{file_path} is a directory, not a file")
                return None
            
            decoded_content = ""
            if content.encoding == "base64":
                decoded_content = base64.b64decode(content.content).decode('utf-8')
            else:
                decoded_content = content.content
            
            return RepoFile(
                path=content.path,
                content=decoded_content,
                size=content.size,
                encoding=content.encoding
            )
        except GithubException as e:
            logger.error(f"Failed to fetch file {file_path}: {e}")
            return None
    
    def get_pr_file_contents(self, pr: PRDetails, max_files: int = None) -> List[RepoFile]:
        """Get the full content of files changed in a PR"""
        max_files = max_files or settings.agent.max_files_to_read
        files = []
        
        for pr_file in pr.files_changed[:max_files]:
            if pr_file.status == "removed":
                continue
            
            # Filter by extension
            if not any(pr_file.filename.endswith(ext) for ext in settings.agent.include_extensions_list):
                continue
            
            # Skip excluded directories
            if any(excluded in pr_file.filename for excluded in settings.agent.exclude_dirs_list):
                continue
            
            content = self.get_file_content(pr_file.filename, ref=pr.branch)
            if content:
                files.append(content)
        
        return files
    
    def get_directory_files(
        self, 
        directory: str = "", 
        ref: str = "main",
        max_files: int = None
    ) -> List[RepoFile]:
        """Recursively get files from a directory"""
        max_files = max_files or settings.agent.max_files_to_read
        files = []
        
        try:
            contents = self.repo.get_contents(directory, ref=ref)
            self._collect_files(contents, ref, files, max_files)
        except Exception as e:
            logger.error(f"Failed to fetch directory {directory}: {e}")
        
        return files[:max_files]
    
    def _collect_files(
        self, 
        contents, 
        ref: str, 
        files: List[RepoFile], 
        max_files: int
    ):
        """Recursively collect files"""
        if len(files) >= max_files:
            return
        
        if not isinstance(contents, list):
            contents = [contents]
        
        for content in contents:
            if len(files) >= max_files:
                break
            
            # Skip excluded directories
            if any(excluded in content.path for excluded in settings.agent.exclude_dirs_list):
                continue
            
            if content.type == "dir":
                try:
                    sub_contents = self.repo.get_contents(content.path, ref=ref)
                    self._collect_files(sub_contents, ref, files, max_files)
                except Exception:
                    pass
            else:
                # Filter by extension
                if any(content.path.endswith(ext) for ext in settings.agent.include_extensions_list):
                    try:
                        decoded = ""
                        if content.encoding == "base64":
                            decoded = base64.b64decode(content.content).decode('utf-8')
                        else:
                            decoded = content.content or ""
                        
                        files.append(RepoFile(
                            path=content.path,
                            content=decoded,
                            size=content.size,
                            encoding=content.encoding
                        ))
                    except Exception as e:
                        logger.warning(f"Could not decode {content.path}: {e}")
    
    def add_pr_comment(self, pr_number: int, comment: str) -> bool:
        """Add a comment to a PR"""
        try:
            pr = self.repo.get_pull(pr_number)
            pr.create_issue_comment(comment)
            logger.info(f"Added comment to PR #{pr_number}")
            return True
        except Exception as e:
            logger.error(f"Failed to add comment to PR #{pr_number}: {e}")
            return False

