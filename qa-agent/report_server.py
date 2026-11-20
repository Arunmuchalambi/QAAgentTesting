"""
Report Server - Serves HTML test reports for direct browser viewing
"""

import os
import threading
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
from loguru import logger

# Configuration
REPORT_DIR = os.path.join(os.path.dirname(__file__), "test_reports")
SERVER_PORT = 8080
SERVER_HOST = "0.0.0.0"

# Create FastAPI app
app = FastAPI(
    title="QA Agent - Report Viewer",
    description="View test execution reports directly in your browser",
    version="1.0.0"
)

# Ensure report directory exists
os.makedirs(REPORT_DIR, exist_ok=True)


@app.get("/", response_class=HTMLResponse)
async def home():
    """Home page with list of available reports"""
    reports = []
    for f in sorted(Path(REPORT_DIR).glob("*.html"), key=os.path.getmtime, reverse=True):
        reports.append({
            "name": f.name,
            "path": f"/report/{f.name}",
            "size": f"{f.stat().st_size / 1024:.1f} KB",
            "modified": f.stat().st_mtime
        })
    
    # Generate HTML listing
    report_rows = ""
    for r in reports[:50]:  # Show last 50 reports
        from datetime import datetime
        mod_time = datetime.fromtimestamp(r["modified"]).strftime("%Y-%m-%d %H:%M")
        report_rows += f'''
        <tr>
            <td><a href="{r['path']}" target="_blank">📄 {r['name']}</a></td>
            <td>{r['size']}</td>
            <td>{mod_time}</td>
            <td>
                <a href="{r['path']}" class="btn view" target="_blank">👁️ View</a>
                <a href="{r['path']}?download=1" class="btn download">⬇️ Download</a>
            </td>
        </tr>
        '''
    
    if not report_rows:
        report_rows = '<tr><td colspan="4" style="text-align:center;padding:40px;color:#666;">No reports generated yet. Create a PR to trigger test execution.</td></tr>'
    
    html = f'''
    <!DOCTYPE html>
    <html>
    <head>
        <title>QA Agent - Report Viewer</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                padding: 40px;
            }}
            .container {{
                max-width: 1200px;
                margin: 0 auto;
                background: white;
                border-radius: 16px;
                box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25);
                overflow: hidden;
            }}
            .header {{
                background: linear-gradient(135deg, #4F46E5 0%, #7C3AED 100%);
                color: white;
                padding: 30px 40px;
                display: flex;
                align-items: center;
                gap: 20px;
            }}
            .header h1 {{ font-size: 24px; }}
            .header .subtitle {{ opacity: 0.9; font-size: 14px; margin-top: 5px; }}
            .content {{ padding: 30px 40px; }}
            table {{
                width: 100%;
                border-collapse: collapse;
            }}
            th, td {{
                padding: 15px;
                text-align: left;
                border-bottom: 1px solid #E5E7EB;
            }}
            th {{
                background: #F3F4F6;
                font-weight: 600;
                color: #374151;
            }}
            tr:hover {{ background: #F9FAFB; }}
            a {{ color: #4F46E5; text-decoration: none; }}
            a:hover {{ text-decoration: underline; }}
            .btn {{
                display: inline-block;
                padding: 6px 12px;
                border-radius: 6px;
                font-size: 12px;
                margin-right: 5px;
                text-decoration: none !important;
            }}
            .btn.view {{ background: #EEF2FF; color: #4F46E5; }}
            .btn.download {{ background: #F0FDF4; color: #059669; }}
            .btn:hover {{ opacity: 0.8; }}
            .stats {{
                display: flex;
                gap: 20px;
                margin-bottom: 20px;
            }}
            .stat {{
                background: #F3F4F6;
                padding: 15px 25px;
                border-radius: 8px;
            }}
            .stat-value {{ font-size: 24px; font-weight: bold; color: #4F46E5; }}
            .stat-label {{ font-size: 12px; color: #6B7280; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div>
                    <h1>🐦🧪 QA Agent - Report Viewer</h1>
                    <div class="subtitle">Click any report to view directly in browser</div>
                </div>
            </div>
            <div class="content">
                <div class="stats">
                    <div class="stat">
                        <div class="stat-value">{len(reports)}</div>
                        <div class="stat-label">Total Reports</div>
                    </div>
                </div>
                <table>
                    <thead>
                        <tr>
                            <th>Report Name</th>
                            <th>Size</th>
                            <th>Generated</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {report_rows}
                    </tbody>
                </table>
            </div>
        </div>
    </body>
    </html>
    '''
    return HTMLResponse(content=html)


@app.get("/report/{filename}")
async def view_report(filename: str, download: int = 0):
    """View or download a specific report"""
    filepath = os.path.join(REPORT_DIR, filename)
    
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Report not found")
    
    if not filename.endswith('.html'):
        raise HTTPException(status_code=400, detail="Only HTML reports are supported")
    
    # Security check - prevent path traversal
    if ".." in filename or "/" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    if download:
        return FileResponse(
            filepath, 
            filename=filename,
            media_type="text/html"
        )
    
    # Return HTML for direct viewing
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    return HTMLResponse(content=content)


@app.get("/api/reports")
async def list_reports():
    """API endpoint to list all reports"""
    reports = []
    for f in sorted(Path(REPORT_DIR).glob("*.html"), key=os.path.getmtime, reverse=True):
        reports.append({
            "name": f.name,
            "url": f"/report/{f.name}",
            "size_bytes": f.stat().st_size,
            "modified_timestamp": f.stat().st_mtime
        })
    return JSONResponse(content={"reports": reports, "total": len(reports)})


@app.get("/api/latest")
async def latest_report():
    """Get the latest report"""
    reports = sorted(Path(REPORT_DIR).glob("*.html"), key=os.path.getmtime, reverse=True)
    if not reports:
        raise HTTPException(status_code=404, detail="No reports available")
    
    latest = reports[0]
    return JSONResponse(content={
        "name": latest.name,
        "url": f"/report/{latest.name}",
        "view_url": f"http://localhost:{SERVER_PORT}/report/{latest.name}"
    })


class ReportServer:
    """Report server that runs in background"""
    
    def __init__(self, port: int = SERVER_PORT, host: str = SERVER_HOST):
        self.port = port
        self.host = host
        self._server_thread: Optional[threading.Thread] = None
        self._running = False
    
    def start(self):
        """Start the report server in background"""
        if self._running:
            logger.info(f"Report server already running on http://{self.host}:{self.port}")
            return
        
        def run_server():
            config = uvicorn.Config(
                app, 
                host=self.host, 
                port=self.port, 
                log_level="warning"
            )
            server = uvicorn.Server(config)
            server.run()
        
        self._server_thread = threading.Thread(target=run_server, daemon=True)
        self._server_thread.start()
        self._running = True
        logger.info(f"📊 Report server started: http://localhost:{self.port}")
    
    def get_report_url(self, filename: str) -> str:
        """Get the URL to view a report"""
        return f"http://localhost:{self.port}/report/{filename}"
    
    def get_base_url(self) -> str:
        """Get the base URL of the report server"""
        return f"http://localhost:{self.port}"


# Singleton instance
_report_server: Optional[ReportServer] = None


def get_report_server() -> ReportServer:
    """Get or create report server instance"""
    global _report_server
    if _report_server is None:
        _report_server = ReportServer()
    return _report_server


def start_report_server(port: int = SERVER_PORT) -> str:
    """Start the report server and return base URL"""
    server = get_report_server()
    server.port = port
    server.start()
    return server.get_base_url()


# Run standalone
if __name__ == "__main__":
    print(f"\n🐦🧪 QA Agent - Report Server")
    print(f"=" * 40)
    print(f"📊 Reports directory: {REPORT_DIR}")
    print(f"🌐 Server URL: http://localhost:{SERVER_PORT}")
    print(f"=" * 40)
    print(f"\nOpen http://localhost:{SERVER_PORT} in your browser to view reports\n")
    
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)

