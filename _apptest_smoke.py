"""Bounded UI smoke test — prints phase after each step to locate any stall."""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from streamlit.testing.v1 import AppTest
from modules import duplicate_checker
duplicate_checker.reset_store()  # clean slate so demo POs aren't flagged as duplicates


def phase(at):
    try:
        o = at.session_state["orch"]
    except (KeyError, AttributeError):
        return None
    return o["phase"] if o else None


def step(at, note=""):
    try:
        at.run(timeout=20)
    except Exception as e:
        import traceback
        print(f"  !! at.run hung/raised at phase={phase(at)} note={note}: {type(e).__name__}: {e}")
        traceback.print_exc()
        sys.exit(2)
    if at.exception:
        print(f"  !! app exception at phase={phase(at)}: {at.exception}")
        sys.exit(3)


def demo(name):
    with open(f"demo/{name}", encoding="utf-8") as f:
        return f.read()


def run_po(fname, approve=False, max_steps=40):
    at = AppTest.from_file("app.py", default_timeout=90)
    at.run(timeout=90)                       # cold start
    at.chat_input[0].set_value(demo(fname))
    for i in range(max_steps):
        step(at, f"step{i}")
        p = phase(at)
        btns = [b.label for b in at.button]
        resolved = len(at.session_state["orch"].get("resolved_issues", []) or [])
        print(f"  step {i:02d}: phase={p} resolved_cards={resolved} buttons={btns}")
        if p == "done":
            print(f"  {fname}: DONE (final resolved_cards={resolved})"); return True
        if p == "terminal":
            print(f"  {fname}: TERMINAL"); return False
        if approve and at.button:
            # Match the first available "accept" button. Order matters:
            # UOM ambiguity uses "Confirm: X EA (individual pieces)" as the AI
            # default. Substitution / SKU / ship-to use "Approve suggestion" or
            # "Use top match". Fall through to any generic "Approve".
            for want in ("Confirm:", "Approve suggestion", "Use top match",
                         "Approve"):
                clicked = False
                for b in at.button:
                    if want.lower() in (b.label or "").lower():
                        b.click(); clicked = True; break
                if clicked:
                    break
    print(f"  {fname}: did not finish in {max_steps} steps (phase={phase(at)})")
    return False


def run_duplicate_scenario():
    """Submit PO-1 twice in the same session. The second submission MUST be
    auto-rejected as a duplicate, and the ONLY decision button must be
    Escalate (no Approve, no Reject)."""
    at = AppTest.from_file("app.py", default_timeout=90)
    at.run(timeout=90)                       # cold start
    at.chat_input[0].set_value(demo("Happy-Flow-PO.txt"))
    for i in range(40):
        step(at, f"dup1-step{i}")
        p = phase(at)
        if p == "done":
            print(f"  first submission: DONE"); break
    # Second submission of the same PO → duplicate
    at.chat_input[0].set_value(demo("Happy-Flow-PO.txt"))
    for i in range(10):
        step(at, f"dup2-step{i}")
        p = phase(at)
        btns = [b.label for b in at.button]
        print(f"  dup step {i:02d}: phase={p} buttons={btns}")
        if p == "intake_review":
            escalate_labels = [b for b in btns if "Escalate" in b]
            approve_labels  = [b for b in btns if "Approve" in b]
            reject_labels   = [b for b in btns if "Reject" in b]
            print(f"    escalate={len(escalate_labels)} approve={len(approve_labels)} reject={len(reject_labels)}")
            return (len(escalate_labels) == 1 and
                    len(approve_labels)  == 0 and
                    len(reject_labels)   == 0)
        if p in ("terminal", "done"):
            break
    return False


print("== PO-1 happy path ==")
ok1 = run_po("Happy-Flow-PO.txt", approve=False)
print("== PO-2 exceptions (auto-approve) ==")
ok2 = run_po("CSR-Approval-PO.txt", approve=True)
print("== Duplicate PO auto-reject (only Escalate button) ==")
ok3 = run_duplicate_scenario()
print(f"  duplicate scenario: {'PASS' if ok3 else 'FAIL'}")
print("\nRESULT:", "PASS" if (ok1 and ok2 and ok3) else "FAIL")
sys.exit(0 if (ok1 and ok2 and ok3) else 1)

