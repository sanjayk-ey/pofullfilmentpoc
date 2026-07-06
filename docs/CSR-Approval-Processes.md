# CSR Approval Processes

This document describes **only the CSR (Customer Service Representative) approval processes** in the PO Order-Fulfillment Orchestration accelerator.

The AI agent auto-resolves everything it can confidently determine from master data. Whenever a decision carries business risk, is ambiguous, or breaches policy, the agent **pauses the pipeline** and raises an interactive gate for a human CSR. Each gate presents:

- **Why approval is needed** — the exact condition the AI detected.
- **What the AI decided automatically** — the recommendation derived from master data.
- **CSR action** — the choices available to the CSR.
- **Routing** — who the item escalates to if the CSR does not approve.

Every CSR decision is written to the **CSR Decision Audit Trail** for traceability.

---

## Where CSR gates occur

CSR approval gates fire in two phases of the run:

1. **Intake resolution** (before the decision pipeline) — the agent reconciles the "soft" parts of the PO (products, quantities, units, ship-to, buyer) against master data.
2. **Decision pipeline** (per validation layer) — pricing, credit, inventory, and logistics each raise their own exception gate when policy is breached.

The reference demo (`demo/CSR-Approval-PO.txt`) is engineered to trigger **all 11 gates** in a single order.

---

## CSR action vocabulary

| Action | Meaning |
|---|---|
| **Approve** | Accept the AI's recommendation and continue. |
| **Pick** | Choose one option from the AI's ranked master-data matches (radio list). |
| **Enter / Correct** | Manually type the correct value (SKU, quantity, address) when no match is right. |
| **Reject** | Decline the line/order; it does not proceed. |
| **Escalate** | Route the item to the responsible team for a specialist decision. |

---

# Intake-phase CSR gates

## 1. Unresolved buyer (`UNRESOLVED_BUYER`)
- **Why approval is needed:** The buyer named on the PO could not be uniquely matched to an authorized buyer registered for this customer account.
- **AI auto-decision:** Ranks the buyers registered for the customer in the buyer master data and presents the closest matches for selection.
- **CSR action:** Pick a registered buyer / Enter the correct buyer / Escalate.
- **Routes to:** Sales Ops / Account Manager.

## 2. Obsolete product substitution (`SUBSTITUTE_SKU`)
- **Why approval is needed:** The requested SKU is **obsolete/inactive** and cannot be ordered as-is.
- **AI auto-decision:** Looks up the approved substitute in the substitution rules and presents compatibility, price impact, and availability impact. Recommends the substitute SKU.
- **CSR action:** Approve the substitute / Enter a different SKU / Escalate. *(No "Reject" — an obsolete line must be resolved.)*
- **Routes to:** Product Specialist.

## 3. Unresolved SKU (`UNRESOLVED_SKU`)
- **Why approval is needed:** The customer's product code does not match any catalog SKU, and description matching was not confident enough to auto-accept.
- **AI auto-decision:** Matches the product description against the catalog and proposes the best candidate(s) with a confidence score.
- **CSR action:** Approve / Pick the correct match / Enter the SKU / Escalate.
- **Routes to:** Product Specialist.

## 4. Missing SKU (`MISSING_SKU`)
- **Why approval is needed:** The line has a description and quantity but **no product code at all**.
- **AI auto-decision:** Identifies the product from the description against master data and proposes the matching SKU(s).
- **CSR action:** Pick / Enter the SKU / Escalate.
- **Routes to:** Product Specialist.

## 5. Invalid quantity (`INVALID_QUANTITY`)
- **Why approval is needed:** The line quantity cannot be processed (e.g., zero, blank, or non-numeric).
- **AI auto-decision:** Flags the line and identifies the affected SKU/description; requires a valid quantity before it can proceed. The **"Use my entry"** action activates only after a valid quantity is entered.
- **CSR action:** Enter a valid quantity / Reject the line / Escalate.
- **Routes to:** Order Operations Supervisor.

## 6. Unit-of-measure conversion (`UOM_CONVERSION`)
- **Why approval is needed:** The line uses a **non-standard unit of measure** (e.g., CASE) that differs from the product's base UOM (e.g., EA).
- **AI auto-decision:** Finds the approved conversion factor in the UOM conversion rules, computes the converted base-unit quantity, and shows the original → converted quantities with the conversion logic applied.
- **CSR action:** Approve the conversion / Reject / Escalate.
- **Routes to:** Product Specialist.

## 7. Ship-to resolution (`PARTIAL_SHIP_TO`)
- **Why approval is needed:** The ship-to address on the PO is partial or ambiguous and matches more than one registered location.
- **AI auto-decision:** Ranks registered ship-to locations from the customer master data (with match percentages) and presents them for selection.
- **CSR action:** Approve / Pick the correct address / Enter a correction / Escalate.
- **Routes to:** Logistics / Account Manager.

---

# Pipeline-phase CSR gates

## 8. Pricing / margin exception (`PRICING_EXCEPTION`)
- **Why approval is needed:** The effective discount on a line exceeds the product family's discount policy (margin protection).
- **AI auto-decision:** Builds the full price waterfall (list price → contract price → volume tier → promotion → rebate → net price) from the pricing master data, computes the effective discount and the **margin impact in dollars**, and identifies the required approver role.
- **CSR action:** Approve the exception / Escalate.
- **Routes to:** Pricing Desk.
- **Demo example:** Requested discount **21.5%** on `SKU-SHS-7700` (Digital Shower Interface System) exceeds the `SHOWERSYS` policy limit of **10%**, margin impact ≈ **$1,668**.

## 9. Credit hold (`CREDIT_HOLD`)
- **Why approval is needed:** The order value exceeds the customer's available credit.
- **AI auto-decision:** Retrieves the credit limit, exposure, and available credit from the credit master data and computes the shortfall against the order total.
- **CSR action:** Approve override / Escalate.
- **Routes to:** Finance / Credit Team.
- **Demo example:** Order value **$38,868.66** exceeds available credit **$30,000.00**.

## 10. Inventory shortage (`INVENTORY_SHORTAGE`)
- **Why approval is needed:** Available-to-promise (ATP) stock is insufficient to fully fulfill a line.
- **AI auto-decision:** Checks ATP across warehouses, allocates what is available, and computes the backorder quantity per the backorder policy, proposing a split/backorder plan.
- **CSR action:** Approve the backorder/allocation plan / Escalate.
- **Routes to:** Fulfillment Planner.

## 11. ZIP not serviceable (`ZIP_NOT_SERVICEABLE`)
- **Why approval is needed:** The destination ZIP is not serviceable by the assigned carrier.
- **AI auto-decision:** Ranks warehouses by proximity to the destination and proposes the **nearest pickup location**, along with the carrier and estimated ETA.
- **CSR action:** Approve the nearest-pickup plan / Escalate.
- **Routes to:** Logistics Team.

---

## CSR Decision Audit Trail

Every gate above records a structured audit entry containing:

- **Why CSR approval was needed** — the triggering condition.
- **What the AI decided automatically from master data** — the auto-resolved findings and recommendation.
- **CSR action** — the decision the CSR made (Approved / Picked / Entered / Rejected / Escalated), with any entered value and the routing target when escalated.

This provides a complete, step-by-step record of both the automated decisions and the human interventions for each processed purchase order.
