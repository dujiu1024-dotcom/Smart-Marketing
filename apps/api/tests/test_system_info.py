from store_operator.application.system_info import get_system_info
from store_operator.domain.system_info import SystemInfo


def test_get_system_info_returns_domain_value_from_configuration() -> None:
    result = get_system_info(app_name="AI 门店运营官 API", environment="test")

    assert result == SystemInfo(
        name="AI 门店运营官 API",
        environment="test",
        api_version="v1",
    )
