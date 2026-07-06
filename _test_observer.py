"""Decisive auto-scroll test: during the pipeline animation, forcibly scroll
the container to the TOP. Streamlit's native scroll-to-bottom will NOT fight
a manual scroll-up, so if the view returns to the bottom it proves OUR
MutationObserver (mounted in-flow) is doing the work."""
import sys, time, pathlib
from playwright.sync_api import sync_playwright

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


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
        time.sleep(8)  # let pipeline get going

        results = []
        # Repeatedly yank to top, wait, then measure whether observer pulled
        # it back near the bottom.
        for i in range(15):
            page.evaluate("""
                () => {
                    const el = document.querySelector('[data-testid="stAppScrollToBottomContainer"]')
                          || document.scrollingElement;
                    if (el) el.scrollTop = 0;   // yank to TOP
                }
            """)
            time.sleep(1.2)  # give observer time to react to next delta
            state = page.evaluate("""
                () => {
                    const el = document.querySelector('[data-testid="stAppScrollToBottomContainer"]')
                          || document.scrollingElement;
                    if (!el) return {};
                    const gap = el.scrollHeight - el.scrollTop - el.clientHeight;
                    return {scrollTop: el.scrollTop, scrollHeight: el.scrollHeight,
                            gap: gap, pulledBack: el.scrollTop > 200,
                            hasObs: !!(window.__poObs)};
                }
            """)
            text = page.evaluate("() => document.body.innerText")
            done = "Order fully processed" in text
            results.append(state.get("pulledBack"))
            print(f"  yank #{i:2d}: after top-reset scrollTop={state.get('scrollTop'):>6} "
                  f"gap_from_bottom={state.get('gap')} pulledBack={state.get('pulledBack')} "
                  f"hasObs={state.get('hasObs')}  done={done}")
            if done:
                break

        page.screenshot(path="_browser_artifacts/observer_test.png", full_page=False)
        browser.close()

        pulls = [r for r in results if r]
        print(f"\nObserver pulled view back to bottom on {len(pulls)}/{len(results)} yanks.")
        ok = len(pulls) >= max(3, len(results) // 2)
        print("RESULT:", "PASS — observer is actively scrolling" if ok
              else "FAIL — observer NOT scrolling reliably")
        return ok


if __name__ == "__main__":
    sys.exit(0 if run() else 1)

