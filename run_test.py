from playwright.sync_api import sync_playwright

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto("http://localhost:8000")
        page.wait_for_timeout(2000)
        page.fill('#search-input', '000001')
        page.wait_for_timeout(1000)
        page.click('#search-suggestions li')
        page.wait_for_timeout(5000)
        page.screenshot(path="debug_kdj_fixed.png")
        browser.close()

run()
