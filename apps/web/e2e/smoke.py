"""Playwright smoke and Issue #137 hotspot/effects browser flow."""

import asyncio
import json
import os

from playwright.async_api import async_playwright


STORE_ID = "11111111-1111-4111-8111-111111111111"
OPPORTUNITY_ID = "22222222-2222-4222-8222-222222222222"


async def _api_mock(route) -> None:
    request = route.request
    path = request.url.split("?", 1)[0].removeprefix("http://127.0.0.1:5173")
    method = request.method
    status = 200
    payload: object = {}

    if path == "/api/v1/auth/me":
        payload = {"user": {"id": "e2e-user", "email": "e2e@example.test"}}
    elif path == "/api/v1/auth/csrf":
        payload = {"csrf_token": "e2e-csrf-token"}
    elif path == "/api/v1/me/stores":
        payload = {
            "items": [{"id": STORE_ID, "name": "E2E 测试门店", "role": "owner"}],
            "active_store_id": STORE_ID,
        }
    elif path.endswith("/profile") and method == "GET":
        status = 404
        payload = {"detail": "profile not created"}
    elif path == "/api/v1/opportunities" and method == "GET":
        payload = {
            "items": [{
                "id": OPPORTUNITY_ID,
                "title": "E2E 春季饮品热点",
                "summary": "来自已登记来源的季节性饮品趋势。",
                "source_url": "https://news.example.test/spring-drinks",
                "published_at": "2026-11-11T08:00:00Z",
                "discovered_at": "2026-11-11T08:30:00Z",
                "expires_at": "2026-11-14T08:00:00Z",
                "region": "东京",
                "heat_value": None,
                "heat_unit": None,
                "evidence_status": "collected",
                "relevance_score": "82.5",
                "match_method": "rules",
                "matching_algorithm_version": 2,
                "reason_summary": "与已确认商品资料匹配。",
                "suggested_scenario": "春季限定饮品",
                "content_angle": "突出季节限定",
                "risk_flags": [],
                "eligibility_status": "eligible",
                "decision": None,
            }],
            "total": 1,
            "source_status": "available",
            "empty_reason": None,
        }
    elif path == f"/api/v1/opportunities/{OPPORTUNITY_ID}" and method == "GET":
        payload = {
            "id": OPPORTUNITY_ID,
            "title": "E2E 春季饮品热点",
            "summary": "来自已登记来源的季节性饮品趋势。",
            "source": {
                "url": "https://news.example.test/spring-drinks",
                "evidence_status": "collected",
                "published_at": "2026-11-11T08:00:00Z",
                "discovered_at": "2026-11-11T08:30:00Z",
            },
            "match": {
                "eligibility_status": "eligible",
                "method": "rules",
                "score": "82.5",
                "reason": "与已确认商品资料匹配。",
                "algorithm_version": 2,
                "scenario": "春季限定饮品",
                "content_angle": "突出季节限定",
                "products": ["春季限定饮品"],
                "risk_flags": [],
            },
        }
    elif path == f"/api/v1/opportunities/{OPPORTUNITY_ID}/decisions" and method == "POST":
        payload = {"id": "e2e-decision", "decision": "adopt", "replayed": False}
    elif path == "/api/v1/effects/overview":
        payload = {
            "items": [],
            "trends": [],
            "content_performance": [],
            "insights": [],
            "conversion_rates": [],
            "data_quality": {
                "total_observations": 0,
                "verified_observations": 0,
                "delayed_observations": 0,
                "incomplete_or_anomalous_observations": 0,
                "accumulating_observations": 0,
                "status": "unavailable",
                "reason": "暂无可核验数据",
            },
            "data_status": "unavailable",
            "business_outcomes": {
                "roi": None,
                "sales_growth": None,
                "store_visit_growth": None,
                "reason": "没有已核验的真实经营结果与成本证据时，不计算 ROI。",
            },
        }
    elif path == "/api/v1/effects/definitions":
        payload = {"items": [{
            "id": "metric-views",
            "source_system": "manual",
            "metric_key": "views",
            "metric_tier": "content_performance",
            "display_name": "播放/浏览",
            "unit": None,
            "definition": "作品播放量",
            "definition_version": 1,
        }]}
    elif path == "/api/v1/effects/import-xlsx" and method == "POST":
        payload = {
            "created": 2,
            "duplicates_skipped": 1,
            "import_batch_id": "e2e-xlsx-batch",
            "content_sha256": "e2e-sha256",
            "authenticity_status": "merchant_reported",
            "message": "导入成功",
        }
    elif path.startswith("/api/v1/effects/"):
        payload = {"items": [], "total": 0, "verified_count": 0}

    await route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload, ensure_ascii=False),
    )


async def main() -> None:
    base_url = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:5173")
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page_errors: list[str] = []

        login_page = await browser.new_page()
        login_page.on("pageerror", lambda error: page_errors.append(str(error)))
        response = await login_page.goto(base_url, wait_until="networkidle")
        assert response is not None and response.ok, "Web application did not return HTTP 2xx"
        await login_page.get_by_role("heading", name="登录门店工作台").wait_for(state="visible")
        await login_page.get_by_label("邮箱 *").wait_for(state="visible")
        await login_page.get_by_label("密码 *").wait_for(state="visible")
        await login_page.get_by_role("button", name="登录").wait_for(state="visible")
        await login_page.get_by_text(
            "登录使用服务端 Session Cookie 与 CSRF 防护；本页面不保存密码。",
            exact=True,
        ).wait_for(state="visible")
        await login_page.close()

        page = await browser.new_page()
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        await page.route("**/api/v1/**", _api_mock)
        response = await page.goto(f"{base_url}#hotspots", wait_until="networkidle")
        assert response is not None and response.ok, "Authenticated workspace did not return HTTP 2xx"

        await page.get_by_role("heading", name="发现营销机会").wait_for(state="visible")
        await page.get_by_role("button", name="查看详情").click()
        await page.get_by_role("heading", name="E2E 春季饮品热点").wait_for(state="visible")
        await page.get_by_role("button", name="采纳机会").click()
        await page.get_by_text("机会已采纳。你可以主动选择基于该机会制作营销内容；系统不会自动创建任务。").wait_for()
        await page.get_by_role("button", name="基于此机会制作内容").click()
        assert await page.evaluate("window.location.hash") == "#create"
        handoff = await page.evaluate(
            "JSON.parse(sessionStorage.getItem('store-operator.opportunity-handoff."
            + STORE_ID
            + "') || '{}')"
        )
        assert handoff.get("opportunity_id") == OPPORTUNITY_ID, "Opportunity handoff snapshot was not preserved"

        await page.get_by_role("link", name="经营效果").click()
        await page.get_by_role("heading", name="经营效果").wait_for(state="visible")
        upload = page.get_by_label("Excel 工作簿（.xlsx，最大 5 MB）")
        await upload.set_input_files({
            "name": "metrics.xlsx",
            "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "buffer": b"PK\\x03\\x04",
        })
        await page.get_by_role("button", name="导入 Excel").click()
        await page.get_by_text("Excel 导入完成：新增 2 条，重复跳过 1 条。").wait_for()

        assert not page_errors, f"Uncaught browser errors: {page_errors}"
        print(
            "Playwright E2E passed: login screen, hotspot detail/adoption, explicit task handoff, "
            "effects workspace and XLSX import feedback."
        )
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
