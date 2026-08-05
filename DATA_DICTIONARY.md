# SpendIQ — Data Dictionary

Reference date anchor: **2026-04-21**. All dates are ISO-8601 (`YYYY-MM-DD`).

## 1. Entity-Relationship Sketch

```
  departments ---------------+
                             |
                             v
             purchase_orders <----- contracts ----- vendors
                    |                                 ^
                    |                                 |
                    v                                 |
                invoices ----------------------------+
```

Relationships:

- `purchase_orders.vendor_id` → `vendors.vendor_id`
- `purchase_orders.contract_id` → `contracts.contract_id` *(nullable — some POs intentionally have no contract)*
- `purchase_orders.department_id` → `departments.department_id`
- `contracts.vendor_id` → `vendors.vendor_id`
- `invoices.vendor_id` → `vendors.vendor_id`
- `invoices.po_id` → `purchase_orders.po_id` *(nullable — some invoices are non-PO-based, see expense policy)*

## 2. `departments.csv`

| Field              | Type     | Notes |
| ------------------ | -------- | ----- |
| department_id      | TEXT PK  | Format `DEPT-###` |
| name               | TEXT     | Human-readable department name |
| cost_center_code   | TEXT     | Format `CC-#####` |
| vp_name            | TEXT     | Person accountable for department spend |

**Rows:** 20.

## 3. `vendors.csv`

| Field                     | Type    | Notes |
| ------------------------- | ------- | ----- |
| vendor_id                 | TEXT PK | Format `VEND-#####` |
| vendor_name               | TEXT    | |
| tax_id                    | TEXT    | Format `TX-########` (synthetic) |
| country                   | TEXT    | Vendor's billing country |
| category                  | TEXT    | One of: SaaS, IT Hardware, Cloud Infrastructure, Marketing Services, Logistics, Professional Services, Office Supplies, Facilities, Legal, Travel, Telecom, Staffing |
| onboarded_date            | DATE    | |
| preferred_status          | BOOL    | `True` if on the Preferred Vendor list |
| risk_rating               | TEXT    | `Low` / `Medium` / `High` (see vendor risk policy) |
| payment_terms_default     | INT     | Default net-days if no contract-specified terms |
| status                    | TEXT    | `Active` / `Suspended` / `Inactive` |

**Rows:** 200.

## 4. `contracts.csv`

| Field                   | Type     | Notes |
| ----------------------- | -------- | ----- |
| contract_id             | TEXT PK  | Format `CTR-####` |
| vendor_id               | TEXT FK  | → `vendors.vendor_id` |
| contract_name           | TEXT     | |
| contract_type           | TEXT     | `MSA` / `SOW` / `Subscription` / `Retainer` / `Blanket PO` |
| start_date              | DATE     | |
| end_date                | DATE     | |
| auto_renew              | BOOL     | `True` if contract auto-renews |
| notice_period_days      | INT      | Days of written notice required to exit / non-renew |
| total_value_cap_usd     | NUMERIC  | Stated cap in USD; cumulative invoice spend should not exceed this |
| currency                | TEXT     | Invoice currency; most are USD |
| payment_terms_days      | INT      | Net-days stated in the contract. **When a contract specifies terms, they govern** over vendor defaults |
| status                  | TEXT     | `Active` / `Expired` / `Terminated` |
| document_path           | TEXT     | Relative path to contract doc (only populated for the 15 hand-authored contracts); empty otherwise |

**Rows:** 80. **~15 contracts have backing documents** in `docs/contracts/`.

## 5. `purchase_orders.csv`

| Field               | Type    | Notes |
| ------------------- | ------- | ----- |
| po_id               | TEXT PK | Format `PO-#####` |
| vendor_id           | TEXT FK | → `vendors.vendor_id` |
| contract_id         | TEXT FK | → `contracts.contract_id` (nullable; empty string when absent) |
| department_id       | TEXT FK | → `departments.department_id` |
| po_date             | DATE    | PO issue date |
| line_description    | TEXT    | Short description of goods/services |
| total_amount        | NUMERIC | PO total in the specified `currency` |
| currency            | TEXT    | |
| status              | TEXT    | `Open` / `Received` / `Closed` / `Cancelled` |
| requestor_name      | TEXT    | Person who raised the PO |
| approval_level      | TEXT    | `Dept Head` / `VP` / `CFO` / `CEO` (derived per policy thresholds) |

**Rows:** ~1,970.

## 6. `invoices.csv`

| Field               | Type    | Notes |
| ------------------- | ------- | ----- |
| invoice_id          | TEXT PK | Format `INV-######` |
| po_id               | TEXT FK | → `purchase_orders.po_id` (nullable; empty string when non-PO-based) |
| vendor_id           | TEXT FK | → `vendors.vendor_id` |
| invoice_date        | DATE    | |
| due_date            | DATE    | Computed as `invoice_date + payment_terms_days` |
| amount              | NUMERIC | |
| currency            | TEXT    | |
| status              | TEXT    | `Paid` / `Pending` / `Overdue` / `Disputed` |
| payment_terms_days  | INT     | Billed terms on this specific invoice. **May differ from the underlying contract — that is sometimes an anomaly worth surfacing.** |
| paid_date           | DATE    | Populated for `Paid` invoices only; empty otherwise |

**Rows:** ~1,600.

## 7. Modeling Notes

- The CSVs are intentionally light on referential integrity. A handful of deliberate inconsistencies exist (e.g., invoices whose `payment_terms_days` disagree with the contract's terms, or purchase orders without a contract above the USD 10,000 threshold). These are **expected** and are part of what a well-designed agent should be able to surface.
- Currency is mostly USD. A small minority of contracts and POs are denominated in EUR or GBP — consider whether and how to normalize when aggregating "total spend".
- The `contracts.document_path` field is only populated for the 15 contracts with backing documents, and those paths are relative to `docs/`. For the remaining 65 contracts, the CSV row is the only source of truth.
- Not every contract doc is in Markdown — three are PDFs (see `docs/contracts/*.pdf`). Your ingestion should handle both.
