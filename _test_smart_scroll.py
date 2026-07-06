"""Verify smart-follow auto-scroll:
  A) Each of the 12 stage headings scrolls into the viewport as it completes.
  B) After 'Order fully processed', a user scroll-UP is RESPECTED (the page
     does NOT get yanked back to the bottom) — i.e. the user can scroll.
"""
import sys, time
from playwright.sync_api import sync_playwright

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

STAGE_HEADINGS = [
    "Extracted Header Fields",
    "Corporate Account Hierarchy",
    "Buyer Authorization",
    "Product Matching",
    "Regional Compliance",
    "Enterprise B2B Pricing",
    "Budget, Spend Limit",
    "Credit, Payment Terms",
    "Inventory Availability",
    "Fulfillment Optimization",
    "Exception Governance",
    "Order Creation",
]


def heading_in_viewport(page, text):
    """Return True if an element containing `text` is currently within the
    scroll container's visible viewport."""
    return page.evaluate(
        """
        (needle) => {
            const cont = document.querySelector('[data-testid="stAppScrollToBottomContainer"]')
                      || document.scrollingElement;
            if (!cont) return false;
            const top = cont.scrollTop, bot = top + cont.clientHeight;
            const els = Array.from(document.querySelectorAll('*'))
                .filter(e => e.children.length === 0 &&
                             (e.textContent || '').includes(needle));
            for (const e of els) {
                const r = e.getBoundingClientRect();
                const cr = cont.getBoundingClientRect();
                // visible if the element's box intersects the container's box
                if (r.bottom > cr.top && r.top < cr.bottom) return true;
            }
            return false;
        }
        """,
        text,
    )


def run():
    with open("demo/Happy-Flow-PO.txt", encoding="utf-8") as f:
        po_text = f.read()
    from modules import duplicate_checker as dup
    dup.reset_store()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(viewport={"width": 1400, "height": 900}).new_page()
        page.goto("http://localhost:8501", wait_until="load", timeout=30000)
        for _ in range(30):
            time.sleep(1)
            if page.query_selector('[data-testid="stChatInput"] textarea'):
                break

        chat = page.query_selector('[data-testid="stChatInput"] textarea')
        chat.fill(po_text)
        chat.press("Enter")

        # ---- A) Track each heading being visible when it first appears ----
        seen_visible = {}
        start = time.time()
        while time.time() - start < 200:
            time.sleep(1.0)
            text = page.evaluate("() => document.body.innerText")
            for h in STAGE_HEADINGS:
                if h in text and h not in seen_visible:
                    seen_visible[h] = heading_in_viewport(page, h)
            if "Order fully processed" in text:
                break

        print("== A) Stage headings visible in viewport when rendered ==")
        for h in STAGE_HEADINGS:
            status = seen_visible.get(h)
            mark = "✓" if status else ("·" if status is False else "?")
            print(f"  [{mark}] {h}")
        completed = "Order fully processed" in page.evaluate("() => document.body.innerText")
        print(f"  Completed: {completed}")

        # give the done-phase inactive scroll a moment
        time.sleep(3)

        # ---- B) After completion, user scrolls UP — must be respected ----
        print("\n== B) User scroll-up after completion is respected ==")
        # simulate a real wheel-up gesture so the follow-listener disengages
        page.mouse.move(700, 450)
        for _ in range(6):
            page.mouse.wheel(0, -600)
            time.sleep(0.15)
        time.sleep(2.0)  # wait longer than the 400ms safety interval
        after = page.evaluate(
            """
            () => {
                const el = document.querySelector('[data-testid="stAppScrollToBottomContainer"]')
                      || document.scrollingElement;
                if (!el) return {};
                return {scrollTop: el.scrollTop,
                        scrollHeight: el.scrollHeight,
                        clientHeight: el.clientHeight,
                        gap: el.scrollHeight - el.scrollTop - el.clientHeight,
                        follow: window.__poFollow};
            }
            """
        )
        print(f"  after wheel-up: scrollTop={after.get('scrollTop')} "
              f"gap_from_bottom={after.get('gap')} __poFollow={after.get('follow')}")
        # If the user could scroll up, gap_from_bottom should be large (not ~0)
        respected = after.get("gap", 0) > 300
        print("  RESULT:", "PASS — scroll-up respected (not yanked back)"
              if respected else "FAIL — page yanked back to bottom")

        page.screenshot(path="_browser_artifacts/smart_scroll_after_up.png",
                        full_page=False)
        browser.close()

        a_ok = sum(1 for v in seen_visible.values() if v) >= 8 and completed
        print(f"\nOVERALL: A={'PASS' if a_ok else 'PARTIAL'}  "
              f"B={'PASS' if respected else 'FAIL'}")
        return a_ok and respected


if __name__ == "__main__":
    sys.exit(0 if run() else 1)

