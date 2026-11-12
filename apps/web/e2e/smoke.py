"""Playwright browser smoke test for the production identity entry point."""

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

        await page.get_by_role("heading", name="登录工作台").wait_for(state="visible")
        await page.get_by_label("邮箱").wait_for(state="visible")
        await page.get_by_label("密码").wait_for(state="visible")
        await page.get_by_role("button", name="登录").wait_for(state="visible")
        await page.get_by_text(
            "登录凭证由服务端通过 HttpOnly Cookie 管理；页面不会保存 Session Token。",
            exact=True,
        ).wait_for(state="visible")

        assert not page_errors, f"Uncaught browser errors: {page_errors}"
        print("Playwright E2E passed: login entry, credential fields and Session security notice rendered.")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
