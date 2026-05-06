import uuid
import json
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import List, Optional
from memory import load_profile, save_profile, save_job, load_job

# ── Result schema ──────────────────────────────────────────────────────────────

@dataclass
class ClawItem:
    name: str
    price: Optional[float]
    sale: bool
    image: Optional[str]
    upc: str
    added: bool = False
    reason: str = ""

@dataclass
class ClawSection:
    title: str
    type: str          # "meal" | "cart_summary" | "sale_alert" | "restock"
    items: List[ClawItem] = field(default_factory=list)
    recipe: List[str] = field(default_factory=list)

@dataclass
class ClawAction:
    label: str
    url: Optional[str] = None
    action: Optional[str] = None   # "rerun_job" | "view_cart" | etc.

@dataclass
class ClawResult:
    job_id: str
    task_type: str
    status: str                    # "done" | "failed" | "needs_auth"
    summary: str
    sections: List[ClawSection] = field(default_factory=list)
    actions: List[ClawAction] = field(default_factory=list)
    push_sent: bool = False

    def to_dict(self):
        return asdict(self)

# ── Base task class ────────────────────────────────────────────────────────────

class ClawTask:
    """All claw features extend this. Override run()."""

    task_type: str = "base"

    def run(self, user_id: str, payload: dict) -> ClawResult:
        raise NotImplementedError

    def _make_job_id(self):
        return str(uuid.uuid4())[:8]

    def _get_profile(self, user_id: str):
        return load_profile(user_id)

    def _save_job(self, job_id, user_id, status, result,
                  schedule=None, scheduled_at=None):
        save_job({
            "id":           job_id,
            "user_id":      user_id,
            "task_type":    self.task_type,
            "status":       status,
            "result":       result.to_dict() if result else {},
            "schedule":     schedule,
            "scheduled_at": scheduled_at,
            "last_run_at":  datetime.utcnow().isoformat(),
        })

# ── Task registry ──────────────────────────────────────────────────────────────
# To add a new claw feature:
#   1. Create tasks/your_task.py with class YourTask(ClawTask)
#   2. Import it below
#   3. Add one line to TASK_REGISTRY
#   Nothing else changes.

def _load_registry():
    from tasks.auto_cart import AutoCartTask
    from tasks.meal_planner import MealPlannerTask
    return {
        "auto_cart": AutoCartTask,
        "meal_planner": MealPlannerTask,
    }

TASK_REGISTRY: dict = _load_registry()


def get_task(task_type: str) -> ClawTask:
    cls = TASK_REGISTRY.get(task_type)
    if not cls:
        raise ValueError(f"Unknown task type: {task_type}")
    return cls()

def run_job(job_id: str, user_id: str, task_type: str, payload: dict) -> ClawResult:
    """Called by API endpoints and by APScheduler."""
    task = get_task(task_type)

    # Mark as running
    save_job({
        "id":          job_id,
        "user_id":     user_id,
        "task_type":   task_type,
        "status":      "running",
        "payload":     payload,
        "last_run_at": datetime.utcnow().isoformat(),
    })

    try:
        result = task.run(user_id, payload)
        save_job({
            "id":          job_id,
            "user_id":     user_id,
            "task_type":   task_type,
            "status":      result.status,
            "payload":     payload,
            "result":      result.to_dict(),
            "last_run_at": datetime.utcnow().isoformat(),
        })
        return result

    except Exception as e:
        err_result = ClawResult(
            job_id=job_id,
            task_type=task_type,
            status="failed",
            summary=f"Task failed: {str(e)}"
        )
        save_job({
            "id":          job_id,
            "user_id":     user_id,
            "task_type":   task_type,
            "status":      "failed",
            "payload":     payload,
            "result":      err_result.to_dict(),
            "last_run_at": datetime.utcnow().isoformat(),
        })
        return err_result
