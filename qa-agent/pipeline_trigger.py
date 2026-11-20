"""
Pipeline Trigger Module
Integrates with QA MCP to trigger pipelines based on Jira type
"""

import json
import os
import requests
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from pathlib import Path
from loguru import logger


@dataclass
class PipelineResult:
    """Result of a pipeline trigger"""
    pipeline_id: str
    pipeline_name: str
    success: bool
    message: str
    run_id: Optional[str] = None


class PipelineTrigger:
    """Triggers QA pipelines via MCP based on Jira type"""
    
    def __init__(self, config_path: str = "pipeline_config.json"):
        self.config_path = Path(config_path)
        self.config = self._load_config()
        
        # MCP Server settings
        self.mcp_url = os.getenv("PIPELINE_MCP_URL", "http://localhost:8080/mcp")
        self.api_base_url = os.getenv("PIPELINE_API_BASE_URL", "https://your-pipeline-host.example.com")
        self.bearer_token = None  # Will be loaded from env or config
        
        self._load_credentials()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load pipeline configuration"""
        try:
            if self.config_path.exists():
                with open(self.config_path) as f:
                    config = json.load(f)
                    logger.info(f"✅ Loaded pipeline config from {self.config_path}")
                    return config
        except Exception as e:
            logger.error(f"Failed to load pipeline config: {e}")
        
        return {
            "jira_type_detection": {},
            "pipelines": {},
            "settings": {}
        }
    
    def _load_credentials(self):
        """Load MCP credentials from environment"""
        import os
        from dotenv import load_dotenv
        
        # Try to load from .env
        env_path = Path(__file__).parent / ".env"
        if env_path.exists():
            load_dotenv(env_path)
        
        self.bearer_token = os.getenv("PIPELINE_BEARER_TOKEN") or os.getenv("BEARER_TOKEN")
        
        if not self.bearer_token:
            logger.warning("⚠️ PIPELINE_BEARER_TOKEN not found in environment")
    
    def detect_jira_type(self, jira_summary: str, jira_description: str = "", 
                         components: List[str] = None, project_key: str = "") -> str:
        """
        Detect if Jira is Salesforce or SDLC type
        
        Returns: 'salesforce', 'sdlc', or 'unknown'
        """
        text = f"{jira_summary} {jira_description}".lower()
        components = components or []
        
        detection_config = self.config.get("jira_type_detection", {})
        
        scores = {"salesforce": 0, "sdlc": 0}
        
        for jira_type, rules in detection_config.items():
            # Check keywords
            keywords = rules.get("keywords", [])
            for keyword in keywords:
                if keyword.lower() in text:
                    scores[jira_type] += 2
                    logger.debug(f"Keyword match: '{keyword}' -> {jira_type}")
            
            # Check components
            type_components = rules.get("components", [])
            for comp in components:
                if comp in type_components:
                    scores[jira_type] += 3
                    logger.debug(f"Component match: '{comp}' -> {jira_type}")
            
            # Check project key
            projects = rules.get("projects", [])
            if project_key.upper() in [p.upper() for p in projects]:
                scores[jira_type] += 5
                logger.debug(f"Project match: '{project_key}' -> {jira_type}")
        
        # Determine winner
        if scores["salesforce"] > scores["sdlc"] and scores["salesforce"] > 0:
            detected_type = "salesforce"
        elif scores["sdlc"] > scores["salesforce"] and scores["sdlc"] > 0:
            detected_type = "sdlc"
        else:
            detected_type = "unknown"
        
        logger.info(f"🔍 Jira type detected: {detected_type} (scores: {scores})")
        return detected_type
    
    def get_pipelines_for_type(self, jira_type: str) -> List[Dict[str, str]]:
        """Get pipeline IDs and names for a Jira type"""
        pipelines_config = self.config.get("pipelines", {}).get(jira_type, {})
        
        pipeline_ids = pipelines_config.get("pipeline_ids", [])
        pipeline_names = pipelines_config.get("pipeline_names", [])
        
        pipelines = []
        for i, pid in enumerate(pipeline_ids):
            name = pipeline_names[i] if i < len(pipeline_names) else f"Pipeline-{i+1}"
            pipelines.append({"id": pid, "name": name})
        
        return pipelines
    
    def trigger_pipeline_via_mcp(self, pipeline_id: str, settings: Dict = None) -> PipelineResult:
        """
        Trigger a pipeline using QA MCP API
        
        This method calls the QA API to run a pipeline.
        """
        if not self.bearer_token:
            return PipelineResult(
                pipeline_id=pipeline_id,
                pipeline_name="",
                success=False,
                message="Missing PIPELINE_BEARER_TOKEN"
            )
        
        # Skip placeholder IDs
        if pipeline_id.startswith("PASTE_"):
            logger.warning(f"⚠️ Skipping placeholder pipeline ID: {pipeline_id}")
            return PipelineResult(
                pipeline_id=pipeline_id,
                pipeline_name="",
                success=False,
                message="Placeholder pipeline ID - please configure actual ID"
            )
        
        try:
            # QA API endpoint for running pipelines
            url = f"{self.api_base_url}/api/v2/actions/pipeline/run"
            
            headers = {
                "Authorization": f"Bearer {self.bearer_token}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "targetPipelines": [pipeline_id],
                "settings": settings or {}
            }
            
            logger.info(f"🚀 Triggering pipeline: {pipeline_id}")
            
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                run_id = result.get("runId") or result.get("data", {}).get("runId")
                
                logger.info(f"✅ Pipeline triggered successfully: {pipeline_id}")
                return PipelineResult(
                    pipeline_id=pipeline_id,
                    pipeline_name="",
                    success=True,
                    message="Pipeline triggered successfully",
                    run_id=run_id
                )
            else:
                logger.error(f"❌ Pipeline trigger failed: {response.status_code} - {response.text}")
                return PipelineResult(
                    pipeline_id=pipeline_id,
                    pipeline_name="",
                    success=False,
                    message=f"API error: {response.status_code}"
                )
                
        except Exception as e:
            logger.error(f"❌ Failed to trigger pipeline {pipeline_id}: {e}")
            return PipelineResult(
                pipeline_id=pipeline_id,
                pipeline_name="",
                success=False,
                message=str(e)
            )
    
    def trigger_pipelines_for_jira(
        self, 
        jira_key: str,
        jira_summary: str, 
        jira_description: str = "",
        components: List[str] = None,
        project_key: str = ""
    ) -> Dict[str, Any]:
        """
        Main method: Detect Jira type and trigger appropriate pipelines
        
        Returns summary of triggered pipelines
        """
        # Detect type
        jira_type = self.detect_jira_type(
            jira_summary=jira_summary,
            jira_description=jira_description,
            components=components,
            project_key=project_key
        )
        
        if jira_type == "unknown":
            logger.warning(f"⚠️ Could not determine Jira type for {jira_key}")
            return {
                "jira_key": jira_key,
                "detected_type": "unknown",
                "pipelines_triggered": 0,
                "results": [],
                "message": "Could not determine Jira type - no pipelines triggered"
            }
        
        # Get pipelines for this type
        pipelines = self.get_pipelines_for_type(jira_type)
        
        if not pipelines:
            logger.warning(f"⚠️ No pipelines configured for type: {jira_type}")
            return {
                "jira_key": jira_key,
                "detected_type": jira_type,
                "pipelines_triggered": 0,
                "results": [],
                "message": f"No pipelines configured for {jira_type}"
            }
        
        # Trigger each pipeline
        results = []
        for pipeline in pipelines:
            result = self.trigger_pipeline_via_mcp(
                pipeline_id=pipeline["id"],
                settings={"jira_key": jira_key}
            )
            result.pipeline_name = pipeline["name"]
            results.append(result)
        
        successful = sum(1 for r in results if r.success)
        
        return {
            "jira_key": jira_key,
            "detected_type": jira_type,
            "pipelines_triggered": successful,
            "total_pipelines": len(pipelines),
            "results": [
                {
                    "pipeline_id": r.pipeline_id,
                    "pipeline_name": r.pipeline_name,
                    "success": r.success,
                    "message": r.message,
                    "run_id": r.run_id
                }
                for r in results
            ]
        }
    
    def format_trigger_result_for_jira(self, result: Dict[str, Any]) -> str:
        """Format pipeline trigger results for Jira comment"""
        lines = [
            "h3. 🚀 Pipeline Execution Triggered",
            "",
            f"*Jira Type Detected:* {result['detected_type'].upper()}",
            f"*Pipelines Triggered:* {result['pipelines_triggered']}/{result['total_pipelines']}",
            "",
        ]
        
        if result['results']:
            lines.extend([
                "||Pipeline||Status||Run ID||",
            ])
            
            for r in result['results']:
                status = "✅ Success" if r['success'] else f"❌ {r['message']}"
                run_id = r.get('run_id') or 'N/A'
                lines.append(f"|{r['pipeline_name']}|{status}|{run_id}|")
        
        lines.append("")
        lines.append("_Triggered by QA Agent_")
        
        return "\n".join(lines)


# Singleton instance
_pipeline_trigger = None

def get_pipeline_trigger() -> PipelineTrigger:
    """Get singleton pipeline trigger instance"""
    global _pipeline_trigger
    if _pipeline_trigger is None:
        _pipeline_trigger = PipelineTrigger()
    return _pipeline_trigger


if __name__ == "__main__":
    # Test the pipeline trigger
    trigger = PipelineTrigger()
    
    # Test detection
    test_cases = [
        ("Implement Apex trigger for account updates", "salesforce"),
        ("Deploy new REST API endpoint", "sdlc"),
        ("Fix Lightning component bug", "salesforce"),
        ("Kubernetes deployment update", "sdlc"),
    ]
    
    print("🧪 Testing Jira Type Detection:\n")
    for summary, expected in test_cases:
        detected = trigger.detect_jira_type(summary)
        status = "✅" if detected == expected else "❌"
        print(f"{status} '{summary[:40]}...' -> {detected} (expected: {expected})")




