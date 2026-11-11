from store_operator.domain.system_info import SystemInfo


def get_system_info(*, app_name: str, environment: str) -> SystemInfo:
    """Build public system metadata from application configuration."""

    return SystemInfo(name=app_name, environment=environment, api_version="v1")
