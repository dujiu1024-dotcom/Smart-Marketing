from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SystemInfo:
    """Domain representation of public system metadata."""

    name: str
    environment: str
    api_version: str
