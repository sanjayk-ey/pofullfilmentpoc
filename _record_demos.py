"""Automated screen-recorder for the two demo flows.

Drives the running Streamlit app (http://localhost:8501) with Playwright,
records the browser session to .webm, then converts to .mp4 using the ffmpeg
binary bundled by imageio-ffmpeg.

Usage:  python _record_demos.py [happy|csr|both]
"""
import os
import sys
import glob
import shutil
import subprocess

from playwright.sync_api import sync_playwright, expect
import imageio_ffmpeg

BASE = os.path.dirname(os.path.abspath(__file__))
URL = "http://localhost:8501"
OUT_DIR = os.path.join(BASE, "demo", "recordings")
TMP_DIR = os.path.join(BASE, "_rec_tmp")
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
VW, VH = 1600, 900

HAPPY_PO = open(os.path.join(BASE, "demo", "Happy-Flow-PO.txt"), encoding="utf-8").read()
CSR_PO = open(os.path.join(BASE, "demo", "CSR-Approval-PO.txt"), encoding="utf-8").read()


def reset_ledger():
    """Clear the duplicate-PO ledger so a re-run never trips the duplicate gate."""
    f = os.path.join(BASE, "data", "submitted_pos.json")
    if os.path.exists(f):
        os.remove(f)
        print("  reset ledger:", f)


def submit_po(page, po_text):
    box = page.get_by_placeholder("Paste your PO text here", exact=False)
    box.wait_for(state="visible", timeout=30000)
    box.click()
    box.fill(po_text)
    page.keyboard.press("Enter")


def select_and_approve(page, marker_text, label="Approve selected"):
    """Wait for a gate identified by marker_text, pick the first row, approve."""
    page.get_by_text(marker_text, exact=False).first.wait_for(timeout=120000)
    page.wait_for_timeout(800)
    page.get_by_role("button", name="⚪ Select").first.click()
    page.wait_for_timeout(1200)  # let the on_click rerun settle
    page.get_by_role("button", name=label).first.click()
    page.wait_for_timeout(1200)


def record(kind, run):
    os.makedirs(TMP_DIR, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(
            viewport={"width": VW, "height": VH},
            record_video_dir=TMP_DIR,
            record_video_size={"width": VW, "height": VH},
        )
        page = ctx.new_page()
        page.set_default_timeout(120000)
        page.goto(URL)
        page.wait_for_timeout(2500)
        run(page)
        # Hold on the completion screen so the video ends cleanly.
        page.get_by_text("created successfully", exact=False).first.wait_for(timeout=180000)
        page.wait_for_timeout(4000)
        video_path = page.video.path()
        ctx.close()      # finalizes the .webm
        browser.close()

    mp4 = os.path.join(OUT_DIR, f"{kind}.mp4")
    if os.path.exists(mp4):
        os.remove(mp4)
    subprocess.run(
        [FFMPEG, "-y", "-i", video_path, "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", mp4],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    print("  wrote", mp4, f"({os.path.getsize(mp4)//1024} KB)")
    shutil.rmtree(TMP_DIR, ignore_errors=True)


def happy_flow(page):
    submit_po(page, HAPPY_PO)


def csr_flow(page):
    submit_po(page, CSR_PO)
    # Gate 1 — obsolete SKU substitution (Line 1)
    select_and_approve(page, "is OBSOLETE")
    # Gate 2 — invalid quantity (Line 4). st.text_input only commits its value
    # on Enter/blur, so press Enter to trigger the rerun that enables the button.
    qty = page.get_by_placeholder("Type the correct quantity", exact=False)
    qty.wait_for(timeout=120000)
    page.wait_for_timeout(800)
    qty.click()
    qty.fill("15")
    qty.press("Enter")
    page.wait_for_timeout(1500)
    use_btn = page.get_by_role("button", name="✍️ Use my entry").first
    expect(use_btn).to_be_enabled(timeout=30000)
    use_btn.click()
    page.wait_for_timeout(1200)
    # Gate 3 — UOM conversion (Line 5): dropdown pick (1-10 or custom) + approve.
    page.get_by_text("quantity to order in", exact=False).first.wait_for(timeout=120000)
    page.wait_for_timeout(800)
    page.locator('div[data-baseweb="select"]').first.click()
    page.wait_for_timeout(600)
    page.get_by_role("option", name="6", exact=True).first.click()
    page.wait_for_timeout(1200)
    uom_ok = page.get_by_role("button", name="✅ Approve selected").first
    expect(uom_ok).to_be_enabled(timeout=30000)
    uom_ok.click()
    page.wait_for_timeout(1200)
    # Gate 4 — unresolved buyer
    select_and_approve(page, "buyer directory")
    # Gate 5 — pricing / margin exception
    page.get_by_text("PRICING_EXCEPTION", exact=False).first.wait_for(timeout=180000)
    page.wait_for_timeout(1500)
    page.get_by_role("button", name="✅ Approve", exact=True).first.click()
    page.wait_for_timeout(1500)


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    reset_ledger()
    if which in ("happy", "both"):
        print("Recording HAPPY flow...")
        record("happy-flow", happy_flow)
    if which in ("csr", "both"):
        print("Recording CSR approval flow...")
        record("csr-approval", csr_flow)
    print("Done.")


if __name__ == "__main__":
    main()
