from dataclasses import dataclass, field
from typing import List, Dict

@dataclass
class TaskState:
    project_name: str = ""
    description: str = ""
    language: str = "python"
    
    # State flags
    status: str = "init"          # init, planned, coded, tested, failed, complete
    current_agent: str = "orchestrator"
    
    # Data payloads
    plan: Dict = field(default_factory=dict)
    files_to_write: List[Dict] = field(default_factory=list)
    code_files: Dict[str, str] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)
    
    # Execution & Error handling
    run_command: str = ""
    last_output: str = ""
    last_error: str = ""
    error_type: str = "none"
    fix_attempts: int = 0
    max_fix_attempts: int = 5
    
    def log_event(self, agent: str, message: str):
        """Silently logs an event to the DB (if configured)."""
        self.current_agent = agent
        try:
            from core.audit_logger import log_action
            # Record state changes in the PostgreSQL database
            log_action(f"Agent:{agent}", {"status": self.status}, "INFO", message)
            print(f"[{agent.upper()}] {message}")
        except ImportError:
            print(f"[{agent.upper()}] {message}")
        except Exception as e:
            print(f"[{agent.upper()}] (Audit Log Error: {e}) {message}")
