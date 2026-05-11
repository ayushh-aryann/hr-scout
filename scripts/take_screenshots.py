"""Take screenshots of the HR Scout UI using Playwright."""

import asyncio
import json
import time
from pathlib import Path

SESSION_FILE = next(Path("outputs/sessions").glob("*.json"), None)
BASE = "http://127.0.0.1:8000"
OUT = Path("assets/screenshots")
OUT.mkdir(parents=True, exist_ok=True)

async def screenshot(page, name, wait=800):
    await asyncio.sleep(wait / 1000)
    path = str(OUT / f"{name}.png")
    await page.screenshot(path=path, full_page=True)
    print(f"  saved: {name}.png")
    return path

async def main():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await context.new_page()

        # 1. Landing / Dashboard
        print("Screenshotting: landing page...")
        await page.goto(BASE, wait_until="networkidle")
        await screenshot(page, "01_dashboard")

        # 2. Upload page (click Start Analysis)
        print("Screenshotting: upload page...")
        await page.click("text=Start Analysis")
        await page.wait_for_timeout(600)
        await screenshot(page, "02_upload_page")

        # 3. Load sample JD
        print("Screenshotting: JD filled...")
        await page.click("text=load sample")
        await page.wait_for_timeout(400)
        await screenshot(page, "03_jd_filled")

        # 4. Run analysis via API directly, then navigate to results
        if SESSION_FILE:
            session_data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
            sid = session_data["session_id"]

            # Inject session into the page via JS and render results view
            print("Screenshotting: results/ranking table...")
            await page.goto(BASE, wait_until="networkidle")

            # Use fetch in browser to get session then render
            await page.evaluate(f"""
                async () => {{
                    const res = await fetch('{BASE}/api/v1/sessions/{sid}');
                    const session = await res.json();
                    window.__session = session;
                }}
            """)
            # Trigger React state update by dispatching a custom event
            await page.evaluate("""
                () => {
                    window.__injectedSession = window.__session;
                }
            """)
            await page.wait_for_timeout(500)

        # 5. Screenshot the HTML report directly
        print("Screenshotting: HTML report (ranking table)...")
        html_report = Path("outputs/html/shortlist_report.html")
        if html_report.exists():
            await page.goto(f"file:///{html_report.resolve().as_posix()}", wait_until="networkidle")
            await page.wait_for_timeout(800)
            await screenshot(page, "04_ranking_table")

            # Scroll down to candidate detail cards
            await page.evaluate("window.scrollTo(0, 1200)")
            await page.wait_for_timeout(400)
            await screenshot(page, "05_scoring_breakdown")

        # 6. Screenshot the override report
        print("Screenshotting: override report...")
        override_report = Path("outputs/html/shortlist_with_overrides.html")
        if override_report.exists():
            await page.goto(f"file:///{override_report.resolve().as_posix()}", wait_until="networkidle")
            await page.evaluate("window.scrollTo(0, 2400)")
            await page.wait_for_timeout(400)
            await screenshot(page, "06_override_feature")

        # 7. API docs screenshot
        print("Screenshotting: API docs...")
        await page.goto(f"{BASE}/docs", wait_until="networkidle")
        await page.wait_for_timeout(1200)
        await screenshot(page, "07_api_docs")

        # 8. Full app landing (wider)
        print("Screenshotting: full hero...")
        await context.close()
        context2 = await browser.new_context(viewport={"width": 1440, "height": 960})
        page2 = await context2.new_page()
        await page2.goto(BASE, wait_until="networkidle")
        await page2.wait_for_timeout(1000)
        await screenshot(page2, "08_hero_full")
        await context2.close()

        await browser.close()
        print(f"\nAll screenshots saved to: assets/screenshots/")

if __name__ == "__main__":
    asyncio.run(main())
