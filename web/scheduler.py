"""
scheduler.py
APScheduler — запуск пайплайна по расписанию.
"""
from apscheduler.schedulers.background import BackgroundScheduler

_scheduler = BackgroundScheduler(timezone="Europe/Kyiv")
_scheduler.start()


def update_schedule(cron_expression: str, enabled: bool, target_dir: str):
    """Обновить или удалить задание планировщика."""
    _scheduler.remove_all_jobs()

    if not enabled or not cron_expression.strip():
        return

    parts = cron_expression.strip().split()
    if len(parts) != 5:
        return

    minute, hour, day, month, day_of_week = parts
    _scheduler.add_job(
        func=_run_scheduled,
        trigger="cron",
        args=[target_dir],
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=day_of_week,
        id="pipeline_job",
        replace_existing=True,
    )


def _run_scheduled(target_dir: str):
    import pipeline_runner
    import db

    pipeline_runner.start_run(target_dir, trigger="schedule")
    db.update_last_run()


def get_next_run():
    jobs = _scheduler.get_jobs()
    return jobs[0].next_run_time if jobs else None
