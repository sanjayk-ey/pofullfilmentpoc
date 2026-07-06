"""Real-browser test harness.

Launches headless Chromium, drives the Streamlit app the way a CSR would, and
captures screenshots + JS console logs at each interesting checkpoint. Used
to catch rendering bugs (stuck reruns, duplicate sidebar, missing scroll,
resolved-card layout) that AppTest cannot detect because it never renders.

Run with:  python _browser_test.py
Artifacts:  ./_browser_artifacts/*.png  +  ./_browser_artifacts/console.log
"""
import os
import sys
import time
import pathlib
from playwright.sync_api import sync_playwright

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

APP_URL = "http://localhost:8501"
ART = pathlib.Path(__file__).parent / "_browser_artifacts"
ART.mkdir(exist_ok=True)

# Clear old artifacts
for f in ART.iterdir():
    if f.is_file():
        f.unlink()

console_log = ART / "console.log"


def demo(name):
    with open(f"demo/{name}", encoding="utf-8") as f:
        return f.read()


def dump_page(page, tag):
    """Save a screenshot + a snippet of what's visible so we can compare
    what the browser is showing to what we expect from the code."""
    fn = ART / f"{tag}.png"
    page.screenshot(path=str(fn), full_page=True)
    # Grab a small text extract so we can grep for expected labels
    text = page.evaluate("() => document.body.innerText")
    (ART / f"{tag}.txt").write_text(text[:12000], encoding="utf-8", errors="replace")
    # Widget census
    counts = page.evaluate("""
        () => ({
            chat_messages: document.querySelectorAll('[data-testid="stChatMessage"]').length,
            status_widgets: document.querySelectorAll('[data-testid="stStatusWidget"]').length,
            expanders: document.querySelectorAll('[data-testid="stExpander"]').length,
            sidebar_captions: (document.querySelector('[data-testid="stSidebar"]') || {innerText:''})
                .innerText.split('\\n').filter(l => l.includes('Version 2.0')).length,
            buttons_by_label: Array.from(document.querySelectorAll('button')).map(b => b.innerText.trim()).filter(Boolean),
        })
    """)
    print(f"  [{tag}] chats={counts['chat_messages']} statuses={counts['status_widgets']} "
          f"expanders={counts['expanders']} sidebar_v2={counts['sidebar_captions']} "
          f"buttons={counts['buttons_by_label'][:6]}...")
    return counts


def wait_for_streamlit_idle(page, timeout_ms=15000):
    """Streamlit shows a 'Running...' toast while rerunning. Wait for it to go away."""
    end = time.time() + timeout_ms / 1000
    while time.time() < end:
        running = page.evaluate("""
            () => !!document.querySelector('[data-testid="stStatusWidget"] [data-testid="stStatusWidget"]')
                  || document.body.innerText.includes('Running...')
        """)
        if not running:
            time.sleep(0.3)
            return True
        time.sleep(0.2)
    print("  [!] timed out waiting for Streamlit to become idle")
    return False


def click_button_by_label(page, label):
    """Streamlit renders buttons as <button> with the label as visible text."""
    buttons = page.query_selector_all("button")
    for b in buttons:
        try:
            if label in (b.inner_text() or ""):
                b.scroll_into_view_if_needed()
                b.click()
                return True
        except Exception:
            continue
    print(f"  [!] button labelled containing {label!r} not found")
    return False


def run():
    # Reset the duplicate PO store so PO-1 isn't flagged as a repeat from
    # a previous test run.
    from modules import duplicate_checker as dup
    dup.reset_store()
    print("== Duplicate store reset ==")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1400, "height": 900})
        page = context.new_page()

        # Collect console messages for later analysis
        errors = []
        page.on("console", lambda msg: (
            console_log.open("a", encoding="utf-8", errors="replace")
                       .write(f"{msg.type}: {msg.text}\n"),
            errors.append(msg.text) if msg.type == "error" else None
        ))
        page.on("pageerror", lambda err: (
            console_log.open("a", encoding="utf-8", errors="replace")
                       .write(f"PAGEERROR: {err}\n"),
            errors.append(str(err))
        ))

        print("== Loading app ==")
        page.goto(APP_URL, wait_until="load", timeout=30000)
        # Streamlit's React app takes several seconds to mount + connect its
        # WebSocket. Wait until either the sidebar OR the chat input shows.
        for _ in range(30):
            time.sleep(1)
            has_sidebar = page.evaluate(
                "() => !!document.querySelector('[data-testid=\"stSidebar\"]')"
            )
            has_chat = page.evaluate(
                "() => !!document.querySelector('[data-testid=\"stChatInput\"] textarea')"
            )
            if has_sidebar and has_chat:
                break
            print(f"  waiting for mount... sidebar={has_sidebar} chat={has_chat}")
        dump_page(page, "00_landing")

        # ── PO-1 happy path ──────────────────────────────────────────────────
        print("\n== PO-1 happy path ==")
        chat = page.query_selector('[data-testid="stChatInput"] textarea')
        chat.fill(demo("Happy-Flow-PO.txt"))
        chat.press("Enter")

        # Poll while pipeline animates. The happy path has ~35s of animations.
        print("  waiting for happy flow to reach 'Order fully processed'...")
        end = time.time() + 90
        finished = False
        checkpoint = 0
        while time.time() < end:
            time.sleep(2)
            checkpoint += 1
            text = page.evaluate("() => document.body.innerText")
            if "Order fully processed" in text:
                finished = True
                break
            # Take checkpoint snapshots so we can inspect the intermediate states
            if checkpoint % 3 == 0:
                dump_page(page, f"po1_check_{checkpoint:02d}")

        dump_page(page, "po1_final")
        print(f"  PO-1 finished: {finished}")

        # Sidebar sanity — should only ever have one "Version 2.0" caption
        sidebar_v2 = page.evaluate("""
            () => (document.querySelector('[data-testid="stSidebar"]') || {innerText:''})
                     .innerText.split('\\n').filter(l => l.includes('Version 2.0')).length
        """)
        print(f"  sidebar 'Version 2.0' count: {sidebar_v2}")

        # Clear conversation for PO-2
        click_button_by_label(page, "New / clear conversation")
        time.sleep(2)
        dump_page(page, "10_after_clear")

        # ── PO-2 exception flow ──────────────────────────────────────────────
        print("\n== PO-2 exceptions — click Approve on each decision ==")
        chat = page.query_selector('[data-testid="stChatInput"] textarea')
        chat.fill(demo("CSR-Approval-PO.txt"))
        chat.press("Enter")
        time.sleep(6)   # let intake run
        dump_page(page, "po2_first_card")

        for step in range(10):
            time.sleep(3)   # allow think panels to finish
            btn_labels = page.evaluate(
                "() => Array.from(document.querySelectorAll('button'))"
                ".map(b => b.innerText.trim())"
            )
            print(f"  step {step}: buttons={[b for b in btn_labels if b][:8]}")
            # If pipeline reached the end, stop
            text = page.evaluate("() => document.body.innerText")
            if "Order fully processed" in text:
                print(f"  reached 'Order fully processed' at step {step}")
                break
            for want in ("Approve suggestion", "Confirm: 2 EA", "Use top match",
                         "✅ Approve"):
                if any(want in b for b in btn_labels):
                    if click_button_by_label(page, want):
                        print(f"    clicked '{want}'")
                        break
            else:
                print(f"    no CSR-actionable button (pipeline probably running)")
            time.sleep(3)
            dump_page(page, f"po2_after_click_{step:02d}")

        # Wait for pipeline to finish
        print("  waiting for pipeline to finish...")
        end = time.time() + 90
        while time.time() < end:
            time.sleep(3)
            text = page.evaluate("() => document.body.innerText")
            if "Order fully processed" in text:
                print("  PO-2 finished OK")
                break
        else:
            print("  [!] PO-2 did not reach 'Order fully processed'")

        dump_page(page, "po2_final")

        print(f"\n== JS errors captured: {len(errors)} ==")
        for e in errors[:10]:
            print(f"  {e[:200]}")

        browser.close()


if __name__ == "__main__":
    run()

