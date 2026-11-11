"""Playwright browser smoke test for the production Web application shell."""

import asyncio
import os

from playwright.async_api import async_playwright


async def main() -> None:
    base_url = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:5173")
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page()
        page_errors: list[str] = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))

        response = await page.goto(base_url, wait_until="networkidle")
        assert response is not None and response.ok, "Web application did not return HTTP 2xx"

        heading = page.get_by_role("heading", name="门店营销执行工作台")
        await heading.wait_for(state="visible")

        status = page.get_by_role("status")
        await status.wait_for(state="visible")
        assert "前端应用运行正常" in await status.inner_text()

        disclaimer = page.get_by_text(
            "当前为工程骨架，不代表真实营销、AI 生成或渠道发布能力已接通。",
            exact=True,
        )
        await disclaimer.wait_for(state="visible")

        assert not page_errors, f"Uncaught browser errors: {page_errors}"
        print("Playwright E2E passed: application shell, status and capability disclaimer rendered.")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
