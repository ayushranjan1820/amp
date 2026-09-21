EXTRACT Prompts
E1 — Full Customer Snapshot


Extract all active bank customers with their primary savings account balance, 
credit score band (Poor <600, Fair 600-699, Good 700-749, Excellent 750+), 
and KYC status. Output as a flat CSV for the CRM team.
E2 — High-Value Transaction Feed


Extract all transactions above ₹50,000 from the last 90 days across all 
channels. Include customer name, account number, merchant category, 
transaction type, and city. Flag any single-day total exceeding ₹200,000 
per customer as 'high_activity'.
E3 — NPA Loan Pipeline


Extract all loans with status = 'npa' or outstanding_amount > principal_amount. 
Include customer PAN, loan number, loan type, original principal, outstanding 
balance, and days since disbursement. Sort by outstanding descending.
E4 — Dormant Account Detection


Extract all accounts with status = 'dormant' OR accounts with no transactions 
in the past 180 days. Include last transaction date, account type, and balance. 
Needed for RBI dormant account compliance report.
E5 — Credit Card Utilisation Extract


Extract all active credit cards where utilisation > 80% 
(outstanding_balance / credit_limit). Include card variant, billing cycle day, 
minimum due, and customer segment. Feed into risk scoring model.
E6 — Multi-Product Customer Extract


Extract customers who hold all three products: a bank account + a credit card + 
an active loan. Include their segment, annual income, and total relationship 
value (sum of account balance + credit limit + loan principal).
TRANSFORM Prompts
T1 — Credit Score Banding


Transform the credit_score column into a 5-tier risk band:
  300–549  → 'Very Poor'
  550–649  → 'Poor'
  650–699  → 'Fair'
  700–749  → 'Good'
  750–900  → 'Excellent'
Add a derived column risk_tier. Also compute a percentile rank of each 
customer's credit score within their customer_segment.
T2 — Transaction Category Rollup


Transform raw transactions into a monthly spend summary per customer.
Pivot merchant_category into columns: Food, Travel, Utilities, Shopping, 
Healthcare, Fuel, Other. Compute MoM change % for total spend.
T3 — EMI Burden Ratio


For every customer with an active loan, compute:
  emi_burden_ratio = (total monthly EMI across all loans) / (annual_income / 12)
Classify:
  < 30%  → 'Healthy'
  30–50% → 'Moderate'
  > 50%  → 'Stressed'
Join back to customer segment for segmented reporting.
T4 — Inactivity Score


Compute an inactivity score (0–100) per account using:
  - Days since last transaction (weight 40%)
  - Number of transactions in last 6 months (weight 30%)
  - Account balance vs minimum balance ratio (weight 30%)
Higher score = more inactive. Flag accounts scoring > 70 for re-engagement.
T5 — Beneficiary Trust Score


Transform beneficiary records: compute a 'trust_score' per beneficiary entry:
  +30 if is_verified = true
  +20 if relationship in ('spouse','parent','child')
  +20 if upi_id is not null
  +30 based on number of successful transfers to this beneficiary
Output a ranked list per customer ordered by trust_score descending.
T6 — Card Reward Normalisation


Normalise reward_points across card variants:
  Classic   → 1 point = ₹0.25
  Gold      → 1 point = ₹0.35
  Platinum  → 1 point = ₹0.50
  Signature → 1 point = ₹0.75
  Infinite  → 1 point = ₹1.00
Transform reward_points into rupee_equivalent. Flag customers where 
rupee_equivalent > ₹5,000 as eligible for reward redemption campaign.
T7 — Duplicate PAN Deduplication


Identify customers sharing the same pan_number (should be unique but 
data quality may have gaps). For duplicates, keep the record with the 
latest created_at and highest credit_score. Mark others as 
dedup_status = 'duplicate'. Output a reconciliation report.
T8 — State-level Income Normalisation


Transform annual_income into a normalised income index per state:
  index = customer_income / avg_state_income
Flag customers with index > 2.0 as 'high earner' and < 0.5 as 
'low earner' within their state. Use for branch-level product targeting.
T9 — Loan-to-Value Ratio


For secured loans (home, vehicle, gold), compute:
  LTV = outstanding_amount / collateral_value * 100
Classify:
  LTV < 60%  → 'Low Risk'
  60–80%     → 'Moderate'
  > 80%      → 'High Risk'
Alert on any home loan with LTV > 90% for provisioning.
T10 — Balance Transfer Enrichment


Enrich balance_transfer records by joining sender/receiver customer names, 
cities, and segments. Add a 'transfer_pattern' flag:
  'intra_city'   — same city, both parties
  'intra_state'  — same state, different city
  'inter_state'  — different states
Used for fraud pattern analysis.
LOAD Prompts
L1 — Customer 360 Data Mart


Build a customer_360 summary table. Load one row per customer with:
total_accounts, total_balance, active_loans, total_loan_outstanding,
credit_cards_count, total_credit_limit, avg_monthly_spend (last 3 months),
credit_score, segment, kyc_status, last_login_date.
Refresh daily via incremental load on updated_at.
L2 — Daily Transaction Fact Table


Load a daily_transactions_fact table partitioned by month (initiated_at).
Include pre-joined customer_segment, account_type, city, state columns 
to avoid runtime joins in the BI layer. Upsert by transaction_ref.
L3 — Risk Dashboard Aggregate Load


Load a risk_metrics table used by the Risk team dashboard:
  - Total NPA amount by loan_type and state
  - Count of credit cards with utilisation > 80% by segment
  - Customers with EMI burden > 50% by city
  - Dormant accounts count by branch_code
Refresh every 4 hours.
L4 — Regulatory Reporting Load (CTR)


Load a ctr_report table for RBI Cash Transaction Report compliance.
Capture all transactions of type 'atm_withdrawal' or 'debit' above ₹10 lakh 
in a single day per customer. Include customer PAN, Aadhaar (masked), 
account number, branch IFSC, and transaction timestamp. 
Load daily at 11 PM for next-day submission.
L5 — Product Cross-Sell Propensity Load


Load a cross_sell_propensity table for the marketing team.
For each customer without a credit card: score them using credit_score, 
annual_income, and avg_monthly_spend. 
For each customer without a loan: score using account_balance and income.
Load weekly; output top 5,000 leads per product ranked by propensity score.
L6 — Segment Migration Audit Load


Load a segment_change_log table each time a customer's segment changes.
Capture: old_segment, new_segment, trigger_reason (balance_increase, 
credit_score_change, product_addition), effective_date.
Feed into customer lifecycle management system.
PIPELINE / ORCHESTRATION Prompts
P1 — Incremental Daily Pipeline


Design an incremental ETL pipeline that runs daily at 2 AM:
  1. Extract: Pull all rows from transactions, loans, credit_cards, 
     bank_accounts where updated_at > last_run_watermark
  2. Transform: Apply T1 (credit banding), T3 (EMI burden), T6 (reward normalisation)
  3. Load: Upsert into customer_360 mart, refresh risk_metrics
  4. Log: Write row counts and duration to etl_run_log table
Handle schema drift on merchant_category values and failed transaction retries.
P2 — KYC Compliance Batch


Build a weekly KYC compliance batch:
  Extract customers where kyc_status = 'pending' for more than 30 days.
  Transform: enrich with PAN validation flag, Aadhaar digit checksum.
  Load: push to kyc_escalation queue table with priority score
  (priority = days_pending + credit_score/100).
  Alert the compliance team if queue > 500 records.
P3 — Fraud Detection Feed


Build a real-time (micro-batch every 15 min) ETL feed for fraud scoring:
  Extract: transactions in last 15 min with status = 'success'
  Transform:
    - Velocity check: > 5 transactions in 10 min from same account
    - Geo-anomaly: city differs from customer's registered city
    - Odd-hour: transactions between 1 AM – 4 AM
    - Round-amount: amounts that are exact multiples of ₹10,000
  Load: flagged transactions into fraud_alerts table with risk_score 0–100.
P4 — Monthly Statement Generation Pipeline


Build a monthly statement ETL:
  Extract: transactions per account for the calendar month
  Transform:
    - Group by merchant_category
    - Compute opening balance, closing balance, total credits, total debits
    - Calculate reward points earned this month (credit card holders)
    - Flag any bounced EMIs (status = 'failed' AND transaction_type = 'emi')
  Load: into monthly_statements table; trigger PDF generation job.
P5 — Data Quality Scorecard Pipeline


Run a weekly data quality ETL across all 8 banking tables:
  - Completeness: % of null values per column
  - Uniqueness: duplicate check on pan_number, account_number, card_number_masked
  - Validity: credit_score outside 300–900, negative balances, 
              expiry_date < issue_date on credit cards
  - Referential integrity: orphan transactions (no account_id or credit_card_id)
  Load results into dq_scorecard table with pass/fail per rule.
  Fail the pipeline if overall score < 95%.
P6 — CIBIL Bureau Sync Pipeline


Prepare a monthly data extract for CIBIL credit bureau submission:
  Extract: all customers with active loans or credit cards
  Transform:
    - Mask Aadhaar (show only last 4 digits)
    - Format PAN as per CIBIL spec (uppercase, no spaces)
    - Map internal loan_type to CIBIL account_type codes
    - Compute days_past_due from EMI schedule for each loan
    - Compute credit utilisation % per credit card
  Load: into cibil_submission_staging; validate row count matches expected
  before marking as 'ready_for_export'.
P7 — Segment Refresh Pipeline


Run a monthly segment re-classification ETL:
  Extract: all customers with their last 6 months of transactions, 
           current balances, loan outstanding, and credit score.
  Transform: re-compute segment using rules:
    wealth    → avg_balance > 25L OR total_relationship_value > 50L
    premium   → avg_balance > 5L OR annual_income > 15L
    nri       → nationality != 'Indian' OR account_type IN ('nri_nre','nri_nro')
    corporate → occupation IN ('Business Owner') AND annual_income > 25L
    retail    → all others
  Load: UPDATE bank_customers SET customer_segment = new_segment WHERE changed.
  Write changed rows to segment_change_log (see L6).
P8 — End-of-Day Reconciliation Pipeline


Build a daily EOD reconciliation ETL:
  Extract: sum of all successful transaction amounts by account for the day.
  Transform: 
    - Compare computed closing balance against bank_accounts.balance
    - Flag accounts where difference > ₹1 as 'reconciliation_break'
    - Separate credit-side and debit-side breaks
  Load: into eod_reconciliation table.
  Alert treasury team if total break amount > ₹10,000 across all accounts.
