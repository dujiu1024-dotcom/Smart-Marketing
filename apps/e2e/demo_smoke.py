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
            await page.wait_for_function(
                "(expected) => document.querySelector('main h1')?.innerText.includes(expected)",
                arg=expected_heading,
            )
            actual = await page.locator("main h1").inner_text()
            assert expected_heading in actual, (
                f"Route #{route}: expected heading containing {expected_heading!r}, got {actual!r}"
            )

        # Store workspace and its first-level pages.
        await route_to("ai", "AI 门店运营官")
        await route_to("create", "按需制作")
        await route_to("hotspots", "发现适合本店的热点机会")
        await route_to("hotspot-detail:hot-001", "秋冬热饮与暖饮消费场景")
        await route_to("tasks", "营销任务")
        await page.locator('[data-action="open-task"]').first.click()
        await route_to("task", "当季草莓鲜奶新品推广")

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

        # Product and offer editors are independent second-level pages reached through their lists.
        await route_to("store:products", "门店资料")
        await page.locator('[data-action="edit-product"]').first.click()
        await route_to("store-editor:product:p1", "编辑商品 / 服务")
        await page.get_by_label("商品 / 服务名称").wait_for(state="visible")
        await page.get_by_role("button", name="返回列表", exact=True).click()
        await route_to("store:offers", "门店资料")
        await page.locator('[data-action="edit-offer"]').first.click()
        await route_to("store-editor:offer:o1", "编辑活动与优惠")
        await page.get_by_label("活动名称").wait_for(state="visible")
        await page.get_by_role("button", name="返回列表", exact=True).wait_for(state="visible")

        # Platform administration top-level pages.
        admin_pages = {
            "overview": "运营总览",
            "stores": "门店管理",
            "monitoring": "AI 运行监控",
            "capabilities": "AI 能力与提示词配置",
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

        await route_to("admin:capabilities", "AI 能力与提示词配置")
        await page.locator('[data-action="admin-edit-prompt"]').first.click()
        await route_to("admin:prompt-detail", "编辑提示词模板")
        await page.get_by_role("button", name="返回模板列表").wait_for(state="visible")

        # Browser history restores the previous route and its rendered page.
        await route_to("tasks", "营销任务")
        await page.locator('[data-action="open-task"]').first.click()
        await route_to("task", "当季草莓鲜奶新品推广")
        await page.go_back(wait_until="networkidle")
        await route_to("tasks", "营销任务")


        # Full local Demo marketing workflow: verify gates, review, quality and frozen handoff.
        await route_to("tasks", "营销任务")
        await page.locator('[data-action="open-task"]').first.click()
        await route_to("task", "当季草莓鲜奶新品推广")

        await page.locator('[data-task-tab="strategy"]').click()
        await page.get_by_role("heading", name="请先完成需求理解").wait_for(state="visible")
        await page.locator('[data-task-tab="brief"]').click()
        await page.locator('[data-action="confirm-brief"]').click()
        await page.locator('[data-task-tab="strategy"]').wait_for(state="visible")
        await page.locator("#hotspotDecision").select_option("skipped")
        await page.locator("#hotspotDecisionReason").fill("本次按明确新品推广需求执行，不依赖外部热点。")
        await page.locator('[data-action="confirm-strategy"]').click()

        # Image production must remain blocked until every target copy is approved.
        await page.locator('[data-task-tab="image"]').click()
        await page.locator('[data-action="generate-image"]').click()
        await page.get_by_text("请先审核通过所有目标渠道的文案版本").wait_for(state="visible")

        await page.locator('[data-task-tab="copy"]').click()
        for platform in ["xhs", "douyin"]:
            await page.locator(f'[data-copy-platform="{platform}"]').click()
            await page.locator('[data-action="approve-copy"]').click()

        await page.locator('[data-task-tab="image"]').click()
        await page.locator('[data-action="generate-image"]').click()
        await page.locator('[data-action="approve-image"]').click()

        await page.locator('[data-task-tab="channel"]').click()
        for platform in ["小红书", "抖音"]:
            await page.locator(f'[data-action="preview-channel"][data-id="{platform}"]').click()
            await page.get_by_role("button", name="关闭").click()

        await page.locator('[data-task-tab="quality"]').click()
        await page.locator('[data-action="run-quality"]').click()
        await page.get_by_text("质检通过", exact=True).wait_for(state="visible")

        await page.locator('[data-task-tab="publish"]').click()
        await page.locator("#publishNote").fill("已核对需求、策略、文案、图片及商品事实，确认冻结当前版本。")
        await page.locator("#publishConfirm").check()
        await page.locator('[data-action="save-publish"]').click()
        package_label = page.get_by_text("内容包编号：", exact=False)
        await package_label.wait_for(state="visible")
        package_text = await package_label.inner_text()
        assert "pkg-" in package_text, f"Unexpected frozen package label: {package_text!r}"
        package_id = "pkg-" + package_text.split("pkg-", 1)[1].split()[0]

        # A repeated submission of the same approved content version must reuse the frozen package.
        await page.locator('[data-action="save-publish"]').click()
        await page.get_by_text("当前内容版本已冻结，无需重复提交").wait_for(state="visible")
        assert package_id in await package_label.inner_text()

        # Refresh must restore the frozen package without pretending an external publish occurred.
        await page.reload(wait_until="networkidle")
        await route_to("task", "当季草莓鲜奶新品推广")
        await page.locator('[data-task-tab="publish"]').click()
        restored_package = page.get_by_text("内容包编号：", exact=False)
        await restored_package.wait_for(state="visible")
        assert package_id in await restored_package.inner_text()
        await page.get_by_text("只保存冻结版本的内容包。渠道未连接时，不会向外部平台发布。").wait_for(
            state="visible"
        )

        # Mobile viewport and keyboard navigation are part of the Demo acceptance gate.
        await page.set_viewport_size({"width": 390, "height": 844})
        brief_tab = page.locator('[data-task-tab="brief"]')
        await brief_tab.focus()
        await brief_tab.press("ArrowRight")
        assert await page.locator('[data-task-tab="strategy"]').get_attribute(
            "aria-selected"
        ) == "true"
        horizontal_overflow = await page.evaluate(
            "document.documentElement.scrollWidth - window.innerWidth"
        )
        assert horizontal_overflow <= 2, (
            f"Mobile Demo has unexpected horizontal overflow: {horizontal_overflow}px"
        )

        assert not page_errors, f"Uncaught browser errors: {page_errors}"
        print(
            "Frozen Demo Playwright smoke passed: 9 store routes, 8 store tabs, "
            "7 task stages, 7 admin pages, admin detail pages, editors and browser history."
        )
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
