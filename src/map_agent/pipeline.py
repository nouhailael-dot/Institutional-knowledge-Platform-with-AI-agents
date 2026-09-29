"""Entry point for the controlled, resumable map workflow."""

from src.map_agent.research import build_controlled_map


def build_map(description: str, plan: dict | None = None, run=None) -> dict:
    """Execute the saved plan within its tracked session."""
    return build_controlled_map(description, plan, run)
