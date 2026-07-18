"""
scheduler.py
APScheduler — запуск пайплайна по расписанию.
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

_scheduler = None


def start_scheduler():
    """Запустить планировщик один раз и вернуть его экземпляр."""
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone="Europe/Kyiv")
    if not _scheduler.running:
        _scheduler.start()
    return _scheduler


def shutdown_scheduler(wait: bool = False):
    """Идемпотентно остановить фоновый поток планировщика."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=wait)
    _scheduler = None


def update_schedule(cron_expression: str, enabled: bool, target_dir: str, output_dir: str | None = None):
    """Обновить или удалить задание планировщика."""
    scheduler = start_scheduler()
    if not enabled or not cron_expression.strip():
        scheduler.remove_all_jobs()
        return

    try:
        trigger = CronTrigger.from_crontab(cron_expression.strip(), timezone="Europe/Kyiv")
    except ValueError as exc:
        raise ValueError("Некорректное расписание cron. Нужно 5 полей, например: 0 9 * * 1-5") from exc

    # Старое задание удаляем только после успешной проверки нового выражения.
    scheduler.remove_all_jobs()
    scheduler.add_job(
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
    if _scheduler is None:
        return None
    jobs = _scheduler.get_jobs()
    return jobs[0].next_run_time if jobs else None
