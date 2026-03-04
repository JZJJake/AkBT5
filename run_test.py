from playwright.sync_api import sync_playwright

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_viewport_size({"width": 1280, "height": 720})

        # Go to the local app
        page.goto("http://127.0.0.1:8000")

        # Wait for the chart to load
        page.wait_for_selector("#chart-container", state="visible")
        page.wait_for_timeout(2000) # give echarts a moment to render

        # Click a stock to render something
        page.locator("#stock-list li").first.click()
        page.wait_for_timeout(2000)

        # Take a screenshot to verify KDJ contour lines and labels
        page.screenshot(path="debug_labels_and_lines.png")

        browser.close()

if __name__ == "__main__":
    run()
