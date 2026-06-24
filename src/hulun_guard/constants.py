STATE_DIR = ".hulun"
LEGACY_STATE_DIR = ".longrun_guard"
STATE_FILE = "state.json"
RESUME_FILE = "resume.md"
VERIFY_FILE = "verification_report.md"
RISK_FILE = "risk.json"
RISK_REPORT_FILE = "risk_report.md"
INGEST_QUEUE_FILE = "ingest_queue.jsonl"
INGEST_DEAD_LETTER_FILE = "ingest_dead_letter.jsonl"
DASHBOARD_FILE = "dashboard.html"
BOARD_FILE = "board.html"
MONITORS_DIR = "monitors"
CONVERSATIONS_DIR = "conversations"

VALID_STATUSES = {"pending", "in_progress", "done", "blocked", "dropped"}
VALID_EVENT_PHASES = {
    "explore",
    "plan",
    "implement",
    "verify",
    "recover",
    "summarize",
    "final",
    "orchestrate",
}
USEFUL_EVENT_TYPES = {
    "artifact",
    "approval",
    "checkpoint",
    "command",
    "criterion",
    "evidence",
    "file_change",
    "source",
    "step",
    "test",
    "tool_result",
    "verification",
}
FAILURE_EVENT_TYPES = {"agent_error", "command", "conversation_error", "llm_call", "test", "tool_result", "source"}
