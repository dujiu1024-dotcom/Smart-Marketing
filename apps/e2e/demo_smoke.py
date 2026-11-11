"""Playwright route and page-state smoke tests for the frozen product Demo."""

import asyncio
import os

from playwright.async_api import async_playwright

BASE_URL = os.environ.get("DEMO_E2E_BASE_URL", "http://127.0.0.1:8080/demo/")


async def main() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        context = await browser.new_context(viewport={"width": 1440, "height": 1000})
        page = await context.new_page()
        page_errors: list[str] = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))

        response = await page.goto(BASE_URL, wait_until="networkidle")
        assert response is not None and response.ok, "Frozen Demo did not return HTTP 2xx"
        await page.locator("#app .shell").wait_for(state="visible")
        await page.evaluate("localStorage.clear()")
        await page.reload(wait_until="networkidle")
        await page.locator("#app .shell").wait_for(state="visible")

        async def route_to(route: str, expected_heading: str) -> None:
            await page.evaluate("(value) => { location.hash = value; }", route)
            heading = page.locator("main h1")
            await heading.wait_for(state="visible")
            actual = await heading.inner_text()
            assert expected_heading in actual, (
                f"Route #{route}: expected heading containing {expected_heading!r}, got {actual!r}"
            )

        # Store workspace and its first-level pages.
        await route_to("ai", "AI 门店运营官")
        await route_to("create", "按需制作")
        await route_to("hotspots", "发现适合本店的热点机会")
        await route_to("hotspot-detail:hot-001", "秋冬热饮与暖饮消费场景")
        await route_to("tasks", "营销任务")
        await route_to("task", "当季草莓鲜奶新品推广")
        await route_to("effects", "经营效果")
        await route_to("account-ops", "账号运营监测")
        await route_to("account-register", "登记已发布作品")

        # The seven marketing task stages are distinct interactive tabs.
        task_tabs = ["brief", "strategy", "copy", "image", "channel", "quality", "publish"]
        for tab in task_tabs:
            control = page.locator(f'[data-task-tab="{tab}"]')
            await control.click()
            assert await control.get_attribute("aria-selected") == "true", (
                f"Marketing task tab {tab!r} did not become selected"
            )
            await page.locator("#task-stage-panel").wait_for(state="visible")

        # Store knowledge pages are separate tabs under the store workspace.
        store_pages = {
            "profile": "门店档案",
            "products": "商品与服务",
            "offers": "活动与优惠",
            "brand": "品牌规范",
            "audience": "客群与经营",
            "knowledge": "门店知识库",
            "assets": "素材资产库",
            "channels": "渠道账号",
        }
        for route, tab_name in store_pages.items():
            await route_to(f"store:{route}", "门店资料")
            tab = page.locator(f'[data-store-tab="{route}"]')
            await tab.wait_for(state="visible")
            assert await tab.get_attribute("aria-selected") == "true"
            assert tab_name in await tab.inner_text()

        # Product and offer editors are independent second-level pages.
        await route_to("store-editor:product:p1", "编辑商品")
        await page.get_by_role("button", name="返回列表").wait_for(state="visible")
        await route_to("store-editor:offer:o1", "编辑活动与优惠")
        await page.get_by_role("button", name="返回列表").wait_for(state="visible")

        # Platform administration top-level pages.
        admin_pages = {
            "overview": "运营总览",
            "stores": "门店管理",
            "monitoring": "AI 运行监控",
            "capabilities": "AI 能力配置",
            "costs": "用量与成本",
            "audit": "审计日志",
            "settings": "系统配置",
        }
        for route, heading in admin_pages.items():
            await route_to(f"admin:{route}", heading)

        # Admin detail pages are reached through their parent lists.
        await route_to("admin:stores", "门店管理")
        await page.locator('[data-action="admin-open-store"]').first.click()
        await route_to("admin:store-detail", "门店详情")
        for tab in ["users", "model"]:
            control = page.locator(f'[data-admin-store-tab="{tab}"]')
            await control.click()
            assert await control.get_attribute("aria-selected") == "true"

        await route_to("admin:monitoring", "AI 运行监控")
        await page.locator('[data-action="admin-monitor-detail"]').first.click()
        await route_to("admin:monitor-detail", "AI 运行监控")

        await route_to("admin:capabilities", "AI 能力配置")
        await page.locator('[data-action="admin-edit-prompt"]').first.click()
        await route_to("admin:prompt-detail", "编辑提示词模板")
        await page.get_by_role("button", name="返回模板列表").wait_for(state="visible")

        # Browser history restores the previous route and its rendered page.
        await route_to("tasks", "营销任务")
        await page.locator('[data-action="open-task"]').first.click()
        await route_to("task", "营销任务")
        await page.go_back(wait_until="networkidle")
        await route_to("tasks", "营销任务")

        assert not page_errors, f"Uncaught browser errors: {page_errors}"
        print(
            "Frozen Demo Playwright smoke passed: 9 store routes, 8 store tabs, "
            "7 task stages, 7 admin pages, admin detail pages, editors and browser history."
        )
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
