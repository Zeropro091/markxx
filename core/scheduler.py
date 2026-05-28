import json
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional

JOBS_PATH = Path(__file__).parent.parent / "config" / "scheduled_jobs.json"

class JobScheduler:
    def __init__(self):
        self.jobs = self.load_jobs()

    def load_jobs(self) -> List[Dict]:
        if JOBS_PATH.exists():
            try:
                with open(JOBS_PATH, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def save_jobs(self):
        JOBS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(JOBS_PATH, "w") as f:
            json.dump(self.jobs, f, indent=2)

    def add_job(self, task_prompt: str, schedule_type: str, value: str) -> Dict:
        """
        schedule_type: "interval" (value: e.g. "60" for minutes) or "daily" (value: e.g. "14:30")
        """
        job_id = str(int(time.time()))
        next_run = self.calculate_next_run(schedule_type, value)
        
        job = {
            "id": job_id,
            "task_prompt": task_prompt,
            "schedule_type": schedule_type,
            "value": value,
            "last_run": None,
            "next_run": next_run.isoformat(),
            "active": True
        }
        self.jobs.append(job)
        self.save_jobs()
        return job

    def remove_job(self, job_id: str) -> bool:
        initial_len = len(self.jobs)
        self.jobs = [j for j in self.jobs if j["id"] != job_id]
        if len(self.jobs) < initial_len:
            self.save_jobs()
            return True
        return False

    def calculate_next_run(self, schedule_type: str, value: str, from_time: datetime = None) -> datetime:
        now = from_time or datetime.now()
        if schedule_type == "interval":
            try:
                minutes = int(value)
            except ValueError:
                minutes = 60
            return now + timedelta(minutes=minutes)
        elif schedule_type == "daily":
            try:
                target_time = datetime.strptime(value.strip(), "%H:%M").time()
                target_dt = datetime.combine(now.date(), target_time)
                if target_dt <= now:
                    target_dt += timedelta(days=1)
                return target_dt
            except ValueError:
                return now + timedelta(days=1)
        return now + timedelta(days=365)
