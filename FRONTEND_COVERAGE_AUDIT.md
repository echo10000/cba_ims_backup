# CBA IMS — Frontend Coverage Audit

**Updated:** October 28, 2026  
**Working branch:** `feat/cba-frontend-storefront-staff-polish` (private Draft PR #1, unmerged).  
**Source baseline:** `develop` at `1894d69d36c59601282d7caf54b79543af33c177` when the branch was created.

## Counting rules

This audit covers 99 top-level Django HTML templates in twelve feature directories. It is a **source-file inventory**, not a count of URLs, production-ready designs, or individual user roles. It excludes shared root templates, error pages, and reusable partials. Some files are print layouts or alias templates.

A ✓ indicates a file has presentation changes on this GitHub-only feature branch. It **does not mean** its design has been rendered, tested in a browser, approved by stakeholders, or regression-tested.

## Summary

- **91 of 99 standalone templates** have a presentation patch in this draft branch.
- **All 5 standalone public Student journey pages** have storefront-style improvements. The shared Student shell also now has refined navigation and a keyboard "Skip to main content" link.
- Staff login, dashboards, inventory and QR utilities, all borrowing/maintenance/supplies/transfers workflows, organizational directories, user administration, disposals, and on-screen reports have scoped visual updates.
- A public tracking status-card partial also has presentation changes. Counting this partial and the 7 scoped CSS files, the feature branch diff contains additional non-top-level files; they are not part of the 91/99 count.
- **No Phase 4E2 Custodian template has been edited**, protecting separate local guard inspection and School ID collection work.
- **No print-specific layout has been edited**, to protect barcode/QR sizing, official letterhead formatting, and page margins.

## Coverage by module

| Directory | Top-level templates | Patched in draft | Unchanged |
| --- | ---: | ---: | ---: |
| accounts | 6 | 5 | 1 |
| assignments | 6 | 5 | 1 |
| audit | 1 | 1 | 0 |
| borrowing | 9 | 9 | 0 |
| disposals | 8 | 7 | 1 |
| inventory | 15 | 13 | 2 |
| maintenance | 10 | 10 | 0 |
| organizations | 7 | 7 | 0 |
| reports | 17 | 16 | 1 |
| student_reservations | 8 | 6 | 2 |
| supplies | 8 | 8 | 0 |
| transfers | 4 | 4 | 0 |
| **Total** | **99** | **91** | **8** |

## Exactly eight unchanged templates

- `templates/accounts/landing.html`
- `templates/assignments/printable_accountability.html`
- `templates/disposals/disposal_print.html`
- `templates/inventory/asset_qr_label.html`
- `templates/inventory/bulk_qr_labels_print.html`
- `templates/reports/report_print.html`
- `templates/student_reservations/custodian_detail.html`
- `templates/student_reservations/custodian_list.html`

The `accounts/landing.html` file is an include-only alias of the Student landing template. It remains unchanged but inherits the already patched Student landing presentation. The five dedicated print templates are deliberately not styled by the new screen-only CSS. The two Custodian templates must wait until separately tested Phase 4E2 changes are safely integrated into `develop`.

## Source checklist

**✓** = presentation patch present on draft branch. **○** = no change in this branch. Neither marking is a runtime or visual test result.


### accounts (6)

✓ `templates/accounts/dashboard.html`; ○ `templates/accounts/landing.html`; ✓ `templates/accounts/login.html`; ✓ `templates/accounts/password_change.html`; ✓ `templates/accounts/user_form.html`; ✓ `templates/accounts/user_list.html`

### assignments (6)

✓ `templates/assignments/assignment_confirm_return.html`; ✓ `templates/assignments/assignment_form.html`; ✓ `templates/assignments/assignment_history_list.html`; ✓ `templates/assignments/current_assignment_list.html`; ✓ `templates/assignments/my_accountability.html`; ○ `templates/assignments/printable_accountability.html`

### audit (1)

✓ `templates/audit/audit_log_list.html`

### borrowing (9)

✓ `templates/borrowing/borrowing_active_list.html`; ✓ `templates/borrowing/borrowing_detail.html`; ✓ `templates/borrowing/borrowing_form.html`; ✓ `templates/borrowing/borrowing_history_list.html`; ✓ `templates/borrowing/borrowing_list.html`; ✓ `templates/borrowing/borrowing_reject_form.html`; ✓ `templates/borrowing/borrowing_release_form.html`; ✓ `templates/borrowing/borrowing_return_form.html`; ✓ `templates/borrowing/my_borrowings.html`

### disposals (8)

✓ `templates/disposals/disposal_approve_form.html`; ✓ `templates/disposals/disposal_cancel_form.html`; ✓ `templates/disposals/disposal_complete_form.html`; ✓ `templates/disposals/disposal_detail.html`; ✓ `templates/disposals/disposal_list.html`; ○ `templates/disposals/disposal_print.html`; ✓ `templates/disposals/disposal_reject_form.html`; ✓ `templates/disposals/disposal_request_form.html`

### inventory (15)

✓ `templates/inventory/asset_confirm_delete.html`; ✓ `templates/inventory/asset_detail.html`; ✓ `templates/inventory/asset_form.html`; ✓ `templates/inventory/asset_list.html`; ○ `templates/inventory/asset_qr_label.html`; ✓ `templates/inventory/asset_verify_form.html`; ✓ `templates/inventory/brand_form.html`; ✓ `templates/inventory/brand_list.html`; ✓ `templates/inventory/bulk_qr_labels.html`; ○ `templates/inventory/bulk_qr_labels_print.html`; ✓ `templates/inventory/category_form.html`; ✓ `templates/inventory/category_list.html`; ✓ `templates/inventory/physical_verification_list.html`; ✓ `templates/inventory/qr_asset_lookup.html`; ✓ `templates/inventory/scan_asset.html`

### maintenance (10)

✓ `templates/maintenance/maintenance_assess_form.html`; ✓ `templates/maintenance/maintenance_cancel_form.html`; ✓ `templates/maintenance/maintenance_complete_form.html`; ✓ `templates/maintenance/maintenance_detail.html`; ✓ `templates/maintenance/maintenance_for_replacement_form.html`; ✓ `templates/maintenance/maintenance_history_list.html`; ✓ `templates/maintenance/maintenance_list.html`; ✓ `templates/maintenance/maintenance_report_form.html`; ✓ `templates/maintenance/maintenance_start_repair_form.html`; ✓ `templates/maintenance/my_maintenance_list.html`

### organizations (7)

✓ `templates/organizations/department_form.html`; ✓ `templates/organizations/department_list.html`; ✓ `templates/organizations/employee_detail.html`; ✓ `templates/organizations/employee_form.html`; ✓ `templates/organizations/employee_list.html`; ✓ `templates/organizations/location_form.html`; ✓ `templates/organizations/location_list.html`

### reports (17)

✓ `templates/reports/accountability_report.html`; ✓ `templates/reports/asset_by_department.html`; ✓ `templates/reports/asset_by_location.html`; ✓ `templates/reports/asset_inventory_report.html`; ✓ `templates/reports/audit_log_report.html`; ✓ `templates/reports/borrowing_report.html`; ✓ `templates/reports/disposal_report.html`; ✓ `templates/reports/employee_accountability_report.html`; ✓ `templates/reports/maintenance_cost_summary.html`; ✓ `templates/reports/maintenance_report.html`; ○ `templates/reports/report_print.html`; ✓ `templates/reports/reports_dashboard.html`; ✓ `templates/reports/supply_department_usage.html`; ✓ `templates/reports/supply_stock_report.html`; ✓ `templates/reports/supply_transactions_report.html`; ✓ `templates/reports/transfer_report.html`; ✓ `templates/reports/verification_report.html`

### student_reservations (8)

✓ `templates/student_reservations/base_student.html`; ✓ `templates/student_reservations/catalog.html`; ✓ `templates/student_reservations/confirmation.html`; ○ `templates/student_reservations/custodian_detail.html`; ○ `templates/student_reservations/custodian_list.html`; ✓ `templates/student_reservations/landing.html`; ✓ `templates/student_reservations/lookup.html`; ✓ `templates/student_reservations/reservation_form.html`

### supplies (8)

✓ `templates/supplies/low_stock_list.html`; ✓ `templates/supplies/stock_adjustment_form.html`; ✓ `templates/supplies/stock_in_form.html`; ✓ `templates/supplies/stock_out_form.html`; ✓ `templates/supplies/supply_detail.html`; ✓ `templates/supplies/supply_form.html`; ✓ `templates/supplies/supply_list.html`; ✓ `templates/supplies/transaction_list.html`

### transfers (4)

✓ `templates/transfers/pending_transfer_list.html`; ✓ `templates/transfers/transfer_detail.html`; ✓ `templates/transfers/transfer_form.html`; ✓ `templates/transfers/transfer_history_list.html`

## Verification and release gates

**Checks performed in the GitHub implementation session:**
- Confirmed the private feature branch base and that `develop` had not moved during this work.
- Created scoped CSS and checked brace balance.
- Checked Django `if`, `for`, and `block` open/close counts while editing templates.
- Preserved counts of form controls, CSRF markers, existing HTMX/Alpine triggers, camera JavaScript, authorization conditions, and report export links where modified.
- Confirmed the feature branch diff is restricted to templates, CSS, and this audit document.
- Verified no Phase 4E2 Custodian template or dedicated print template was changed.

**NOT performed, and REQUIRED before merging:**
1. Integrate verified Phase 4E2 work into private `develop`, without overwriting the original Windows worktree.
2. Reconcile/rebase this frontend branch, reviewing the diff for conflicts and accessibility regressions.
3. Run `python manage.py check`, `python manage.py makemigrations --check --dry-run`, focused tests, and complete Django regression tests using isolated Django test databases.
4. Run role-aware browser tests with a verified disposable SQLite clone outside the repo, at 390px / 768px / 1440px. Test no-login Student availability/reservation/tracking, the mobile nav, Staff login, operational forms, QR camera/manual fallback, filters, exports, keyboard focus, and status/warning indicators.
5. Review real screenshots and print outputs, fix all material defects, and confirm three protected persistent database hashes have not changed.

**The draft frontend PR must NOT be merged or deployed until these checks succeed.** No Python services, views, models, migrations, permission logic, production integrations, persistent SQLite databases, or public GitHub repos are intentionally modified by this branch.
