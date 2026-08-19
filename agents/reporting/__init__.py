"""Reporting agent package."""

__all__ = ["run_reporting_agent"]


def __getattr__(name: str):
    if name == "run_reporting_agent":
        from agents.reporting.loop import run_reporting_agent

        return run_reporting_agent
    raise AttributeError(name)
