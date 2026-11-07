"""Preserve the deployed jobs and let them finish before worker shutdown."""

from app.workers.collector import WorkerSettings as BaseWorkerSettings


class WorkerSettings(BaseWorkerSettings):
    # A deployment may wait as long as a job is normally permitted to run.
    job_completion_wait = BaseWorkerSettings.job_timeout


# ARQ reads settings_cls.__dict__, not inherited attributes. Materialize the
# existing settings so the original functions, cron jobs and limits all survive.
for _name, _value in vars(BaseWorkerSettings).items():
    if not _name.startswith("_") and _name != "job_completion_wait":
        setattr(WorkerSettings, _name, _value)
del _name, _value
