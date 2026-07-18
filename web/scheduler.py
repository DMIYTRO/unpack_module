"""
scheduler.py
APScheduler — запуск пайплайна по расписанию.
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

_scheduler = BackgroundScheduler(timezone="Europe/Kyiv")
_scheduler.start()


def update_schedule(cron_expression: str, enabled: bool, target_dir: str, output_dir: str | None = None):
    """Обновить или удалить задание планировщика."""
    if not enabled or not cron_expression.strip():
        _scheduler.remove_all_jobs()
        return

    try:
        trigger = CronTrigger.from_crontab(cron_expression.strip(), timezone="Europe/Kyiv")
    except ValueError as exc:
        raise ValueError("Некорректное расписание cron. Нужно 5 полей, например: 0 9 * * 1-5") from exc

    # Старое задание удаляем только после успешной проверки нового выражения.
    _scheduler.remove_all_jobs()
    _scheduler.add_job(
        func=_run_scheduled,
        trigger=trigger,
        args=[target_dir, output_dir or target_dir],
        id="pipeline_job",
        replace_existing=True,
    )


def _run_scheduled(target_dir: str, output_dir: str):
    import pipeline_runner
    import db

    try:
        pipeline_runner.start_run(target_dir, output_dir, trigger="schedule")
    except pipeline_runner.PipelineRunningError:
        # Ручной запуск имеет приоритет; следующий запуск по расписанию состоится позже.
        return
    db.update_last_run()


def get_next_run():
    jobs = _scheduler.get_jobs()
    return jobs[0].next_run_time if jobs else None
