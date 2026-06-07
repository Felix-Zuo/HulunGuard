STATE_DIR = ".hulun"
LEGACY_STATE_DIR = ".longrun_guard"
STATE_FILE = "state.json"
RESUME_FILE = "resume.md"
VERIFY_FILE = "verification_report.md"
RISK_FILE = "risk.json"
RISK_REPORT_FILE = "risk_report.md"
DASHBOARD_FILE = "dashboard.html"
BOARD_FILE = "board.html"
MONITORS_DIR = "monitors"

VALID_STATUSES = {"pending", "in_progress", "done", "blocked", "dropped"}
USEFUL_EVENT_TYPES = {
    "artifact",
    "approval",
    "command",
    "evidence",
    "file_change",
    "source",
    "test",
    "tool_result",
}
FAILURE_EVENT_TYPES = {"command", "test", "tool_result", "source"}
