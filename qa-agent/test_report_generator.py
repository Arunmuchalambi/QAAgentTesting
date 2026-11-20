"""
Test Report Generator - Creates HTML/PDF reports from test execution results
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from loguru import logger

from api_executor import TestExecutionSummary, TestResult, TestStatus


@dataclass
class ReportConfig:
    """Configuration for report generation"""
    output_dir: str = "test_reports"
    include_request_details: bool = True
    include_response_details: bool = True
    include_suggestions: bool = True
    max_response_length: int = 2000
    company_name: str = "QA Agent"
    theme_color: str = "#4F46E5"  # Indigo


class TestReportGenerator:
    """Generates beautiful HTML reports from test execution results"""
    
    def __init__(self, config: ReportConfig = None):
        self.config = config or ReportConfig()
        os.makedirs(self.config.output_dir, exist_ok=True)
    
    def generate_html_report(
        self,
        summary: TestExecutionSummary,
        jira_key: str,
        pr_number: int = None,
        additional_info: Dict[str, Any] = None,
        code_quality: Any = None,
        code_alignment: Any = None
    ) -> str:
        """Generate HTML report and return file path
        
        Args:
            summary: Test execution summary
            jira_key: Jira issue key
            pr_number: PR number (optional)
            additional_info: Additional info to include in report
            code_quality: CodeQualityReport from analyzer
            code_alignment: CodeAlignmentReport from analyzer
        
        Returns:
            Path to generated HTML file
        """
        
        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pr_suffix = f"_PR{pr_number}" if pr_number else ""
        filename = f"Test_Case_Outcome{pr_suffix}_{jira_key}_{timestamp}.html"
        filepath = os.path.join(self.config.output_dir, filename)
        
        # Generate HTML content
        html_content = self._generate_html(
            summary, jira_key, pr_number, additional_info,
            code_quality=code_quality, code_alignment=code_alignment
        )
        
        # Write to file
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        logger.info(f"Generated HTML report: {filepath}")
        return filepath
    
    def _generate_html(
        self,
        summary: TestExecutionSummary,
        jira_key: str,
        pr_number: int = None,
        additional_info: Dict[str, Any] = None,
        code_quality: Any = None,
        code_alignment: Any = None
    ) -> str:
        """Generate the HTML content"""
        
        # Store code analysis results for use in the template
        self._code_quality = code_quality
        self._code_alignment = code_alignment
        
        # Calculate percentages
        pass_rate = (summary.passed / summary.total_tests * 100) if summary.total_tests > 0 else 0
        
        # Determine overall status color
        if summary.overall_status == TestStatus.PASSED:
            status_color = "#10B981"  # Green
            status_bg = "#D1FAE5"
            status_text = "✅ ALL TESTS PASSED"
        else:
            status_color = "#EF4444"  # Red
            status_bg = "#FEE2E2"
            status_text = "❌ TESTS FAILED"
        
        # Build URLs
        jira_url = f"https://your-domain.atlassian.net/browse/{jira_key}"
        github_repo = "your-org/your-repo"  # Default repo
        pr_url = f"https://github.com/{github_repo}/pull/{pr_number}" if pr_number else "#"
        
        html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Test Case Outcome - PR #{pr_number or 'N/A'} - {jira_key}</title>
    <style>
        :root {{
            --primary-color: {self.config.theme_color};
            --success-color: #10B981;
            --error-color: #EF4444;
            --warning-color: #F59E0B;
            --info-color: #3B82F6;
            --gray-100: #F3F4F6;
            --gray-200: #E5E7EB;
            --gray-300: #D1D5DB;
            --gray-600: #4B5563;
            --gray-800: #1F2937;
        }}
        
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }}
        
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 16px;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25);
            overflow: hidden;
        }}
        
        /* Header */
        .header {{
            background: linear-gradient(135deg, var(--primary-color) 0%, #7C3AED 100%);
            color: white;
            padding: 20px 40px;
            display: flex;
            align-items: center;
            position: relative;
        }}
        
        .header-left {{
            display: flex;
            align-items: center;
            gap: 15px;
            position: absolute;
            left: 40px;
        }}
        
        .header-logo {{
            width: 80px;
            height: auto;
            /* No filter - show original purple/gold colors */
        }}
        
        .header-brand {{
            font-weight: bold;
            font-size: 22px;
            letter-spacing: 1px;
        }}
        
        .header-center {{
            text-align: center;
            width: 100%;
        }}
        
        .header-center h1 {{
            font-size: 24px;
            margin: 0 0 8px 0;
        }}
        
        .header-center .subtitle {{
            font-size: 14px;
        }}
        
        .header-center .subtitle a {{
            color: #FFD700;
            text-decoration: none;
            font-weight: bold;
            padding: 2px 8px;
            background: rgba(255,255,255,0.2);
            border-radius: 4px;
            transition: background 0.2s;
        }}
        
        .header-center .subtitle a:hover {{
            background: rgba(255,255,255,0.3);
            text-decoration: underline;
        }}
        
        /* Status Banner */
        .status-banner {{
            background: {status_bg};
            color: {status_color};
            padding: 12px 40px;
            font-size: 16px;
            font-weight: bold;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            border-bottom: 2px solid {status_color};
            text-align: center;
        }}
        
        /* Summary Cards */
        .summary-section {{
            padding: 20px 40px;
            background: var(--gray-100);
        }}
        
        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
            gap: 12px;
            margin-bottom: 12px;
        }}
        
        /* Progress Circle */
        .progress-circle-container {{
            display: flex;
            justify-content: center;
            gap: 40px;
            margin: 30px 0;
            flex-wrap: wrap;
        }}
        
        .progress-circle-item {{
            text-align: center;
        }}
        
        .progress-circle {{
            position: relative;
            width: 150px;
            height: 150px;
        }}
        
        .progress-circle svg {{
            transform: rotate(-90deg);
        }}
        
        .progress-circle .bg {{
            fill: none;
            stroke: var(--gray-200);
            stroke-width: 10;
        }}
        
        .progress-circle .progress {{
            fill: none;
            stroke-width: 10;
            stroke-linecap: round;
            transition: stroke-dashoffset 0.5s ease;
        }}
        
        .progress-circle .progress.pass {{ stroke: var(--success-color); }}
        .progress-circle .progress.align {{ stroke: var(--info-color); }}
        .progress-circle .progress.quality {{ stroke: #8B5CF6; }}
        
        .progress-circle .percentage {{
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            font-size: 28px;
            font-weight: bold;
            color: var(--gray-800);
        }}
        
        .progress-circle-label {{
            margin-top: 10px;
            font-weight: 600;
            color: var(--gray-600);
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
        }}
        
        .info-icon {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 18px;
            height: 18px;
            background: #56508B;
            color: white;
            border-radius: 50%;
            font-size: 12px;
            font-weight: bold;
            font-style: normal;
            cursor: help;
            position: relative;
            margin-left: 6px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.3);
            z-index: 10;
        }}
        
        .info-icon:hover {{
            background: #3D3A5C;
            transform: scale(1.15);
            z-index: 1000;
        }}
        
        .info-icon .tooltip {{
            visibility: hidden;
            opacity: 0;
            position: absolute;
            bottom: 130%;
            left: 50%;
            transform: translateX(-50%);
            background: var(--gray-800);
            color: white;
            padding: 12px 16px;
            border-radius: 8px;
            font-size: 12px;
            font-weight: normal;
            font-style: normal;
            width: 280px;
            text-align: left;
            line-height: 1.5;
            z-index: 9999;
            box-shadow: 0 4px 12px rgba(0,0,0,0.4);
            transition: opacity 0.2s, visibility 0.2s;
        }}
        
        .info-icon .tooltip::after {{
            content: '';
            position: absolute;
            top: 100%;
            left: 50%;
            transform: translateX(-50%);
            border: 8px solid transparent;
            border-top-color: var(--gray-800);
        }}
        
        .info-icon:hover .tooltip {{
            visibility: visible;
            opacity: 1;
        }}
        
        .tooltip-title {{
            font-weight: bold;
            margin-bottom: 6px;
            color: #FFD700;
        }}
        
        /* Code Quality Section */
        .code-quality-section {{
            padding: 30px 40px;
            background: linear-gradient(135deg, #F0FDF4 0%, #ECFDF5 100%);
            border-top: 3px solid var(--success-color);
        }}
        
        .quality-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }}
        
        .quality-card {{
            background: white;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        }}
        
        .quality-card h4 {{
            color: var(--gray-800);
            margin-bottom: 10px;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        
        .quality-card ul {{
            list-style: none;
            padding: 0;
        }}
        
        .quality-card li {{
            padding: 8px 0;
            border-bottom: 1px solid var(--gray-100);
            color: var(--gray-600);
            font-size: 14px;
        }}
        
        .quality-card li:last-child {{
            border-bottom: none;
        }}
        
        .quality-badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: bold;
        }}
        
        .quality-badge.good {{ background: #D1FAE5; color: #059669; }}
        .quality-badge.warning {{ background: #FEF3C7; color: #D97706; }}
        .quality-badge.critical {{ background: #FEE2E2; color: #DC2626; }}
        
        .summary-card {{
            background: rgba(255, 255, 255, 0.7);
            padding: 12px 16px;
            border-radius: 10px;
            text-align: center;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
        }}
        
        .summary-card .value {{
            font-size: 28px;
            font-weight: bold;
            color: var(--gray-800);
        }}
        
        .summary-card .label {{
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--gray-600);
            margin-top: 3px;
        }}
        
        .summary-card.passed .value {{ color: var(--success-color); }}
        .summary-card.failed .value {{ color: var(--error-color); }}
        .summary-card.errors .value {{ color: var(--warning-color); }}
        
        /* Progress Bar */
        .progress-container {{
            background: rgba(255, 255, 255, 0.6);
            padding: 12px;
            border-radius: 10px;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
        }}
        
        .progress-bar {{
            height: 24px;
            background: var(--gray-200);
            border-radius: 12px;
            overflow: hidden;
            display: flex;
        }}
        
        .progress-segment {{
            height: 100%;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: bold;
            font-size: 12px;
        }}
        
        .progress-segment.passed {{ background: var(--success-color); }}
        .progress-segment.failed {{ background: var(--error-color); }}
        .progress-segment.errors {{ background: var(--warning-color); }}
        .progress-segment.skipped {{ background: var(--gray-400); }}
        
        /* Test Results Section */
        .results-section {{
            padding: 30px 40px;
        }}
        
        .section-title {{
            font-size: 20px;
            font-weight: bold;
            color: var(--gray-800);
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid var(--gray-200);
        }}
        
        /* Test Card */
        .test-card {{
            background: white;
            border: 1px solid var(--gray-200);
            border-radius: 12px;
            margin-bottom: 20px;
            overflow: hidden;
            transition: box-shadow 0.2s;
        }}
        
        .test-card:hover {{
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
        }}
        
        .test-header {{
            padding: 15px 20px;
            display: flex;
            align-items: center;
            gap: 15px;
            cursor: pointer;
            background: var(--gray-100);
        }}
        
        .test-header.passed {{ border-left: 4px solid var(--success-color); }}
        .test-header.failed {{ border-left: 4px solid var(--error-color); }}
        .test-header.error {{ border-left: 4px solid var(--warning-color); }}
        
        .status-badge {{
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: bold;
            text-transform: uppercase;
        }}
        
        .status-badge.passed {{ background: #D1FAE5; color: var(--success-color); }}
        .status-badge.failed {{ background: #FEE2E2; color: var(--error-color); }}
        .status-badge.error {{ background: #FEF3C7; color: var(--warning-color); }}
        
        .test-name {{
            flex: 1;
            font-weight: 600;
            color: var(--gray-800);
        }}
        
        .test-time {{
            color: var(--gray-600);
            font-size: 14px;
        }}
        
        .test-body {{
            padding: 20px;
            display: none;
        }}
        
        .test-card.expanded .test-body {{
            display: block;
        }}
        
        .test-card.expanded .test-header .expand-icon {{
            transform: rotate(180deg);
        }}
        
        .expand-icon {{
            transition: transform 0.2s;
        }}
        
        /* Request/Response */
        .request-response {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-top: 15px;
        }}
        
        @media (max-width: 768px) {{
            .request-response {{
                grid-template-columns: 1fr;
            }}
        }}
        
        .code-block {{
            background: #1E1E1E;
            color: #D4D4D4;
            padding: 15px;
            border-radius: 8px;
            overflow-x: auto;
            font-family: 'Consolas', 'Monaco', monospace;
            font-size: 13px;
            max-height: 300px;
            overflow-y: auto;
        }}
        
        .code-block .key {{ color: #9CDCFE; }}
        .code-block .string {{ color: #CE9178; }}
        .code-block .number {{ color: #B5CEA8; }}
        
        /* Assertions */
        .assertions {{
            margin-top: 15px;
        }}
        
        .assertion {{
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 10px;
            background: var(--gray-100);
            border-radius: 8px;
            margin-bottom: 8px;
        }}
        
        .assertion.passed {{ background: #D1FAE5; }}
        .assertion.failed {{ background: #FEE2E2; }}
        
        .assertion-icon {{
            font-size: 18px;
        }}
        
        /* Suggestions */
        .suggestions {{
            background: #FEF3C7;
            border: 1px solid #F59E0B;
            border-radius: 8px;
            padding: 15px;
            margin-top: 15px;
        }}
        
        .suggestions h4 {{
            color: #92400E;
            margin-bottom: 10px;
        }}
        
        .suggestions ul {{
            list-style: none;
            padding-left: 0;
        }}
        
        .suggestions li {{
            padding: 5px 0;
            color: #78350F;
        }}
        
        /* Footer */
        .footer {{
            background: var(--gray-100);
            padding: 20px 40px;
            text-align: center;
            color: var(--gray-600);
            font-size: 14px;
        }}
        
        /* Print styles */
        @media print {{
            body {{
                background: white;
                padding: 0;
            }}
            .container {{
                box-shadow: none;
            }}
            .test-body {{
                display: block !important;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <div class="header">
            <!-- Left: Logo + Brand -->
            <div class="header-left">
                <svg class="header-logo" viewBox="0 0 510 448" xmlns="http://www.w3.org/2000/svg">
                    <g>
                    <path d="M 229.56 377.57 C227.33,378.47 223.36,380.05 220.75,381.09 L 216.00 382.97 L 216.02 372.24 C216.04,364.12 216.64,359.18 218.50,352.00 C221.32,341.09 221.34,341.00 220.00,341.00 C219.45,341.00 219.01,341.56 219.03,342.25 C219.05,342.94 217.83,347.17 216.32,351.66 L 213.59 359.82 L 208.21 360.49 C205.25,360.86 202.65,360.99 202.44,360.77 C202.22,360.55 201.76,356.58 201.43,351.94 L 200.81 343.50 L 205.95 332.62 C208.77,326.64 210.85,321.52 210.58,321.24 C210.30,320.97 209.58,321.81 208.99,323.12 C208.39,324.43 206.12,326.25 203.95,327.18 L 200.00 328.85 L 200.00 311.32 L 206.00 302.66 C212.31,293.57 213.32,291.50 209.99,294.51 C208.89,295.50 207.77,296.10 207.50,295.84 C207.09,295.42 203.36,278.02 199.81,259.93 C198.73,254.42 198.80,254.09 206.48,231.06 C212.35,213.44 213.94,207.58 212.99,206.99 C212.29,206.56 207.85,205.91 203.11,205.53 C191.75,204.62 189.74,204.11 190.45,202.27 C190.76,201.46 191.30,191.67 191.64,180.53 L 192.27 160.26 L 186.88 156.35 C180.42,151.66 178.82,150.54 168.50,143.54 C164.10,140.55 158.25,136.52 155.50,134.59 C152.75,132.66 149.66,130.50 148.64,129.79 C147.61,129.08 145.14,127.22 143.14,125.65 C139.84,123.06 132.33,119.24 107.00,107.26 C102.32,105.05 97.65,102.95 96.61,102.60 C95.57,102.24 94.96,101.70 95.27,101.40 C95.58,101.09 103.62,100.09 113.15,99.17 C127.67,97.77 130.53,97.23 130.79,95.84 C131.02,94.66 125.46,90.22 111.81,80.65 C109.78,79.24 107.92,77.94 106.22,76.75 C93.74,68.02 89.63,65.14 89.99,64.39 C90.16,64.02 91.42,64.16 93.30,64.37 C93.82,64.43 94.39,64.50 95.00,64.56 C98.57,64.91 117.91,67.17 137.96,69.57 L 174.42 73.94 L 193.96 93.22 C261.56,159.92 272.80,171.36 272.24,172.90 C271.92,173.78 270.02,176.98 268.02,180.00 C266.02,183.02 263.11,187.75 261.56,190.50 C260.00,193.25 257.71,196.62 256.45,198.00 C254.69,199.93 245.00,222.36 245.00,224.50 C245.00,224.74 243.88,227.40 242.50,230.41 C241.12,233.41 240.00,236.12 240.00,236.42 C240.00,238.05 229.73,263.00 229.06,263.00 C228.63,263.00 226.20,259.44 223.67,255.08 C221.14,250.72 218.60,246.87 218.03,246.52 C217.34,246.09 217.00,252.52 217.00,266.31 L 217.00 286.74 L 221.88 297.12 C224.56,302.83 228.82,312.00 231.34,317.50 L 235.92 327.50 L 236.08 342.50 C236.17,350.75 235.65,361.65 234.93,366.72 L 233.63 375.93 ZM 289.83 395.75 C289.29,397.54 288.67,399.00 288.45,399.00 C288.24,399.00 284.77,396.13 280.75,392.62 C273.54,386.34 273.34,386.02 267.55,372.37 C262.00,359.28 259.21,352.95 253.30,340.01 C249.11,330.82 249.20,329.74 255.25,317.49 C264.40,298.97 269.33,289.94 270.15,290.23 C270.58,290.38 284.15,303.64 300.31,319.70 L 329.69 348.91 L 331.44 357.02 C332.41,361.48 332.91,365.42 332.56,365.77 C332.21,366.12 329.09,366.59 325.64,366.81 L 319.35 367.21 L 310.00 356.61 C304.86,350.77 300.25,346.00 299.76,346.00 C299.28,346.00 302.91,350.93 307.83,356.95 L 316.78 367.91 L 318.00 376.51 C318.67,381.24 318.98,385.36 318.67,385.66 C318.37,385.96 313.93,384.75 308.81,382.96 C298.57,379.39 296.44,377.69 288.81,367.00 C283.40,359.44 276.98,352.06 279.22,356.00 C280.00,357.38 283.70,363.60 287.43,369.83 L 294.22 381.16 L 292.52 386.83 C291.59,389.95 290.38,393.96 289.83,395.75 ZM 0.00 4.00 L 0.00 0.00 L 510.00 0.00 L 510.00 4.00 ZM 220.55 337.75 C220.14,339.10 220.29,340.00 220.93,340.00 C221.52,340.00 222.00,339.36 222.00,338.58 C222.00,337.80 222.29,336.34 222.65,335.33 C223.09,334.08 222.97,333.82 222.26,334.50 C221.69,335.05 220.92,336.51 220.55,337.75 Z" fill="rgb(86,80,139)"/>
                    <path d="M 265.10 396.75 C262.60,401.84 260.08,406.00 259.50,406.00 C258.01,406.00 254.70,403.61 245.25,395.69 L 237.00 388.78 L 236.86 372.64 L 236.72 356.50 L 235.16 366.23 L 233.85 374.40 L 234.93 366.72 C235.65,361.65 236.17,350.75 236.08,342.50 L 235.92 327.50 L 231.34 317.50 C228.82,312.00 224.56,302.83 221.88,297.12 L 217.00 286.74 L 217.00 266.31 C217.00,252.52 217.34,246.09 218.03,246.52 C218.60,246.87 221.14,250.72 223.67,255.08 C226.20,259.44 228.63,263.00 229.06,263.00 C229.73,263.00 240.00,238.05 240.00,236.42 C240.00,236.12 241.12,233.41 242.50,230.41 C243.88,227.40 245.00,224.74 245.00,224.50 C245.00,222.36 254.69,199.93 256.45,198.00 C257.71,196.62 260.00,193.25 261.56,190.50 C263.11,187.75 266.02,183.02 268.02,180.00 C270.02,176.98 271.92,173.78 272.24,172.90 C272.79,171.38 261.94,160.30 197.32,96.53 L 213.87 112.70 C235.70,134.04 255.13,152.92 257.04,154.65 C260.11,157.45 261.40,157.88 268.55,158.49 L 276.61 159.17 L 285.05 152.56 C289.70,148.92 294.17,145.38 295.00,144.70 C295.83,144.03 297.85,142.53 299.50,141.38 L 302.50 139.28 L 320.35 141.07 C334.36,142.48 338.65,143.25 340.31,144.68 C341.47,145.68 347.79,151.37 354.34,157.33 C360.89,163.28 367.21,168.58 368.38,169.09 C369.54,169.60 378.38,172.06 388.00,174.55 C397.62,177.05 420.35,182.94 438.50,187.65 C468.82,195.51 479.47,198.69 471.50,197.53 C467.83,196.99 454.49,195.86 406.00,192.01 C385.38,190.37 366.80,188.83 364.71,188.60 C360.86,188.17 358.39,186.28 342.50,171.61 C339.20,168.57 335.89,166.06 335.15,166.04 C334.41,166.02 331.26,167.41 328.15,169.13 C311.54,178.33 301.80,183.62 295.65,186.81 C291.88,188.76 288.66,190.83 288.48,191.43 C285.36,201.94 274.21,236.49 272.97,239.50 C272.52,240.60 271.90,247.12 271.59,254.00 C271.29,260.88 270.74,271.11 270.37,276.75 C269.90,284.01 270.03,287.00 270.82,287.00 C271.44,287.00 271.73,287.56 271.49,288.25 C271.24,288.94 284.25,302.94 300.40,319.37 L 318.31 337.59 L 300.31 319.70 C284.15,303.64 270.58,290.38 270.15,290.23 C269.33,289.94 264.40,298.97 255.25,317.49 C249.20,329.74 249.11,330.82 253.30,340.01 C259.21,352.95 262.00,359.28 267.55,372.37 C270.30,378.87 271.79,382.34 273.38,384.88 C272.03,382.78 270.83,380.14 269.00,375.81 C264.40,364.97 259.52,355.10 260.44,358.50 C260.74,359.60 262.93,366.58 265.32,374.00 L 269.65 387.50 Z" fill="rgb(145,142,195)"/>
                    <path d="M 124.47 67.97 C109.88,66.24 97.76,64.83 95.00,64.56 C94.39,64.50 93.82,64.43 93.30,64.37 C91.42,64.16 90.16,64.02 89.99,64.39 C89.63,65.14 93.74,68.02 106.22,76.75 C107.92,77.94 109.78,79.24 111.81,80.65 C125.46,90.22 131.02,94.66 130.79,95.84 C130.53,97.23 127.67,97.77 113.15,99.17 C103.62,100.09 95.58,101.09 95.27,101.40 C94.96,101.70 95.57,102.24 96.61,102.60 C97.65,102.95 102.32,105.05 107.00,107.26 C132.33,119.24 139.84,123.06 143.14,125.65 C145.14,127.22 147.61,129.08 148.64,129.79 C149.66,130.50 152.75,132.66 155.50,134.59 C158.25,136.52 164.10,140.55 168.50,143.54 C178.82,150.54 180.42,151.66 186.88,156.35 L 192.27 160.26 L 191.64 180.53 C191.50,185.22 191.32,189.68 191.14,193.32 L 172.50 184.21 C162.05,179.10 148.23,172.35 141.80,169.21 C135.36,166.07 130.08,163.21 130.05,162.85 C130.02,162.49 133.57,159.90 137.94,157.10 C144.79,152.71 148.14,150.00 146.72,150.00 C146.51,150.00 136.36,147.77 124.18,145.04 C102.51,140.19 101.81,139.95 91.55,134.03 C85.78,130.70 80.03,127.52 78.78,126.97 C77.53,126.41 74.07,124.43 71.10,122.55 L 65.71 119.14 L 72.10 115.05 C88.03,104.86 93.00,101.52 93.00,101.00 C93.00,100.69 88.16,98.24 82.25,95.56 C69.55,89.81 40.18,76.37 20.50,67.31 C12.80,63.77 6.05,60.40 5.50,59.84 C4.82,59.14 7.84,59.01 15.00,59.42 C20.77,59.75 38.33,60.70 54.00,61.51 C69.68,62.33 88.35,63.69 95.50,64.52 C100.46,65.11 111.90,66.47 124.47,67.97 Z" fill="rgb(224,178,73)"/>
                    </g>
                </svg>
                <span class="header-brand">QA</span>
            </div>
            
            <!-- Center: Title and Links -->
            <div class="header-center">
                <h1>Test Case Outcome Report</h1>
                <div class="subtitle">
                    <strong>Jira:</strong> <a href="{jira_url}" target="_blank">{jira_key}</a> | 
                    <strong>PR:</strong> <a href="{pr_url}" target="_blank">#{pr_number or 'N/A'}</a>
                </div>
                <div class="subtitle" style="margin-top: 4px; opacity: 0.8; font-size: 12px;">
                    {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                </div>
            </div>
        </div>
        
        <!-- Status Banner -->
        <div class="status-banner">
            {status_text} - Pass Rate: {pass_rate:.1f}%
        </div>
        
        <!-- Summary Section -->
        <div class="summary-section">
            <div class="summary-grid">
                <div class="summary-card">
                    <div class="value">{summary.total_tests}</div>
                    <div class="label">Total Tests</div>
                </div>
                <div class="summary-card passed">
                    <div class="value">{summary.passed}</div>
                    <div class="label">Passed</div>
                </div>
                <div class="summary-card failed">
                    <div class="value">{summary.failed}</div>
                    <div class="label">Failed</div>
                </div>
                <div class="summary-card errors">
                    <div class="value">{summary.errors}</div>
                    <div class="label">Errors</div>
                </div>
                <div class="summary-card">
                    <div class="value">{summary.total_time_ms:.0f}ms</div>
                    <div class="label">Total Time</div>
                </div>
            </div>
            
            <!-- Progress Bar -->
            <div class="progress-container">
                <div class="progress-bar">
                    {self._generate_progress_segments(summary)}
                </div>
            </div>
            
            <!-- Progress Circles -->
            <div class="progress-circle-container">
                {self._generate_progress_circle(
                    pass_rate, 
                    "Test Pass Rate", 
                    "pass",
                    "<div class='tooltip-title'>How it's calculated:</div>"
                    "<b>Formula:</b> (Passed Tests ÷ Total Tests) × 100<br><br>"
                    f"<b>Current:</b> {summary.passed} passed out of {summary.total_tests} total tests"
                )}
                {self._generate_alignment_circle(summary)}
                {self._generate_quality_circle(summary)}
            </div>
            
            <!-- Disclaimer -->
            <div style="background: #FEF3C7; border: 1px solid #F59E0B; border-radius: 8px; padding: 12px 16px; margin-top: 20px; display: flex; align-items: flex-start; gap: 10px;">
                <span style="font-size: 20px;">⚠️</span>
                <div style="font-size: 13px; color: #92400E;">
                    <strong>Disclaimer:</strong> The "Code Alignment" score is an estimated analysis based on test results compared to Jira description. 
                    This analysis may not be 100% accurate as code changes can have both <strong>direct</strong> and <strong>indirect</strong> impacts on the Jira requirements. 
                    Please review the actual code changes and test results for a complete assessment.
                </div>
            </div>
        </div>
        
        <!-- Code Quality Review -->
        {self._generate_code_quality_section(summary)}
        
        <!-- Test Results -->
        <div class="results-section">
            <h2 class="section-title">📋 Test Results</h2>
            
            {self._generate_test_cards(summary.results)}
        </div>
        
        <!-- Suggestions Summary -->
        {self._generate_suggestions_summary(summary.results)}
        
        <!-- Footer -->
        <div class="footer">
            Generated by {self.config.company_name} QA Agent | 
            {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        </div>
    </div>
    
    <script>
        // Toggle test card expansion
        document.querySelectorAll('.test-header').forEach(header => {{
            header.addEventListener('click', () => {{
                header.parentElement.classList.toggle('expanded');
            }});
        }});
    </script>
</body>
</html>'''
        
        return html
    
    def _generate_progress_circle(self, percentage: float, label: str, css_class: str, tooltip_info: str = "") -> str:
        """Generate a circular progress indicator with info tooltip"""
        # SVG circle parameters
        radius = 60
        circumference = 2 * 3.14159 * radius
        offset = circumference - (percentage / 100) * circumference
        
        # Info icon with tooltip
        info_html = ""
        if tooltip_info:
            info_html = f'''<span class="info-icon">i<span class="tooltip">{tooltip_info}</span></span>'''
        
        return f'''
            <div class="progress-circle-item">
                <div class="progress-circle">
                    <svg width="150" height="150" viewBox="0 0 150 150">
                        <circle class="bg" cx="75" cy="75" r="{radius}"/>
                        <circle class="progress {css_class}" cx="75" cy="75" r="{radius}"
                            stroke-dasharray="{circumference}"
                            stroke-dashoffset="{offset}"/>
                    </svg>
                    <div class="percentage">{percentage:.0f}%</div>
                </div>
                <div class="progress-circle-label">{label} {info_html}</div>
            </div>
        '''
    
    def _generate_alignment_circle(self, summary: TestExecutionSummary) -> str:
        """Generate Code Alignment progress circle with real or fallback analysis"""
        
        # Check if we have real AI analysis
        if hasattr(self, '_code_alignment') and self._code_alignment:
            score = self._code_alignment.score
            confidence = getattr(self._code_alignment, 'confidence', 'medium')
            aligned = len(getattr(self._code_alignment, 'aligned_changes', []))
            unrelated = len(getattr(self._code_alignment, 'unrelated_changes', []))
            summary_text = getattr(self._code_alignment, 'summary', '')[:100]
            
            tooltip = (
                "<div class='tooltip-title'>AI-Powered Analysis</div>"
                "<b>Method:</b> QA Agent comparison of PR diff vs Jira requirements<br><br>"
                f"<b>Aligned Changes:</b> {aligned}<br>"
                f"<b>Unrelated Changes:</b> {unrelated}<br>"
                f"<b>Confidence:</b> {confidence}<br><br>"
                f"<em>{summary_text}...</em>"
            )
        else:
            score = self._calculate_alignment_score(summary)
            tooltip = (
                "<div class='tooltip-title'>Estimated Score</div>"
                "<b>Based on:</b><br>"
                "• Test coverage (60%)<br>"
                "• Error-free execution (20%)<br>"
                "• Test count bonus (20%)<br><br>"
                "<em>Note: For accurate analysis, provide PR files with patches.</em>"
            )
        
        return self._generate_progress_circle(score, "Code Alignment", "align", tooltip)
    
    def _generate_quality_circle(self, summary: TestExecutionSummary) -> str:
        """Generate Code Quality progress circle with real or fallback analysis"""
        
        # Check if we have real code quality analysis
        if hasattr(self, '_code_quality') and self._code_quality:
            score = self._code_quality.score
            tool = getattr(self._code_quality, 'tool_used', 'pattern-analysis')
            errors = getattr(self._code_quality, 'errors', 0)
            warnings = getattr(self._code_quality, 'warnings', 0)
            info = getattr(self._code_quality, 'info', 0)
            
            if tool == 'semgrep':
                tool_name = "Semgrep (Open Source)"
            else:
                tool_name = "Pattern Analysis"
            
            tooltip = (
                "<div class='tooltip-title'>Static Code Analysis</div>"
                f"<b>Tool:</b> {tool_name}<br><br>"
                f"<b>Issues Found:</b><br>"
                f"• Errors: {errors}<br>"
                f"• Warnings: {warnings}<br>"
                f"• Info: {info}<br><br>"
                "<b>Score:</b> 100 - (errors×10) - (warnings×3) - (info×1)"
            )
        else:
            score = self._calculate_quality_score(summary)
            tooltip = (
                "<div class='tooltip-title'>Estimated Score</div>"
                "<b>Based on:</b><br>"
                "• Test pass rate (50%)<br>"
                "• API response times (25%)<br>"
                "• Error handling (25%)<br><br>"
                "<em>Install Semgrep for real static analysis:<br>"
                "<code>pip install semgrep</code></em>"
            )
        
        return self._generate_progress_circle(score, "Code Quality", "quality", tooltip)
    
    def _calculate_alignment_score(self, summary: TestExecutionSummary) -> float:
        """Calculate how well the code changes align with requirements
        
        This is based on:
        - Test coverage (tests exist for changed code)
        - No unexpected errors
        - Response times within acceptable range
        """
        if summary.total_tests == 0:
            return 0.0
        
        # Base score from pass rate
        base_score = (summary.passed / summary.total_tests) * 60
        
        # Bonus for no errors
        error_penalty = (summary.errors / summary.total_tests) * 20 if summary.errors > 0 else 0
        no_error_bonus = 20 - error_penalty
        
        # Bonus for having tests (coverage indication)
        coverage_bonus = min(20, summary.total_tests * 2)  # Max 20 points
        
        return min(100, base_score + no_error_bonus + coverage_bonus)
    
    def _calculate_quality_score(self, summary: TestExecutionSummary) -> float:
        """Calculate code quality score based on test results
        
        Considers:
        - Pass rate
        - Response times
        - Error handling
        """
        if summary.total_tests == 0:
            return 0.0
        
        # Pass rate contribution (50%)
        pass_score = (summary.passed / summary.total_tests) * 50
        
        # Check response times from results (25%)
        time_scores = []
        for result in summary.results:
            if result.response and result.response.response_time_ms < 1000:
                time_scores.append(25)
            elif result.response and result.response.response_time_ms < 3000:
                time_scores.append(15)
            else:
                time_scores.append(5)
        
        time_score = sum(time_scores) / len(time_scores) if time_scores else 15
        
        # No errors bonus (25%)
        error_score = 25 if summary.errors == 0 else max(0, 25 - (summary.errors * 5))
        
        return min(100, pass_score + time_score + error_score)
    
    def _generate_code_quality_section(self, summary: TestExecutionSummary) -> str:
        """Generate code quality review section"""
        
        # Analyze results for quality insights
        quality_score = self._calculate_quality_score(summary)
        alignment_score = self._calculate_alignment_score(summary)
        
        # Determine overall quality badge
        if quality_score >= 80:
            quality_badge = '<span class="quality-badge good">✅ Good</span>'
        elif quality_score >= 60:
            quality_badge = '<span class="quality-badge warning">⚠️ Needs Attention</span>'
        else:
            quality_badge = '<span class="quality-badge critical">❌ Critical Issues</span>'
        
        # Generate suggestions based on results
        suggestions = []
        improvements = []
        strengths = []
        
        # Analyze pass/fail patterns
        if summary.failed > 0:
            suggestions.append("Review failed test cases and fix underlying issues")
            
        if summary.errors > 0:
            suggestions.append("Investigate error cases - may indicate connection or auth issues")
            improvements.append("Add better error handling in the code")
        
        # Analyze response times
        slow_tests = [r for r in summary.results if r.response and r.response.response_time_ms > 2000]
        if slow_tests:
            suggestions.append(f"{len(slow_tests)} endpoint(s) have slow response times (>2s)")
            improvements.append("Consider optimizing database queries or adding caching")
        
        # Check for common issues
        auth_failures = [r for r in summary.results if r.response and r.response.status_code == 401]
        if auth_failures:
            suggestions.append("Authentication failures detected - verify API tokens")
        
        not_found = [r for r in summary.results if r.response and r.response.status_code == 404]
        if not_found:
            suggestions.append(f"{len(not_found)} endpoint(s) returned 404 - verify paths")
        
        server_errors = [r for r in summary.results if r.response and r.response.status_code >= 500]
        if server_errors:
            suggestions.append(f"{len(server_errors)} server error(s) - check server logs")
            improvements.append("Add try-catch blocks and proper error responses")
        
        # Add strengths
        if summary.passed > 0:
            strengths.append(f"{summary.passed} test(s) passing successfully")
        
        fast_tests = [r for r in summary.results if r.response and r.response.response_time_ms < 500]
        if fast_tests:
            strengths.append(f"{len(fast_tests)} endpoint(s) with excellent response time (<500ms)")
        
        if summary.errors == 0:
            strengths.append("No connection or system errors")
        
        if alignment_score >= 80:
            strengths.append("Code changes well-aligned with requirements")
        
        # Default suggestions if none found
        if not suggestions:
            suggestions.append("All tests passed - code is production ready")
        if not improvements:
            improvements.append("Continue following current coding practices")
        if not strengths:
            strengths.append("Tests are being executed successfully")
        
        return f'''
        <div class="code-quality-section">
            <h2 class="section-title">🔍 Code Quality Review {quality_badge}</h2>
            
            <div class="quality-grid">
                <div class="quality-card">
                    <h4>💡 Suggestions</h4>
                    <ul>
                        {"".join(f"<li>{s}</li>" for s in suggestions[:5])}
                    </ul>
                </div>
                
                <div class="quality-card">
                    <h4>🔧 Improvements Needed</h4>
                    <ul>
                        {"".join(f"<li>{i}</li>" for i in improvements[:5])}
                    </ul>
                </div>
                
                <div class="quality-card">
                    <h4>✨ Strengths</h4>
                    <ul>
                        {"".join(f"<li>{s}</li>" for s in strengths[:5])}
                    </ul>
                </div>
            </div>
        </div>
        '''
    
    def _generate_progress_segments(self, summary: TestExecutionSummary) -> str:
        """Generate progress bar segments"""
        segments = []
        total = summary.total_tests
        
        if total == 0:
            return '<div class="progress-segment skipped" style="width: 100%">No Tests</div>'
        
        if summary.passed > 0:
            width = (summary.passed / total) * 100
            segments.append(
                f'<div class="progress-segment passed" style="width: {width}%">'
                f'{summary.passed} Passed</div>'
            )
        
        if summary.failed > 0:
            width = (summary.failed / total) * 100
            segments.append(
                f'<div class="progress-segment failed" style="width: {width}%">'
                f'{summary.failed} Failed</div>'
            )
        
        if summary.errors > 0:
            width = (summary.errors / total) * 100
            segments.append(
                f'<div class="progress-segment errors" style="width: {width}%">'
                f'{summary.errors} Errors</div>'
            )
        
        if summary.skipped > 0:
            width = (summary.skipped / total) * 100
            segments.append(
                f'<div class="progress-segment skipped" style="width: {width}%">'
                f'{summary.skipped} Skipped</div>'
            )
        
        return '\n'.join(segments)
    
    def _generate_test_cards(self, results: List[TestResult]) -> str:
        """Generate HTML for test result cards"""
        cards = []
        
        for result in results:
            status_class = result.status.value
            status_text = result.status.value.upper()
            
            # Generate assertions HTML
            assertions_html = self._generate_assertions_html(result.assertions)
            
            # Generate request/response HTML
            request_html = self._format_json_html(
                result.request.__dict__ if result.request else {}
            )
            response_html = self._format_json_html(
                result.response.__dict__ if result.response else {"error": result.error_message}
            )
            
            # Generate suggestions HTML
            suggestions_html = ""
            if result.suggestions:
                suggestions_html = f'''
                <div class="suggestions">
                    <h4>💡 Suggestions to Improve</h4>
                    <ul>
                        {"".join(f"<li>{s}</li>" for s in result.suggestions)}
                    </ul>
                </div>'''
            
            card = f'''
            <div class="test-card">
                <div class="test-header {status_class}">
                    <span class="status-badge {status_class}">{status_text}</span>
                    <span class="test-name">{result.test_id}: {result.test_name}</span>
                    <span class="test-time">{result.execution_time_ms:.0f}ms</span>
                    <span class="expand-icon">▼</span>
                </div>
                <div class="test-body">
                    <p><strong>Description:</strong> {result.description}</p>
                    <p><strong>Source:</strong> {result.source_file}</p>
                    
                    {assertions_html}
                    
                    <div class="request-response">
                        <div>
                            <h4>📤 Request</h4>
                            <div class="code-block">{request_html}</div>
                        </div>
                        <div>
                            <h4>📥 Response</h4>
                            <div class="code-block">{response_html}</div>
                        </div>
                    </div>
                    
                    {suggestions_html}
                </div>
            </div>'''
            
            cards.append(card)
        
        return '\n'.join(cards)
    
    def _generate_assertions_html(self, assertions: List[Dict]) -> str:
        """Generate HTML for assertions"""
        if not assertions:
            return ""
        
        html = '<div class="assertions"><h4>✓ Assertions</h4>'
        
        for assertion in assertions:
            passed = assertion.get('passed', False)
            status_class = "passed" if passed else "failed"
            icon = "✅" if passed else "❌"
            
            html += f'''
            <div class="assertion {status_class}">
                <span class="assertion-icon">{icon}</span>
                <strong>{assertion.get('type', 'Unknown')}:</strong>
                Expected: {assertion.get('expected', 'N/A')} | 
                Actual: {assertion.get('actual', 'N/A')}
            </div>'''
        
        html += '</div>'
        return html
    
    def _format_json_html(self, data: Any) -> str:
        """Format JSON data for HTML display with syntax highlighting"""
        try:
            if isinstance(data, str):
                return self._escape_html(data)
            
            json_str = json.dumps(data, indent=2, default=str)
            
            # Truncate if too long
            if len(json_str) > self.config.max_response_length:
                json_str = json_str[:self.config.max_response_length] + "\n... (truncated)"
            
            return self._escape_html(json_str)
        except:
            return str(data)
    
    def _escape_html(self, text: str) -> str:
        """Escape HTML special characters"""
        return (
            text.replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
            .replace("'", '&#39;')
        )
    
    def _generate_suggestions_summary(self, results: List[TestResult]) -> str:
        """Generate a summary of all suggestions"""
        all_suggestions = []
        
        for result in results:
            if result.suggestions and result.status != TestStatus.PASSED:
                all_suggestions.extend([
                    f"[{result.test_id}] {s}" for s in result.suggestions
                ])
        
        if not all_suggestions:
            return ""
        
        # Deduplicate similar suggestions
        unique_suggestions = list(dict.fromkeys(all_suggestions))[:10]  # Top 10
        
        return f'''
        <div class="results-section">
            <h2 class="section-title">💡 Code Enhancement Suggestions</h2>
            <div class="suggestions" style="background: #EEF2FF; border-color: #6366F1;">
                <ul>
                    {"".join(f"<li>{s}</li>" for s in unique_suggestions)}
                </ul>
            </div>
        </div>'''


def generate_test_report(
    summary: TestExecutionSummary,
    jira_key: str,
    pr_number: int = None,
    output_dir: str = "test_reports"
) -> str:
    """Convenience function to generate a test report
    
    Returns the path to the generated HTML file
    """
    config = ReportConfig(output_dir=output_dir)
    generator = TestReportGenerator(config)
    return generator.generate_html_report(summary, jira_key, pr_number)


# Quick test
if __name__ == "__main__":
    from api_executor import TestStatus, APIRequest, APIResponse
    
    # Create sample data
    sample_results = [
        TestResult(
            test_id="TC_001",
            test_name="GET /api/users",
            description="Test getting all users",
            status=TestStatus.PASSED,
            request=APIRequest(method="GET", url="https://api.example.com/users"),
            response=APIResponse(status_code=200, body={"users": []}, response_time_ms=150),
            expected_status=200,
            actual_status=200,
            assertions=[{"type": "status_code", "expected": 200, "actual": 200, "passed": True}],
            execution_time_ms=150,
            source_file="test_data.json"
        ),
        TestResult(
            test_id="TC_002",
            test_name="POST /api/users",
            description="Test creating a user",
            status=TestStatus.FAILED,
            request=APIRequest(method="POST", url="https://api.example.com/users", body={"name": "Test"}),
            response=APIResponse(status_code=400, body={"error": "Invalid input"}, response_time_ms=50),
            expected_status=201,
            actual_status=400,
            assertions=[{"type": "status_code", "expected": 201, "actual": 400, "passed": False}],
            error_message="Status code mismatch",
            suggestions=["📝 Validate request body format", "🔍 Check required fields"],
            execution_time_ms=50,
            source_file="test_data.json"
        ),
    ]
    
    summary = TestExecutionSummary(
        total_tests=2,
        passed=1,
        failed=1,
        errors=0,
        skipped=0,
        total_time_ms=200,
        results=sample_results,
        pr_number=123
    )
    
    report_path = generate_test_report(summary, "DT-1234", pr_number=123)
    print(f"Report generated: {report_path}")

