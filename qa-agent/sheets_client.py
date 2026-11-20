"""
Google Sheets Client for QA Agent
Structure: One row per Test Case, grouped by Jira ID
"""

import os
from typing import List, Dict, Any, Optional
from datetime import datetime
from loguru import logger

try:
    import gspread
    from google.oauth2.service_account import Credentials
    SHEETS_AVAILABLE = True
except ImportError:
    SHEETS_AVAILABLE = False
    logger.warning("Google Sheets libraries not installed. Run: pip install gspread google-auth")


class SheetsClient:
    """Client for Google Sheets integration"""
    
    # Column structure matching user's diagram
    COLUMNS = {
        "Jira ID": "A",
        "Test Id": "B",
        "Test Details": "C",
        "Test Summary": "D",
        "PR Link": "E",
        "Subtask ID": "F",
    }
    
    def __init__(
        self,
        spreadsheet_id: str = "1a7ExGEI6vy9kMjDkSWMN0966VPnK-ikOUE4d_penK8Y",
        credentials_path: str = None
    ):
        self.spreadsheet_id = spreadsheet_id
        self.credentials_path = credentials_path or self._find_credentials()
        self.client = None
        self.sheet = None
        self.worksheet = None
        
        if SHEETS_AVAILABLE:
            self._connect()
    
    def _find_credentials(self) -> str:
        possible_paths = [
            "google_credentials.json",
            os.path.join(os.path.dirname(__file__), "google_credentials.json"),
        ]
        for path in possible_paths:
            if os.path.exists(path):
                return path
        return "google_credentials.json"
    
    def _connect(self):
        if not SHEETS_AVAILABLE:
            logger.error("Google Sheets libraries not available")
            return
        
        if not os.path.exists(self.credentials_path):
            logger.error(f"Credentials file not found: {self.credentials_path}")
            return
        
        try:
            scopes = [
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive'
            ]
            
            creds = Credentials.from_service_account_file(
                self.credentials_path,
                scopes=scopes
            )
            
            self.client = gspread.authorize(creds)
            self.sheet = self.client.open_by_key(self.spreadsheet_id)
            self.worksheet = self.sheet.sheet1
            
            logger.info(f"Connected to Google Sheet: {self.sheet.title}")
            self._ensure_headers()
            
        except Exception as e:
            logger.error(f"Failed to connect to Google Sheets: {e}")
            self.client = None
    
    def _ensure_headers(self):
        if not self.worksheet:
            return
        try:
            first_row = self.worksheet.row_values(1)
            if not first_row or first_row[0] != "Jira ID":
                headers = list(self.COLUMNS.keys())
                self.worksheet.update(values=[headers], range_name='A1:F1')
                logger.info("Created header row in Google Sheet")
        except Exception as e:
            logger.error(f"Failed to ensure headers: {e}")
    
    def is_connected(self) -> bool:
        return self.client is not None and self.worksheet is not None
    
    def find_test_case_row(self, jira_id: str, test_id: str) -> Optional[int]:
        """Find if a specific test case already exists for a Jira"""
        if not self.is_connected():
            return None
        try:
            # Get all data
            all_data = self.worksheet.get_all_values()
            for idx, row in enumerate(all_data[1:], start=2):  # Skip header
                if len(row) >= 2 and row[0] == jira_id and row[1] == test_id:
                    return idx
            return None
        except Exception as e:
            logger.error(f"Failed to find test case row: {e}")
            return None
    
    def add_test_cases(
        self,
        jira_id: str,
        jira_summary: str,
        subtask_id: str,
        test_cases: List[Dict[str, Any]],
        pr_url: str = None
    ) -> bool:
        """
        Add test cases to sheet - one row per test case
        Appends under existing Jira section if Jira already exists
        
        Args:
            jira_id: Parent Jira issue key
            jira_summary: Jira issue summary (used in test details)
            subtask_id: Subtask key
            test_cases: List of test case dictionaries
            pr_url: Optional PR URL
        """
        if not self.is_connected():
            logger.warning("Not connected to Google Sheets, skipping...")
            return False
        
        try:
            rows_to_add = []
            rows_updated = 0
            
            # Find if Jira already exists and get its last row
            jira_rows = self._find_jira_row_range(jira_id)
            insert_after_row = jira_rows[1] if jira_rows else None  # Last row of existing Jira
            
            for tc in test_cases:
                test_id = tc.get("id", tc.get("test_id", ""))
                title = tc.get("title", tc.get("name", ""))
                tc_type = tc.get("type", tc.get("test_type", "functional"))
                priority = tc.get("priority", "medium")
                description = tc.get("description", "")
                
                # Format steps
                steps = tc.get("steps", tc.get("test_steps", []))
                if isinstance(steps, list):
                    steps_str = "\n".join([f"{i+1}. {s}" for i, s in enumerate(steps)])
                else:
                    steps_str = str(steps)
                
                # Format expected results
                expected = tc.get("expected_result", tc.get("expected_results", ""))
                if isinstance(expected, list):
                    expected_str = "\n".join([f"• {e}" for e in expected])
                else:
                    expected_str = str(expected)
                
                # Format preconditions
                preconditions = tc.get("preconditions", tc.get("prerequisites", ""))
                if isinstance(preconditions, list):
                    preconditions_str = "\n".join([f"• {p}" for p in preconditions])
                else:
                    preconditions_str = str(preconditions)
                
                # Build Test Details (Column C) - comprehensive info
                test_details = f"""Type: {tc_type}
Priority: {priority}
Description: {description}

Preconditions:
{preconditions_str}

Steps:
{steps_str}

Expected Results:
{expected_str}"""
                
                # Test Summary (Column D) - brief title
                test_summary = title
                
                # Check if this test case already exists
                existing_row = self.find_test_case_row(jira_id, test_id)
                
                if existing_row:
                    # Update existing row
                    row_data = [jira_id, test_id, test_details, test_summary, pr_url or "", subtask_id]
                    self.worksheet.update(values=[row_data], range_name=f'A{existing_row}:F{existing_row}')
                    rows_updated += 1
                else:
                    # Add new row
                    row_data = [jira_id, test_id, test_details, test_summary, pr_url or "", subtask_id]
                    rows_to_add.append(row_data)
            
            # Insert/append new rows
            if rows_to_add:
                if insert_after_row:
                    # Jira exists - insert rows after its last row
                    logger.info(f"Inserting {len(rows_to_add)} rows after row {insert_after_row} for {jira_id}")
                    
                    # First, unmerge the existing cells for this Jira
                    self._unmerge_jira_cells(jira_id)
                    
                    # Insert new rows
                    for i, row_data in enumerate(rows_to_add):
                        self.worksheet.insert_row(row_data, insert_after_row + 1 + i)
                    
                    logger.info(f"Inserted {len(rows_to_add)} new test case rows under {jira_id}")
                else:
                    # New Jira - append at end
                    self.worksheet.append_rows(rows_to_add)
                    logger.info(f"Added {len(rows_to_add)} new test case rows for {jira_id}")
                
                # Re-merge Jira ID cells in column A for this Jira
                self._merge_jira_cells(jira_id)
            
            if rows_updated > 0:
                logger.info(f"Updated {rows_updated} existing test case rows for {jira_id}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to add test cases to sheet: {e}")
            return False
    
    def _find_jira_row_range(self, jira_id: str) -> Optional[tuple]:
        """Find the start and end row for a Jira ID
        
        Returns:
            Tuple of (start_row, end_row) or None if not found
        """
        if not self.is_connected():
            return None
        try:
            jira_column = self.worksheet.col_values(1)
            start_row = None
            end_row = None
            
            for idx, value in enumerate(jira_column):
                if value == jira_id:
                    if start_row is None:
                        start_row = idx + 1
                    end_row = idx + 1
            
            if start_row:
                return (start_row, end_row)
            return None
        except Exception as e:
            logger.error(f"Failed to find Jira row range: {e}")
            return None
    
    def _unmerge_jira_cells(self, jira_id: str):
        """Unmerge column A cells for a specific Jira ID"""
        try:
            jira_range = self._find_jira_row_range(jira_id)
            if not jira_range:
                return
            
            start_row, end_row = jira_range
            if start_row == end_row:
                return  # Nothing to unmerge
            
            # Unmerge cells
            sheet_id = self.worksheet.id
            requests = [{
                'unmergeCells': {
                    'range': {
                        'sheetId': sheet_id,
                        'startRowIndex': start_row - 1,  # 0-indexed
                        'endRowIndex': end_row,
                        'startColumnIndex': 0,
                        'endColumnIndex': 1
                    }
                }
            }]
            self.sheet.batch_update({'requests': requests})
            
            # Restore Jira ID in all unmerged cells
            for row in range(start_row, end_row + 1):
                self.worksheet.update_acell(f'A{row}', jira_id)
            
            logger.info(f"Unmerged cells A{start_row}:A{end_row} for {jira_id}")
            
        except Exception as e:
            logger.warning(f"Could not unmerge cells for {jira_id}: {e}")
    
    def get_jira_test_count(self, jira_id: str) -> int:
        """Get count of test cases for a Jira ID"""
        if not self.is_connected():
            return 0
        try:
            jira_column = self.worksheet.col_values(1)
            return sum(1 for j in jira_column[1:] if j == jira_id)  # Skip header
        except:
            return 0
    
    def _merge_jira_cells(self, jira_id: str):
        """Merge column A cells for a specific Jira ID"""
        try:
            # Find all rows with this Jira ID
            jira_column = self.worksheet.col_values(1)
            
            start_row = None
            end_row = None
            
            for idx, value in enumerate(jira_column):
                if value == jira_id:
                    if start_row is None:
                        start_row = idx + 1  # 1-indexed
                    end_row = idx + 1
            
            if start_row and end_row and start_row != end_row:
                # Merge cells A{start_row}:A{end_row}
                self.worksheet.merge_cells(f'A{start_row}:A{end_row}', merge_type='MERGE_ALL')
                logger.info(f"Merged cells A{start_row}:A{end_row} for {jira_id}")
                
        except Exception as e:
            logger.warning(f"Could not merge cells for {jira_id}: {e}")
    
    def merge_all_jira_cells(self):
        """Merge column A cells for all Jira IDs in the sheet"""
        if not self.is_connected():
            return
        
        try:
            jira_column = self.worksheet.col_values(1)
            
            # Find unique Jira IDs (skip header)
            unique_jiras = []
            for j in jira_column[1:]:
                if j and j not in unique_jiras:
                    unique_jiras.append(j)
            
            # Merge cells for each Jira
            for jira_id in unique_jiras:
                self._merge_jira_cells(jira_id)
                
            logger.info(f"Merged cells for {len(unique_jiras)} Jira IDs")
            
        except Exception as e:
            logger.error(f"Failed to merge all Jira cells: {e}")


_sheets_client = None

def get_sheets_client() -> SheetsClient:
    global _sheets_client
    if _sheets_client is None:
        _sheets_client = SheetsClient()
    return _sheets_client


def add_test_cases_to_sheet(
    jira_id: str,
    jira_summary: str,
    subtask_id: str,
    test_cases: List[Dict[str, Any]],
    pr_url: str = None
) -> bool:
    """Convenience function to add test cases"""
    client = get_sheets_client()
    return client.add_test_cases(jira_id, jira_summary, subtask_id, test_cases, pr_url)


if __name__ == "__main__":
    client = SheetsClient()
    if client.is_connected():
        print("✅ Successfully connected to Google Sheets!")
    else:
        print("❌ Failed to connect to Google Sheets")
