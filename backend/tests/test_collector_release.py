"""ARQ must retain inherited jobs and permit a running job to finish."""
from arq.worker import get_kwargs

from app.workers.collector import WorkerSettings as Base
from app.workers.collector_release import WorkerSettings


def test_graceful_worker_preserves_every_original_job_and_limit():
    settings = get_kwargs(WorkerSettings)
    assert settings["functions"] is Base.functions
    assert settings["cron_jobs"] is Base.cron_jobs
    assert settings["max_jobs"] == Base.max_jobs
    assert settings["job_timeout"] == Base.job_timeout
    assert settings["job_completion_wait"] == Base.job_timeout
