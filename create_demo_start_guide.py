"""
create_demo_start_guide.py
Generates docs/Demo_Start_Guide.docx — a very simple, step-by-step guide for the
business team to start and run the demo today. Plain language, no jargon.

Run:  python create_demo_start_guide.py
"""
import os
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH

OUT_DIR = os.path.join(os.path.dirname(__file__), "docs")
os.makedirs(OUT_DIR, exist_ok=True)

NAVY = RGBColor(0x1F, 0x2A, 0x44)
BLUE = RGBColor(0x25, 0x63, 0xEB)
GREEN = RGBColor(0x1E, 0x7D, 0x44)
AMBER = RGBColor(0xB4, 0x53, 0x09)


def main():
    doc = Document()

    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    # Title
    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = t.add_run("PO Fulfilment AI Agent")
    run.bold = True
    run.font.size = Pt(22)
    run.font.color.rgb = NAVY

    s = doc.add_paragraph()
    s.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = s.add_run("Demo Start Guide — Simple Steps")
    run.bold = True
    run.font.size = Pt(14)
    run.font.color.rgb = BLUE

    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta.add_run("Prepared by: Sanjay Kumar Kesarvani    |    Date: 30 June 2026").font.size = Pt(10)

    doc.add_paragraph()

    def h(text, color=NAVY, size=14):
        p = doc.add_paragraph()
        run = p.add_run(text)
        run.bold = True
        run.font.size = Pt(size)
        run.font.color.rgb = color
        return p

    def step(num, text):
        p = doc.add_paragraph(style="List Number")
        p.add_run(text)
        return p

    def bullet(text):
        p = doc.add_paragraph(style="List Bullet")
        p.add_run(text)
        return p

    # ---- What this is ----
    h("What is this?")
    doc.add_paragraph(
        "This is a smart assistant that reads a Purchase Order (PO) and checks it from start to "
        "finish — just like an experienced order desk would. It pulls out the details, checks the "
        "customer, prices, budget, credit, stock and delivery, and finally creates the order. "
        "If something is wrong, it stops, explains the problem in plain words, and points it to "
        "the right team."
    )

    # ---- Before the demo ----
    h("Before the demo (one-time setup)")
    doc.add_paragraph(
        "Your engineer normally does this part. If you need to do it yourself, follow these steps "
        "on the demo laptop:"
    )
    step(1, "Open the Start menu, type 'cmd', and press Enter to open a black command window.")
    step(2, "Type this and press Enter:  cd C:\\projects\\po-fullfiment-poc")
    step(3, "Turn on the work area. Type:  venv\\Scripts\\activate   (you will see (venv) appear).")
    step(4, "Install the parts (first time only). Type:  python -m pip install -r requirements.txt")
    doc.add_paragraph(
        "That's it for setup. You only need to do this once on a new laptop.", style="Intense Quote"
    )

    # ---- Start the demo ----
    h("How to START the demo (do this today)", GREEN)
    step(1, "Open the command window (Start menu -> type 'cmd' -> Enter).")
    step(2, "Go to the project folder. Type:  cd C:\\projects\\po-fullfiment-poc")
    step(3, "Turn on the work area. Type:  venv\\Scripts\\activate")
    step(4, "Start the app. Type:  python -m streamlit run app.py")
    step(5, "Your web browser opens automatically and shows a chat screen. "
            "If it does not open, type this address in your browser:  http://localhost:8501")
    doc.add_paragraph(
        "You are ready. Leave the black command window open in the background — do not close it "
        "while you demo.", style="Intense Quote"
    )

    # ---- Two ways to send a PO ----
    h("Two ways to give a PO to the agent")
    p = doc.add_paragraph()
    p.add_run("A) Paste text:  ").bold = True
    p.add_run("Open a PO .txt file, select all the text, copy it, paste it into the chat box at "
              "the bottom of the screen, and press Enter.")
    p = doc.add_paragraph()
    p.add_run("B) Upload Excel:  ").bold = True
    p.add_run("Click the + (plus) button near the chat box, then choose a PO Excel (.xlsx) file. "
              "Only Excel files are accepted.")

    # ---- What you will see ----
    h("What you will see on screen")
    bullet("The agent shows each step as it works, one after another.")
    bullet("GREEN / a tick means the step is fine and it moves on.")
    bullet("An AMBER / RED box means it found a problem. It explains the problem in simple words "
           "and says who should handle it. This is the correct behaviour for the 'problem' demos.")
    bullet("For approvals or pricing problems, it shows a sample email being sent to the right "
           "manager. No real email is sent — it is only for show.")
    bullet("When everything passes, it creates the order and shows confirmation messages.")

    # ---- Suggested running order ----
    h("Suggested demo flow (a good story to tell)", BLUE)
    doc.add_paragraph("Run these in order for the smoothest demo:")
    flow = [
        ("1. The happy path", "sample-data/US-01/sample-po-comprehensive.txt",
         "Show a complete PO sailing through all 12 checks and creating an order."),
        ("2. Missing information", "sample-data/US-01/sample-po-missing-fields.xlsx",
         "Show the agent catching missing fields and asking for them."),
        ("3. Wrong ship-to", "sample-data/US-02/scenario-invalid-shipto.txt",
         "Show the agent confirming the delivery address belongs to the customer."),
        ("4. Pricing build-up", "sample-data/US-06/happy-path.txt",
         "Show the price waterfall — how the final price is built step by step."),
        ("5. Needs approval", "sample-data/US-07/scenario-approval-required.txt",
         "Show the agent routing a big order to a manager (sample email)."),
        ("6. Credit hold", "sample-data/US-08/scenario-credit-hold.txt",
         "Show the agent stopping an order that is over the credit limit."),
        ("7. Out of stock", "sample-data/US-09/scenario-inventory-shortage.txt",
         "Show the agent spotting not enough stock."),
        ("8. Order created", "sample-data/US-12/happy-path.txt",
         "Finish by showing the order being created in the downstream systems."),
    ]
    for title, fpath, why in flow:
        p = doc.add_paragraph()
        p.add_run(title + "  ").bold = True
        p.add_run("(" + fpath + ")").italic = True
        b = doc.add_paragraph(style="List Bullet")
        b.add_run(why)

    doc.add_paragraph(
        "For the full list of every test and its expected result, see the Excel file "
        "'Unit_Test_Plan_US01-US12.xlsx' in the docs folder.", style="Intense Quote"
    )

    # ---- If something goes wrong ----
    h("If something goes wrong", AMBER)
    bullet("The screen looks stuck or shows an error: refresh the browser page (press F5).")
    bullet("The browser tab closed: open it again at  http://localhost:8501")
    bullet("The app stopped completely: go back to the black command window and run "
           "'python -m streamlit run app.py' again.")
    bullet("An upload is rejected: make sure the file is a .xlsx Excel file (not PDF or Word).")

    # ---- How to stop ----
    h("How to STOP the demo")
    step(1, "Close the browser tab.")
    step(2, "Go to the black command window and press the Ctrl key and C together to stop the app.")

    out = os.path.join(OUT_DIR, "Demo_Start_Guide.docx")
    doc.save(out)
    print("Created:", out)


if __name__ == "__main__":
    main()
