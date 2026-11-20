"""
Product Knowledge Base Service
Provides context from product documentation to enhance test case generation
"""

import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from loguru import logger


@dataclass
class FeatureMatch:
    """Represents a matched product feature"""
    feature_key: str
    feature_name: str
    description: str
    match_score: float
    matched_keywords: List[str]
    test_focus: List[str]
    test_types: List[str]
    critical_areas: List[str]


class ProductKnowledge:
    """Service to provide product context for test generation"""
    
    def __init__(self, knowledge_file: str = "product_knowledge.json"):
        self.knowledge_path = Path(__file__).parent / knowledge_file
        self.knowledge = self._load_knowledge()
        logger.info(f"✅ Loaded product knowledge base with {len(self.knowledge.get('features', {}))} features")
    
    def _load_knowledge(self) -> Dict:
        """Load the knowledge base"""
        if self.knowledge_path.exists():
            with open(self.knowledge_path) as f:
                return json.load(f)
        logger.warning(f"Knowledge file not found: {self.knowledge_path}")
        return {"features": {}}
    
    def find_relevant_features(
        self, 
        text: str, 
        min_score: float = 0.1
    ) -> List[FeatureMatch]:
        """
        Find product features relevant to the given text (Jira description, PR content, etc.)
        
        Args:
            text: Text to search for feature matches
            min_score: Minimum match score (0-1) to include
            
        Returns:
            List of matched features sorted by relevance
        """
        if not text:
            return []
        
        text_lower = text.lower()
        matches = []
        
        for feature_key, feature_data in self.knowledge.get("features", {}).items():
            keywords = feature_data.get("keywords", [])
            matched_keywords = []
            
            # Check each keyword
            for keyword in keywords:
                # Use word boundary matching for better accuracy
                pattern = r'\b' + re.escape(keyword.lower()) + r'\b'
                if re.search(pattern, text_lower):
                    matched_keywords.append(keyword)
            
            if matched_keywords:
                # Calculate score based on keyword matches
                score = len(matched_keywords) / len(keywords) if keywords else 0
                
                # Boost score if feature name is mentioned
                feature_name = feature_data.get("name", "").lower()
                if feature_name and feature_name in text_lower:
                    score = min(1.0, score + 0.3)
                
                if score >= min_score:
                    matches.append(FeatureMatch(
                        feature_key=feature_key,
                        feature_name=feature_data.get("name", feature_key),
                        description=feature_data.get("description", ""),
                        match_score=score,
                        matched_keywords=matched_keywords,
                        test_focus=feature_data.get("test_focus", []),
                        test_types=feature_data.get("test_types", []),
                        critical_areas=feature_data.get("critical_areas", [])
                    ))
        
        # Sort by score descending
        matches.sort(key=lambda x: x.match_score, reverse=True)
        return matches
    
    def get_feature_context(self, feature_key: str) -> Optional[Dict]:
        """Get full context for a specific feature"""
        return self.knowledge.get("features", {}).get(feature_key)
    
    def get_test_context_for_jira(
        self, 
        jira_summary: str, 
        jira_description: str,
        components: List[str] = None
    ) -> Dict[str, Any]:
        """
        Get comprehensive test context for a Jira issue
        
        Args:
            jira_summary: Jira issue summary/title
            jira_description: Jira issue description
            components: Jira components if any
            
        Returns:
            Dictionary with relevant product context
        """
        # Combine all text for matching
        combined_text = f"{jira_summary} {jira_description}"
        if components:
            combined_text += " " + " ".join(components)
        
        # Find matching features
        matches = self.find_relevant_features(combined_text)
        
        if not matches:
            return {
                "has_context": False,
                "features": [],
                "recommended_test_focus": [],
                "recommended_test_types": ["functional", "integration"],
                "critical_areas": [],
                "context_summary": "No specific product feature context found. Using general testing approach."
            }
        
        # Aggregate context from all matches
        all_test_focus = []
        all_test_types = set()
        all_critical_areas = []
        feature_summaries = []
        
        for match in matches[:3]:  # Top 3 matches
            all_test_focus.extend(match.test_focus[:3])  # Top 3 focus areas per feature
            all_test_types.update(match.test_types)
            all_critical_areas.extend(match.critical_areas)
            feature_summaries.append(f"{match.feature_name}: {match.description}")
        
        return {
            "has_context": True,
            "features": [
                {
                    "name": m.feature_name,
                    "description": m.description,
                    "score": m.match_score,
                    "matched_keywords": m.matched_keywords,
                    "test_focus": m.test_focus
                }
                for m in matches[:3]
            ],
            "recommended_test_focus": list(set(all_test_focus))[:10],
            "recommended_test_types": list(all_test_types),
            "critical_areas": list(set(all_critical_areas)),
            "context_summary": f"Related to: {', '.join([m.feature_name for m in matches[:3]])}"
        }
    
    def format_context_for_prompt(self, context: Dict[str, Any]) -> str:
        """Format context for inclusion in AI prompt"""
        if not context.get("has_context"):
            return ""
        
        lines = [
            "\n## QA Platform Context",
            ""
        ]
        
        for feature in context.get("features", []):
            lines.append(f"**{feature['name']}**: {feature['description']}")
            if feature.get("test_focus"):
                lines.append(f"  Key test areas: {', '.join(feature['test_focus'][:5])}")
            lines.append("")
        
        if context.get("recommended_test_focus"):
            lines.append(f"**Recommended Test Focus:** {', '.join(context['recommended_test_focus'][:5])}")
        
        if context.get("critical_areas"):
            lines.append(f"**Critical Areas:** {', '.join(context['critical_areas'])}")
        
        return "\n".join(lines)


# Singleton instance
_knowledge_service = None

def get_product_knowledge() -> ProductKnowledge:
    """Get or create the knowledge service singleton"""
    global _knowledge_service
    if _knowledge_service is None:
        _knowledge_service = ProductKnowledge()
    return _knowledge_service


# Test the service
if __name__ == "__main__":
    from rich.console import Console
    from rich.table import Table
    
    console = Console()
    knowledge = ProductKnowledge()
    
    # Test cases
    test_texts = [
        "Salesforce: Enable Jira Ticket Selection for apex deployment",
        "Migrate Gradle Build from Jenkins to Native Pipeline",
        "Fix DORA metrics dashboard not showing correct lead time",
        "Implement Kafka consumer for order events processing",
        "Add Terraform support for AWS EKS deployment",
        "Update approval gate workflow for production deployments"
    ]
    
    for text in test_texts:
        console.print(f"\n[bold]Testing:[/bold] {text}")
        context = knowledge.get_test_context_for_jira(text, "")
        
        if context["has_context"]:
            console.print(f"[green]✅ Found context![/green]")
            for f in context["features"]:
                console.print(f"  - {f['name']} (score: {f['score']:.2f})")
                console.print(f"    Keywords: {', '.join(f['matched_keywords'][:5])}")
        else:
            console.print("[yellow]⚠️ No specific context found[/yellow]")




