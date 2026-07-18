"""Явная инициализация инфраструктуры веб-приложения."""
import db
import scheduler

_started = False


def start_runtime():
    """Инициализировать хранилище и один раз восстановить расписание."""
    global _started
    if _started:
        return

    db.init_db()
    scheduler.start_scheduler()
    config = db.get_schedule()
    if config.get("enabled"):
        scheduler.update_schedule(
            config.get("cron_expression", ""),
            True,
            config.get("target_dir", "original_archives"),
            config.get("output_dir") or config.get("target_dir", "original_archives"),
        )
    _started = True


def shutdown_runtime():
    """Остановить инфраструктуру; повторный вызов безопасен."""
    global _started
    scheduler.shutdown_scheduler()
    _started = False
