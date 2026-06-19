"""
One-off screenshot capture script for docs/screenshots/ (v1.6 public release
hardening). Run against a Streamlit instance started with no ANTHROPIC_API_KEY
(see docs/screenshots/README or the v1.6 deliverables report for the exact
invocation). Not part of the test suite or app runtime.
"""

import time

from playwright.sync_api import sync_playwright

BASE_URL = "http://localhost:8502"
OUT_DIR = "docs/screenshots"


def wait_for_app(page):
    page.wait_for_selector("text=Denial Prevention Copilot", timeout=15000)
    time.sleep(1.5)


def select_sample_claim(page, label_substring):
    combobox = page.locator('[data-testid="stSelectbox"]').first
    combobox.click()
    time.sleep(0.3)
    page.get_by_text(label_substring, exact=False).first.click()
    time.sleep(1)


def click_button(page, text):
    page.get_by_role("button", name=text).first.click()
    page.wait_for_selector("text=Checks run:", timeout=15000)
    time.sleep(1.5)


def snap(page, path):
    # Streamlit's main content area scrolls inside a div, not <body>, so
    # full_page=True screenshots clip at the viewport. Resize the viewport
    # to the actual content height first so the screenshot captures it all.
    height = page.locator('[data-testid="stMain"]').evaluate("el => el.scrollHeight")
    page.set_viewport_size({"width": 1400, "height": max(height + 50, 1100)})
    time.sleep(0.3)
    page.screenshot(path=path)
    page.set_viewport_size({"width": 1400, "height": 1100})


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 1100})
        page.goto(BASE_URL)
        wait_for_app(page)

        # 1. AI disabled state (sidebar) — default sample mode, CLM-001 selected
        snap(page, f"{OUT_DIR}/01_ai_disabled_state.png")

        # 2. Clean claim — CLM-003 rule-layer-only review (NCCI only, no escalation)
        select_sample_claim(page, "CLM-003")
        click_button(page, "Review Claim (rule layer only)")
        snap(page, f"{OUT_DIR}/02_clean_path_ncci_finding.png")

        # 3. Multi-finding claim (CLM-001) — rule findings + cached AI artifacts banner
        select_sample_claim(page, "CLM-001")
        click_button(page, "Review Claim (rule layer only)")
        snap(page, f"{OUT_DIR}/03_multi_finding_with_cached_ai.png")

        # 4. Coding finding scenario (CLM-002) — cached coding finding
        select_sample_claim(page, "CLM-002")
        click_button(page, "Review Claim (rule layer only)")
        snap(page, f"{OUT_DIR}/04_coding_finding_cached.png")

        # 5. Coverage finding scenario (CLM-005) — cached coverage finding
        select_sample_claim(page, "CLM-005")
        click_button(page, "Review Claim (rule layer only)")
        snap(page, f"{OUT_DIR}/05_coverage_finding_cached.png")

        # 6. Invalid NPI scenario — Manual Claim Entry mode
        page.get_by_text("Manual Claim Entry", exact=False).first.click()
        time.sleep(1)
        page.get_by_role("textbox", name="Claim ID *").fill("CLM-MANUAL-001")
        page.locator('[data-testid="stSelectbox"]', has_text="Payer").first.click()
        time.sleep(0.3)
        page.get_by_role("option", name="Medicare", exact=True).click()
        time.sleep(0.3)
        page.get_by_role("textbox", name="Provider NPI (optional)").fill("1234567890")
        page.get_by_role("textbox", name="CPT", exact=True).first.fill("99213")
        page.get_by_role("textbox", name="ICD1", exact=True).first.fill("Z00.00")
        time.sleep(0.5)
        click_button(page, "Review Claim (rule layer only)")
        snap(page, f"{OUT_DIR}/06_invalid_npi_short_circuit.png")

        browser.close()


if __name__ == "__main__":
    main()
