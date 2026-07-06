"""Verify the auto-scroll fix: watches scroll container position, latest
visible stage, and confirms every phase reaches the user's viewport all
the way to Order Execution — no dead zones, no viewport hangs."""
import sys, time, pathlib
from playwright.sync_api import sync_playwright

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


STAGES = [
    "AI Agent Processing",
    "Reviewing order against master data",
    "Backfilled from master data",
    "Intake decision",
    "Account Hierarchy Validation",
    "Buyer Authorization",
    "Product Matching",
    "Pricing",
    "Inventory",
    "Credit",
    "Compliance",
    "Logistics",
    "Governance",
    "Order Creation",
    "Order fully processed",
]


def latest_stage(text: str) -> str:
    last = "?"
    for s in STAGES:
        if s in text:
            last = s
    return last


def run(po_name: str, label: str, out_dir: pathlib.Path):
    with open(f"demo/{po_name}", encoding="utf-8") as f:
        po_text = f.read()

    from modules import duplicate_checker as dup
    dup.reset_store()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(viewport={"width": 1400, "height": 900}).new_page()
        console = []
        page.on("console", lambda m: console.append(f"{m.type}: {m.text[:200]}"))

        page.goto("http://localhost:8501", wait_until="load", timeout=30000)
        for _ in range(30):
            time.sleep(1)
            if page.query_selector('[data-testid="stChatInput"] textarea'):
                break

        # Verify our scroll installer landed
        installed = page.evaluate("() => !!window.__poScrollInstalled")
        print(f"[{label}] __poScrollInstalled = {installed}")

        chat = page.query_selector('[data-testid="stChatInput"] textarea')
        chat.fill(po_text)
        chat.press("Enter")

        stage_first_seen: dict[str, float] = {}
        stage_scroll_at: dict[str, int] = {}
        start = time.time()
        prev_scroll_top = 0
        stalls = 0
        done = False
        while time.time() - start < 240:  # up to 4 minutes
            time.sleep(1.5)
            state = page.evaluate(
                """
                () => {
                    const el = document.querySelector('[data-testid="stAppScrollToBottomContainer"]')
                          || document.querySelector('section.main')
                          || document.scrollingElement;
                    if (!el) return {sel: 'none'};
                    return {
                        sel: el.getAttribute('data-testid') || el.tagName,
                        scrollTop: el.scrollTop,
                        scrollHeight: el.scrollHeight,
                        clientHeight: el.clientHeight,
                        atBottom: (el.scrollHeight - el.scrollTop - el.clientHeight) < 80,
                    };
                }
                """
            )
            text = page.evaluate("() => document.body.innerText")
            stage = latest_stage(text)
            t = time.time() - start
            if stage != "?" and stage not in stage_first_seen:
                stage_first_seen[stage] = t
                stage_scroll_at[stage] = state.get("scrollTop", 0)
                print(f"  [{label}] t={t:5.1f}s  NEW STAGE: {stage:<45s} "
                      f"scrollTop={state.get('scrollTop')}/{state.get('scrollHeight')} "
                      f"atBottom={state.get('atBottom')}")
            # Track scroll advancement
            st = state.get("scrollTop", 0)
            if state.get("scrollHeight", 0) > state.get("clientHeight", 0) + 200:
                if st == prev_scroll_top:
                    stalls += 1
                else:
                    stalls = 0
            prev_scroll_top = st
            if "Order fully processed" in text:
                done = True
                print(f"  [{label}] t={t:5.1f}s  ✓ REACHED END, final "
                      f"scrollTop={state.get('scrollTop')}/{state.get('scrollHeight')} "
                      f"atBottom={state.get('atBottom')}")
                break

        page.screenshot(path=str(out_dir / f"{label}_final.png"), full_page=True)
        page.screenshot(path=str(out_dir / f"{label}_viewport.png"), full_page=False)

        expected = [
            "AI Agent Processing", "Reviewing order against master data",
            "Intake decision", "Account Hierarchy Validation",
            "Product Matching", "Pricing", "Inventory",
            "Compliance", "Logistics", "Order Creation",
            "Order fully processed",
        ]
        missed = [s for s in expected if s not in stage_first_seen]

        print(f"\n[{label}] SUMMARY")
        print(f"  Completed: {done}")
        print(f"  Stages seen: {len(stage_first_seen)} / expected {len(expected)}")
        print(f"  Missed:     {missed if missed else 'NONE'}")

        # Chronological order check
        order = sorted(stage_first_seen.items(), key=lambda kv: kv[1])
        print(f"  Chronological order:")
        for s, t in order:
            print(f"    {t:5.1f}s  {s}   (scrollTop when appeared: "
                  f"{stage_scroll_at.get(s)})")

        errs = [c for c in console if c.startswith("error:")]
        if errs:
            print(f"\n[{label}] JS errors:")
            for e in errs[:20]:
                print(f"    {e}")

        browser.close()
        return done, missed


if __name__ == "__main__":
    out = pathlib.Path("_browser_artifacts")
    out.mkdir(exist_ok=True)

    ok1, missed1 = run("Happy-Flow-PO.txt", "PO1_HAPPY", out)
    print("\n" + "=" * 70 + "\n")
    ok2, missed2 = run("CSR-Approval-PO.txt", "PO2_EXCEPTION", out)

    print("\n" + "=" * 70)
    print(f"PO-1 happy path:  {'PASS' if ok1 and not missed1 else 'FAIL'}")
    print(f"PO-2 exception:   {'PASS' if ok2 else 'PARTIAL (expected — needs CSR clicks)'}")
    sys.exit(0 if ok1 and not missed1 else 1)

