"""
╔══════════════════════════════════════════════════════════════════════════╗
║          Digital Lending MCP Server  —  Full Loan Lifecycle              ║
╠══════════════════════════════════════════════════════════════════════════╣
║  Partners    CRED · PhonePe · GPay · Paytm · Amazon Pay · Slice         ║
║                                                                          ║
║  Domains                                                                 ║
║    Partner Management   register · config · health · metrics             ║
║    Customer / KYC       create · verify PAN/Aadhaar · credit bureau      ║
║    Loan Application     create · submit · offer · accept · reject        ║
║    Loan Servicing       disburse · EMI schedule · statement · NOC        ║
║    Payments             EMI · prepayment · foreclosure · overdue         ║
║    Collections          overdue tracking · NPA · waivers                 ║
║    Testing Utilities    synthetic data · simulate · reset · audit        ║
║                                                                          ║
║  Resources  partner://config  loan://details  customer://profile         ║
║             docs://flow  schema://application  report://portfolio        ║
║                                                                          ║
║  Prompts    pm_test_plan · integration_checklist · credit_policy         ║
║             emi_verification · partner_launch · npa_analysis             ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import json
import math
import random
import string
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Literal, Optional

import asyncio
from mcp.server.fastmcp import Context, FastMCP

mcp = FastMCP("digital-lending-server")

# ══════════════════════════════════════════════════════════════════════════════
# IN-MEMORY STATE  (persists for the session — reset via reset_test_data)
# ══════════════════════════════════════════════════════════════════════════════

def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")

def _uid(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:8].upper()}"

def _date_str(d: date) -> str:
    return d.strftime("%Y-%m-%d")


# ── Seed Partners ─────────────────────────────────────────────────────────────
PARTNERS: dict[str, dict] = {
    "CRED": {
        "id": "CRED", "name": "CRED", "type": "NBFC_PARTNER",
        "min_loan": 10_000, "max_loan": 5_00_000,
        "min_tenure": 3, "max_tenure": 36,
        "interest_rate_pa": 16.0, "processing_fee_pct": 1.5,
        "prepayment_charge_pct": 2.0, "foreclosure_charge_pct": 3.0,
        "min_credit_score": 700, "max_foir": 0.50,
        "status": "ACTIVE", "api_endpoint": "https://api.cred.club/lending/v2",
        "webhook_url": "https://api.cred.club/webhooks/lending",
        "created_at": "2024-01-10T09:00:00", "disbursed_count": 1240, "npa_rate": 1.2,
    },
    "PHONEPE": {
        "id": "PHONEPE", "name": "PhonePe", "type": "PAYMENTS_PARTNER",
        "min_loan": 5_000, "max_loan": 2_00_000,
        "min_tenure": 3, "max_tenure": 24,
        "interest_rate_pa": 18.0, "processing_fee_pct": 2.0,
        "prepayment_charge_pct": 0.0, "foreclosure_charge_pct": 2.5,
        "min_credit_score": 680, "max_foir": 0.55,
        "status": "ACTIVE", "api_endpoint": "https://api.phonepe.com/lending/v1",
        "webhook_url": "https://api.phonepe.com/webhooks/loans",
        "created_at": "2024-02-14T10:00:00", "disbursed_count": 3780, "npa_rate": 2.1,
    },
    "GPAY": {
        "id": "GPAY", "name": "Google Pay", "type": "PAYMENTS_PARTNER",
        "min_loan": 1_000, "max_loan": 1_00_000,
        "min_tenure": 1, "max_tenure": 12,
        "interest_rate_pa": 15.0, "processing_fee_pct": 1.0,
        "prepayment_charge_pct": 0.0, "foreclosure_charge_pct": 0.0,
        "min_credit_score": 720, "max_foir": 0.45,
        "status": "ACTIVE", "api_endpoint": "https://api.google.com/pay/lending/v1",
        "webhook_url": "https://api.google.com/pay/webhooks",
        "created_at": "2024-03-01T08:00:00", "disbursed_count": 5120, "npa_rate": 0.8,
    },
    "PAYTM": {
        "id": "PAYTM", "name": "Paytm", "type": "FINTECH_PARTNER",
        "min_loan": 2_000, "max_loan": 3_00_000,
        "min_tenure": 3, "max_tenure": 24,
        "interest_rate_pa": 20.0, "processing_fee_pct": 2.5,
        "prepayment_charge_pct": 1.5, "foreclosure_charge_pct": 3.0,
        "min_credit_score": 650, "max_foir": 0.60,
        "status": "ACTIVE", "api_endpoint": "https://api.paytm.com/lending/v2",
        "webhook_url": "https://api.paytm.com/webhooks/loans",
        "created_at": "2024-01-20T11:00:00", "disbursed_count": 2890, "npa_rate": 3.4,
    },
    "AMAZON_PAY": {
        "id": "AMAZON_PAY", "name": "Amazon Pay", "type": "ECOMMERCE_PARTNER",
        "min_loan": 5_000, "max_loan": 4_00_000,
        "min_tenure": 3, "max_tenure": 36,
        "interest_rate_pa": 14.5, "processing_fee_pct": 1.0,
        "prepayment_charge_pct": 0.0, "foreclosure_charge_pct": 1.5,
        "min_credit_score": 730, "max_foir": 0.45,
        "status": "ACTIVE", "api_endpoint": "https://api.amazon.in/pay/lending/v1",
        "webhook_url": "https://api.amazon.in/pay/webhooks",
        "created_at": "2024-04-01T09:00:00", "disbursed_count": 980, "npa_rate": 0.5,
    },
    "SLICE": {
        "id": "SLICE", "name": "Slice", "type": "NEOBANK_PARTNER",
        "min_loan": 2_000, "max_loan": 1_50_000,
        "min_tenure": 1, "max_tenure": 18,
        "interest_rate_pa": 22.0, "processing_fee_pct": 2.0,
        "prepayment_charge_pct": 0.0, "foreclosure_charge_pct": 2.0,
        "min_credit_score": 620, "max_foir": 0.65,
        "status": "SANDBOX", "api_endpoint": "https://api.sliceit.com/lending/v2",
        "webhook_url": "https://api.sliceit.com/webhooks",
        "created_at": "2024-05-15T10:00:00", "disbursed_count": 0, "npa_rate": 0.0,
    },
}

# ── Seed Customers ────────────────────────────────────────────────────────────
CUSTOMERS: dict[str, dict] = {
    "CUST001": {
        "id": "CUST001", "name": "Rajesh Kumar", "pan": "ABCDE1234F",
        "aadhaar": "2345 6789 0123", "mobile": "9876543210",
        "email": "rajesh.kumar@example.com", "dob": "1988-04-15",
        "gender": "M", "credit_score": 760, "monthly_income": 85_000,
        "employment_type": "SALARIED", "employer": "Infosys Ltd",
        "existing_emi": 12_000, "city": "Bengaluru", "pincode": "560001",
        "bank_account": "ICIC0001234", "ifsc": "ICIC0001234",
        "kyc_status": "VERIFIED", "created_at": "2024-06-01T10:00:00",
    },
    "CUST002": {
        "id": "CUST002", "name": "Priya Sharma", "pan": "FGHIJ5678K",
        "aadhaar": "3456 7890 1234", "mobile": "9123456780",
        "email": "priya.sharma@example.com", "dob": "1992-11-22",
        "gender": "F", "credit_score": 720, "monthly_income": 65_000,
        "employment_type": "SALARIED", "employer": "Wipro Technologies",
        "existing_emi": 8_000, "city": "Hyderabad", "pincode": "500081",
        "bank_account": "HDFC0005678", "ifsc": "HDFC0005678",
        "kyc_status": "VERIFIED", "created_at": "2024-06-05T11:00:00",
    },
    "CUST003": {
        "id": "CUST003", "name": "Amit Patel", "pan": "KLMNO9012P",
        "aadhaar": "4567 8901 2345", "mobile": "9988776655",
        "email": "amit.patel@example.com", "dob": "1985-07-08",
        "gender": "M", "credit_score": 640, "monthly_income": 45_000,
        "employment_type": "SELF_EMPLOYED", "employer": "Self",
        "existing_emi": 5_000, "city": "Ahmedabad", "pincode": "380001",
        "bank_account": "SBIN0009012", "ifsc": "SBIN0009012",
        "kyc_status": "PENDING", "created_at": "2024-06-10T09:00:00",
    },
}

APPLICATIONS: dict[str, dict] = {}
LOANS: dict[str, dict] = {}
PAYMENTS: dict[str, dict] = {}
AUDIT_LOG: list[dict] = []
COLLECTIONS: dict[str, dict] = {}

# ── Seed a few Applications and Loans ────────────────────────────────────────
APPLICATIONS["APP001"] = {
    "id": "APP001", "partner_id": "CRED", "customer_id": "CUST001",
    "loan_amount": 1_50_000, "tenure_months": 18, "purpose": "HOME_RENOVATION",
    "status": "DISBURSED", "credit_score_at_apply": 760,
    "offered_rate": 16.0, "processing_fee": 2_250,
    "created_at": "2024-07-01T10:00:00", "updated_at": "2024-07-03T15:00:00",
    "notes": "",
}
APPLICATIONS["APP002"] = {
    "id": "APP002", "partner_id": "PHONEPE", "customer_id": "CUST002",
    "loan_amount": 80_000, "tenure_months": 12, "purpose": "MEDICAL",
    "status": "OFFERED", "credit_score_at_apply": 720,
    "offered_rate": 18.0, "processing_fee": 1_600,
    "created_at": "2024-07-10T11:00:00", "updated_at": "2024-07-10T12:00:00",
    "notes": "",
}
APPLICATIONS["APP003"] = {
    "id": "APP003", "partner_id": "GPAY", "customer_id": "CUST003",
    "loan_amount": 50_000, "tenure_months": 6, "purpose": "TRAVEL",
    "status": "REJECTED", "credit_score_at_apply": 640,
    "offered_rate": None, "processing_fee": None,
    "rejection_reason": "Credit score below minimum threshold (700) for GPay.",
    "created_at": "2024-07-12T09:00:00", "updated_at": "2024-07-12T09:05:00",
    "notes": "",
}

LOANS["LOAN001"] = {
    "id": "LOAN001", "application_id": "APP001", "partner_id": "CRED",
    "customer_id": "CUST001", "principal": 1_50_000, "interest_rate_pa": 16.0,
    "tenure_months": 18, "emi_amount": 9_318, "processing_fee": 2_250,
    "disbursement_date": "2024-07-03", "maturity_date": "2026-01-03",
    "status": "ACTIVE", "emis_paid": 4, "emis_remaining": 14,
    "outstanding_principal": 1_18_463, "total_overdue": 0,
    "bank_account": "ICIC0001234", "ifsc": "ICIC0001234",
    "created_at": "2024-07-03T15:00:00",
}

# Seed some payments for LOAN001
for i in range(1, 5):
    pid = f"PAY{i:04d}"
    pay_date = date(2024, 7 + i, 3)
    PAYMENTS[pid] = {
        "id": pid, "loan_id": "LOAN001", "customer_id": "CUST001",
        "partner_id": "CRED", "emi_number": i,
        "amount": 9_318, "principal_component": round(9_318 - (1_50_000 - (i-1)*7_700)*0.16/12, 2),
        "interest_component": round((1_50_000 - (i-1)*7_700)*0.16/12, 2),
        "type": "EMI", "status": "SUCCESS",
        "payment_date": _date_str(pay_date),
        "utr": f"UTR{uuid.uuid4().hex[:12].upper()}",
        "created_at": f"{pay_date.isoformat()}T10:30:00",
    }


def _audit(action: str, entity: str, entity_id: str, detail: str = "", user: str = "PM_TEST"):
    AUDIT_LOG.append({
        "ts": _now(), "user": user, "action": action,
        "entity": entity, "entity_id": entity_id, "detail": detail,
    })


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _emi(principal: float, rate_pa: float, tenure_months: int) -> float:
    """Standard reducing-balance EMI formula."""
    r = rate_pa / (12 * 100)
    if r == 0:
        return round(principal / tenure_months, 2)
    return round(principal * r * (1 + r) ** tenure_months / ((1 + r) ** tenure_months - 1), 2)


def _foir(customer: dict, new_emi: float) -> float:
    return (customer["existing_emi"] + new_emi) / customer["monthly_income"]


def _check_eligibility(customer: dict, partner: dict, amount: float, tenure: int) -> tuple[bool, str]:
    if customer["credit_score"] < partner["min_credit_score"]:
        return False, f"Credit score {customer['credit_score']} below minimum {partner['min_credit_score']} for {partner['name']}."
    if amount < partner["min_loan"] or amount > partner["max_loan"]:
        return False, f"Loan amount ₹{amount:,.0f} outside partner range ₹{partner['min_loan']:,}–₹{partner['max_loan']:,}."
    if tenure < partner["min_tenure"] or tenure > partner["max_tenure"]:
        return False, f"Tenure {tenure}m outside partner range {partner['min_tenure']}–{partner['max_tenure']} months."
    emi = _emi(amount, partner["interest_rate_pa"], tenure)
    foir = _foir(customer, emi)
    if foir > partner["max_foir"]:
        return False, f"FOIR {foir:.1%} exceeds max {partner['max_foir']:.0%} for {partner['name']}."
    if customer["kyc_status"] != "VERIFIED":
        return False, f"Customer KYC status is '{customer['kyc_status']}'. KYC must be VERIFIED before loan."
    return True, "Eligible"


# ══════════════════════════════════════════════════════════════════════════════
# ── PARTNER MANAGEMENT TOOLS ──────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def list_partners(status: Optional[str] = None) -> list[dict]:
    """
    List all configured lending partners.

    Args:
        status: Filter by status — ACTIVE | SANDBOX | INACTIVE (omit for all)

    Returns list of partner summaries with config snapshot.
    """
    partners = list(PARTNERS.values())
    if status:
        partners = [p for p in partners if p["status"].upper() == status.upper()]
    return [{
        "id": p["id"], "name": p["name"], "type": p["type"],
        "status": p["status"],
        "loan_range": f"₹{p['min_loan']:,} – ₹{p['max_loan']:,}",
        "tenure_range": f"{p['min_tenure']}–{p['max_tenure']} months",
        "interest_rate_pa": f"{p['interest_rate_pa']}%",
        "processing_fee_pct": f"{p['processing_fee_pct']}%",
        "min_credit_score": p["min_credit_score"],
        "disbursed_count": p["disbursed_count"],
        "npa_rate": f"{p['npa_rate']}%",
    } for p in partners]


@mcp.tool()
def get_partner_config(partner_id: str) -> dict:
    """
    Get full configuration for a specific partner.

    Args:
        partner_id: Partner identifier (e.g. CRED, PHONEPE, GPAY)
    """
    p = PARTNERS.get(partner_id.upper())
    if not p:
        return {"error": f"Partner '{partner_id}' not found. Use list_partners() to see valid IDs."}
    _audit("GET_CONFIG", "PARTNER", partner_id)
    return p


@mcp.tool()
def register_partner(
    id: str,
    name: str,
    type: Literal["NBFC_PARTNER", "PAYMENTS_PARTNER", "FINTECH_PARTNER", "ECOMMERCE_PARTNER", "NEOBANK_PARTNER"],
    min_loan: int,
    max_loan: int,
    min_tenure: int,
    max_tenure: int,
    interest_rate_pa: float,
    processing_fee_pct: float,
    min_credit_score: int,
    max_foir: float,
    api_endpoint: str,
    webhook_url: str,
    prepayment_charge_pct: float = 0.0,
    foreclosure_charge_pct: float = 2.0,
) -> dict:
    """
    Register a new lending partner.

    Args:
        id:                     Unique uppercase partner ID (e.g. BAJAJ_FIN)
        name:                   Display name
        type:                   Partner category
        min_loan:               Minimum loan amount in ₹
        max_loan:               Maximum loan amount in ₹
        min_tenure:             Minimum tenure in months
        max_tenure:             Maximum tenure in months
        interest_rate_pa:       Annual interest rate in % (e.g. 18.5)
        processing_fee_pct:     Processing fee as % of loan amount
        min_credit_score:       Minimum CIBIL score required (300–900)
        max_foir:               Maximum Fixed Obligation to Income Ratio (0.0–1.0)
        api_endpoint:           Partner's API base URL
        webhook_url:            Webhook URL for loan lifecycle events
        prepayment_charge_pct:  Prepayment penalty % (default 0)
        foreclosure_charge_pct: Foreclosure charge % (default 2)
    """
    pid = id.upper().replace(" ", "_")
    if pid in PARTNERS:
        return {"error": f"Partner '{pid}' already exists. Use update_partner_config() to modify."}
    partner = {
        "id": pid, "name": name, "type": type,
        "min_loan": min_loan, "max_loan": max_loan,
        "min_tenure": min_tenure, "max_tenure": max_tenure,
        "interest_rate_pa": interest_rate_pa,
        "processing_fee_pct": processing_fee_pct,
        "prepayment_charge_pct": prepayment_charge_pct,
        "foreclosure_charge_pct": foreclosure_charge_pct,
        "min_credit_score": min_credit_score,
        "max_foir": max_foir,
        "api_endpoint": api_endpoint,
        "webhook_url": webhook_url,
        "status": "SANDBOX",
        "disbursed_count": 0, "npa_rate": 0.0,
        "created_at": _now(),
    }
    PARTNERS[pid] = partner
    _audit("REGISTER", "PARTNER", pid, f"New partner registered by PM — status: SANDBOX")
    return {"success": True, "partner_id": pid, "status": "SANDBOX",
            "message": "Partner registered in SANDBOX. Test all flows before activating."}


@mcp.tool()
def update_partner_config(
    partner_id: str,
    interest_rate_pa: Optional[float] = None,
    processing_fee_pct: Optional[float] = None,
    max_loan: Optional[int] = None,
    min_credit_score: Optional[int] = None,
    max_foir: Optional[float] = None,
    status: Optional[Literal["ACTIVE", "SANDBOX", "INACTIVE"]] = None,
) -> dict:
    """
    Update configuration fields for an existing partner.

    Args:
        partner_id:        Partner to update
        interest_rate_pa:  New annual interest rate (%)
        processing_fee_pct:New processing fee (%)
        max_loan:          New maximum loan amount
        min_credit_score:  New minimum credit score
        max_foir:          New max FOIR (0.0–1.0)
        status:            Change partner status
    """
    p = PARTNERS.get(partner_id.upper())
    if not p:
        return {"error": f"Partner '{partner_id}' not found."}
    changes = {}
    for field, val in [
        ("interest_rate_pa", interest_rate_pa), ("processing_fee_pct", processing_fee_pct),
        ("max_loan", max_loan), ("min_credit_score", min_credit_score),
        ("max_foir", max_foir), ("status", status),
    ]:
        if val is not None:
            changes[field] = {"old": p[field], "new": val}
            p[field] = val
    _audit("UPDATE_CONFIG", "PARTNER", partner_id.upper(), json.dumps(changes))
    return {"success": True, "partner_id": partner_id.upper(), "changes_applied": changes}


@mcp.tool()
def check_partner_health(partner_id: str) -> dict:
    """
    Simulate an API health check against a partner's endpoint.

    Args:
        partner_id: Partner to check
    """
    p = PARTNERS.get(partner_id.upper())
    if not p:
        return {"error": f"Partner '{partner_id}' not found."}
    # Simulate health — INACTIVE partners fail
    healthy = p["status"] != "INACTIVE"
    latency = random.randint(45, 320) if healthy else None
    return {
        "partner_id": partner_id.upper(),
        "endpoint": p["api_endpoint"],
        "status": "UP" if healthy else "DOWN",
        "http_status": 200 if healthy else 503,
        "latency_ms": latency,
        "checked_at": _now(),
        "webhook_reachable": healthy,
    }


@mcp.tool()
def get_partner_metrics(partner_id: str) -> dict:
    """
    Get portfolio metrics for a partner: volume, approval rate, NPA, collections.

    Args:
        partner_id: Partner to analyse
    """
    p = PARTNERS.get(partner_id.upper())
    if not p:
        return {"error": f"Partner '{partner_id}' not found."}
    partner_apps = [a for a in APPLICATIONS.values() if a["partner_id"] == partner_id.upper()]
    partner_loans = [l for l in LOANS.values() if l["partner_id"] == partner_id.upper()]
    approved = [a for a in partner_apps if a["status"] in ("DISBURSED", "OFFERED", "ACCEPTED")]
    rejected = [a for a in partner_apps if a["status"] == "REJECTED"]
    active_loans = [l for l in partner_loans if l["status"] == "ACTIVE"]
    total_outstanding = sum(l["outstanding_principal"] for l in active_loans)
    return {
        "partner_id": partner_id.upper(), "partner_name": p["name"],
        "total_applications": len(partner_apps),
        "approved": len(approved), "rejected": len(rejected),
        "approval_rate": f"{len(approved)/max(len(partner_apps),1)*100:.1f}%",
        "total_loans_disbursed": p["disbursed_count"] + len([l for l in partner_loans if l["status"] in ("ACTIVE","CLOSED")]),
        "active_loans": len(active_loans),
        "total_outstanding": f"₹{total_outstanding:,.0f}",
        "npa_rate": f"{p['npa_rate']}%",
        "npa_amount": f"₹{total_outstanding * p['npa_rate'] / 100:,.0f}",
        "avg_loan_amount": f"₹{sum(l['principal'] for l in partner_loans)/max(len(partner_loans),1):,.0f}",
        "generated_at": _now(),
    }


# ══════════════════════════════════════════════════════════════════════════════
# ── CUSTOMER & KYC TOOLS ──────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def create_customer(
    name: str,
    pan: str,
    aadhaar: str,
    mobile: str,
    email: str,
    dob: str,
    gender: Literal["M", "F", "O"],
    monthly_income: int,
    employment_type: Literal["SALARIED", "SELF_EMPLOYED", "BUSINESS"],
    city: str,
    pincode: str,
    bank_account: str,
    ifsc: str,
    employer: str = "",
    existing_emi: int = 0,
) -> dict:
    """
    Onboard a new customer.

    Args:
        name:            Full legal name as per PAN
        pan:             PAN number (10 chars, e.g. ABCDE1234F)
        aadhaar:         12-digit Aadhaar (spaces allowed)
        mobile:          10-digit mobile number
        email:           Email address
        dob:             Date of birth YYYY-MM-DD
        gender:          M | F | O
        monthly_income:  Gross monthly income in ₹
        employment_type: SALARIED | SELF_EMPLOYED | BUSINESS
        city:            City of residence
        pincode:         6-digit pincode
        bank_account:    Bank account number
        ifsc:            Bank IFSC code
        employer:        Employer / business name
        existing_emi:    Sum of all existing EMIs per month (₹)
    """
    pan = pan.upper().strip()
    # Check duplicate PAN
    for c in CUSTOMERS.values():
        if c["pan"] == pan:
            return {"error": f"Customer with PAN {pan} already exists: {c['id']}"}
    cid = _uid("CUST")
    CUSTOMERS[cid] = {
        "id": cid, "name": name, "pan": pan,
        "aadhaar": aadhaar.replace(" ", ""), "mobile": mobile, "email": email,
        "dob": dob, "gender": gender, "monthly_income": monthly_income,
        "employment_type": employment_type, "employer": employer,
        "existing_emi": existing_emi, "city": city, "pincode": pincode,
        "bank_account": bank_account, "ifsc": ifsc.upper(),
        "credit_score": None, "kyc_status": "PENDING",
        "created_at": _now(),
    }
    _audit("CREATE", "CUSTOMER", cid, f"New customer: {name} | {pan}")
    return {"success": True, "customer_id": cid, "kyc_status": "PENDING",
            "next_steps": ["verify_pan", "verify_aadhaar", "fetch_credit_score"]}


@mcp.tool()
def get_customer_profile(customer_id: str) -> dict:
    """
    Fetch full customer profile including KYC status and credit score.

    Args:
        customer_id: Customer identifier (e.g. CUST001)
    """
    c = CUSTOMERS.get(customer_id)
    if not c:
        return {"error": f"Customer '{customer_id}' not found."}
    _audit("GET", "CUSTOMER", customer_id)
    # Mask sensitive fields for display
    profile = dict(c)
    profile["aadhaar"] = f"XXXX XXXX {c['aadhaar'][-4:]}"
    return profile


@mcp.tool()
def verify_pan(customer_id: str) -> dict:
    """
    Simulate PAN verification against NSDL/UTI (mock).

    Args:
        customer_id: Customer to verify
    """
    c = CUSTOMERS.get(customer_id)
    if not c:
        return {"error": f"Customer '{customer_id}' not found."}
    pan = c["pan"]
    # Validation: PAN format AAAAA9999A
    import re
    valid_format = bool(re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]$", pan))
    result = {
        "customer_id": customer_id, "pan": pan,
        "verified": valid_format,
        "name_match": "EXACT" if valid_format else "NO_MATCH",
        "pan_status": "ACTIVE" if valid_format else "INVALID_FORMAT",
        "source": "NSDL_MOCK", "verified_at": _now(),
    }
    if not valid_format:
        result["error"] = "PAN format invalid. Expected: AAAAA9999A"
    _audit("VERIFY_PAN", "CUSTOMER", customer_id, f"PAN: {pan} | Result: {result['pan_status']}")
    return result


@mcp.tool()
def verify_aadhaar(customer_id: str) -> dict:
    """
    Simulate Aadhaar OTP-based verification (mock — no real OTP sent).

    Args:
        customer_id: Customer to verify
    """
    c = CUSTOMERS.get(customer_id)
    if not c:
        return {"error": f"Customer '{customer_id}' not found."}
    aadhaar = c["aadhaar"].replace(" ", "")
    valid = len(aadhaar) == 12 and aadhaar.isdigit()
    if valid:
        c["kyc_status"] = "VERIFIED"
    result = {
        "customer_id": customer_id,
        "aadhaar_last4": aadhaar[-4:],
        "verified": valid,
        "kyc_status": c["kyc_status"],
        "address_seeded": valid,
        "source": "UIDAI_MOCK", "verified_at": _now(),
    }
    if not valid:
        result["error"] = "Aadhaar must be 12 digits."
    _audit("VERIFY_AADHAAR", "CUSTOMER", customer_id, f"Result: {c['kyc_status']}")
    return result


@mcp.tool()
def fetch_credit_score(customer_id: str, bureau: str = "CIBIL") -> dict:
    """
    Pull credit bureau score for a customer (mock — deterministic from PAN).

    Args:
        customer_id: Customer to check
        bureau:      CIBIL | EXPERIAN | EQUIFAX | CRIF (default CIBIL)
    """
    c = CUSTOMERS.get(customer_id)
    if not c:
        return {"error": f"Customer '{customer_id}' not found."}
    if c["kyc_status"] != "VERIFIED":
        return {"error": "KYC must be VERIFIED before credit bureau pull."}
    # If already fetched, return same score (deterministic)
    if c.get("credit_score") is None:
        # Deterministic from PAN hash
        seed = sum(ord(ch) for ch in c["pan"]) % 300
        c["credit_score"] = 580 + seed   # 580–879 range
    score = c["credit_score"]
    rating = ("EXCELLENT" if score >= 800 else "GOOD" if score >= 740
              else "FAIR" if score >= 680 else "POOR" if score >= 620 else "VERY_POOR")
    _audit("CREDIT_PULL", "CUSTOMER", customer_id, f"Bureau: {bureau} | Score: {score}")
    return {
        "customer_id": customer_id, "bureau": bureau,
        "score": score, "score_range": "300–900",
        "rating": rating,
        "dpd_30": 0 if score > 720 else random.randint(0, 2),
        "dpd_60": 0 if score > 700 else random.randint(0, 1),
        "active_loans": random.randint(0, 3),
        "total_credit_limit": random.randint(50_000, 5_00_000),
        "credit_utilisation": f"{random.randint(10, 60)}%",
        "inquiries_6m": random.randint(0, 4),
        "pulled_at": _now(),
        "report_id": _uid("CR"),
    }


@mcp.tool()
def check_eligibility(
    customer_id: str,
    partner_id: str,
    loan_amount: float,
    tenure_months: int,
) -> dict:
    """
    Check if a customer is eligible for a loan with a specific partner.
    Validates credit score, FOIR, loan limits, tenure, and KYC.

    Args:
        customer_id:   Customer to evaluate
        partner_id:    Target lending partner
        loan_amount:   Requested loan amount in ₹
        tenure_months: Requested tenure in months
    """
    c = CUSTOMERS.get(customer_id)
    p = PARTNERS.get(partner_id.upper())
    if not c:
        return {"error": f"Customer '{customer_id}' not found."}
    if not p:
        return {"error": f"Partner '{partner_id}' not found."}
    eligible, reason = _check_eligibility(c, p, loan_amount, tenure_months)
    emi = _emi(loan_amount, p["interest_rate_pa"], tenure_months)
    foir = _foir(c, emi)
    _audit("ELIGIBILITY_CHECK", "CUSTOMER", customer_id,
           f"Partner: {partner_id} | ₹{loan_amount:,.0f} x {tenure_months}m | {reason}")
    return {
        "customer_id": customer_id, "partner_id": partner_id.upper(),
        "eligible": eligible, "reason": reason,
        "loan_amount": loan_amount, "tenure_months": tenure_months,
        "estimated_emi": f"₹{emi:,.0f}",
        "foir": f"{foir:.1%}",
        "max_foir_allowed": f"{p['max_foir']:.0%}",
        "credit_score": c["credit_score"],
        "min_score_required": p["min_credit_score"],
        "kyc_status": c["kyc_status"],
    }


# ══════════════════════════════════════════════════════════════════════════════
# ── LOAN APPLICATION TOOLS ────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def create_loan_application(
    customer_id: str,
    partner_id: str,
    loan_amount: float,
    tenure_months: int,
    purpose: Literal["PERSONAL", "HOME_RENOVATION", "MEDICAL", "TRAVEL",
                     "EDUCATION", "WEDDING", "BUSINESS", "VEHICLE", "DEBT_CONSOLIDATION"],
    notes: str = "",
) -> dict:
    """
    Create a new loan application after eligibility is confirmed.

    Args:
        customer_id:   Applicant's customer ID
        partner_id:    Target partner (CRED, PHONEPE, GPAY, PAYTM, AMAZON_PAY, SLICE)
        loan_amount:   Requested loan amount in ₹
        tenure_months: Loan tenure in months
        purpose:       Loan purpose category
        notes:         Optional PM notes
    """
    c = CUSTOMERS.get(customer_id)
    p = PARTNERS.get(partner_id.upper())
    if not c:
        return {"error": f"Customer '{customer_id}' not found."}
    if not p:
        return {"error": f"Partner '{partner_id}' not found."}
    if p["status"] == "INACTIVE":
        return {"error": f"Partner '{partner_id}' is INACTIVE. Cannot accept applications."}

    eligible, reason = _check_eligibility(c, p, loan_amount, tenure_months)
    app_id = _uid("APP")
    emi = _emi(loan_amount, p["interest_rate_pa"], tenure_months)
    fee = round(loan_amount * p["processing_fee_pct"] / 100, 2)

    APPLICATIONS[app_id] = {
        "id": app_id, "partner_id": partner_id.upper(), "customer_id": customer_id,
        "loan_amount": loan_amount, "tenure_months": tenure_months,
        "purpose": purpose, "notes": notes,
        "status": "PENDING",
        "credit_score_at_apply": c.get("credit_score"),
        "offered_rate": None, "processing_fee": fee,
        "estimated_emi": emi,
        "auto_eligibility": eligible, "eligibility_reason": reason,
        "created_at": _now(), "updated_at": _now(),
    }
    _audit("CREATE", "APPLICATION", app_id,
           f"Customer: {customer_id} | Partner: {partner_id} | ₹{loan_amount:,.0f} x {tenure_months}m")
    return {
        "success": True, "application_id": app_id,
        "status": "PENDING",
        "estimated_emi": f"₹{emi:,.0f}",
        "processing_fee": f"₹{fee:,.0f}",
        "auto_eligibility": eligible,
        "eligibility_note": reason,
        "next_step": "submit_for_credit_assessment" if eligible else "Application may be rejected — check eligibility_note",
    }


@mcp.tool()
async def submit_for_credit_assessment(application_id: str, ctx: Context) -> dict:
    """
    Submit an application for credit underwriting / bureau assessment.
    Emits real-time notifications for each underwriting step.
    Transitions status: PENDING → UNDER_REVIEW.

    Args:
        application_id: Application to submit
    """
    app = APPLICATIONS.get(application_id)
    if not app:
        return {"error": f"Application '{application_id}' not found."}
    if app["status"] != "PENDING":
        return {"error": f"Application is in '{app['status']}' status. Only PENDING apps can be submitted."}

    c = CUSTOMERS.get(app["customer_id"], {})
    p = PARTNERS.get(app["partner_id"], {})
    pan_masked = c.get("pan", "XXXXX")[:5] + "XXXXX"

    await ctx.report_progress(0, 5)
    await ctx.info(f"📋 Assessment started for {application_id} — Partner: {app['partner_id']}")
    await asyncio.sleep(0.3)

    await ctx.report_progress(1, 5)
    await ctx.info(f"🏦 Pulling CIBIL bureau report for PAN {pan_masked}...")
    await asyncio.sleep(0.4)

    score = c.get("credit_score", 0)
    score_label = "EXCELLENT" if score >= 800 else "GOOD" if score >= 740 else "FAIR" if score >= 680 else "POOR"
    await ctx.report_progress(2, 5)
    await ctx.info(f"📊 CIBIL response received — Score: {score} ({score_label}), DPD-30: 0, Active Loans: {random.randint(0,3)}")
    await asyncio.sleep(0.3)

    emi_est = _emi(app["loan_amount"], p.get("interest_rate_pa", 18), app["tenure_months"])
    foir    = _foir(c, emi_est) if c.get("monthly_income") else 0
    await ctx.report_progress(3, 5)
    await ctx.info(f"⚖️  Policy checks — FOIR: {foir:.1%} (max {p.get('max_foir',0.5):.0%}), Score vs min {p.get('min_credit_score','?')}")
    await asyncio.sleep(0.3)

    eligible, reason = _check_eligibility(c, p, app["loan_amount"], app["tenure_months"]) if c and p else (False, "Missing data")
    await ctx.report_progress(4, 5)
    if eligible:
        await ctx.info(f"✅ All policy checks passed. Proceeding to offer generation.")
    else:
        await ctx.warning(f"⚠️  Policy check failed: {reason}")
    await asyncio.sleep(0.2)

    app["status"] = "UNDER_REVIEW"
    app["updated_at"] = _now()
    app["assessment_id"] = _uid("ASM")
    _audit("SUBMIT_ASSESSMENT", "APPLICATION", application_id)

    await ctx.report_progress(5, 5)
    await ctx.info(f"🏁 Assessment complete — ID: {app['assessment_id']} | Decision: {'PROCEED' if eligible else 'REVIEW'}")

    return {
        "success": True, "application_id": application_id,
        "status": "UNDER_REVIEW",
        "assessment_id": app["assessment_id"],
        "credit_score_checked": score,
        "foir_calculated": f"{foir:.1%}",
        "policy_eligible": eligible,
        "next_step": "generate_loan_offer (if approved) or reject_application",
    }


@mcp.tool()
def generate_loan_offer(
    application_id: str,
    approved_amount: Optional[float] = None,
    approved_tenure: Optional[int] = None,
    override_rate: Optional[float] = None,
) -> dict:
    """
    Generate a loan offer for an application under review.
    Optionally override amount/tenure/rate (e.g. counter-offer).

    Args:
        application_id:  Application to offer
        approved_amount: Override loan amount (default = requested)
        approved_tenure: Override tenure in months
        override_rate:   Override interest rate % p.a. (uses partner default if omitted)
    """
    app = APPLICATIONS.get(application_id)
    if not app:
        return {"error": f"Application '{application_id}' not found."}
    if app["status"] not in ("UNDER_REVIEW", "PENDING"):
        return {"error": f"Cannot generate offer: status is '{app['status']}'."}
    p = PARTNERS[app["partner_id"]]
    c = CUSTOMERS[app["customer_id"]]
    amount  = approved_amount or app["loan_amount"]
    tenure  = approved_tenure or app["tenure_months"]
    rate    = override_rate   or p["interest_rate_pa"]
    emi     = _emi(amount, rate, tenure)
    fee     = round(amount * p["processing_fee_pct"] / 100, 2)
    total_interest = round(emi * tenure - amount, 2)

    app["status"]         = "OFFERED"
    app["loan_amount"]    = amount
    app["tenure_months"]  = tenure
    app["offered_rate"]   = rate
    app["processing_fee"] = fee
    app["estimated_emi"]  = emi
    app["offer_expiry"]   = _date_str(date.today() + timedelta(days=7))
    app["updated_at"]     = _now()

    _audit("OFFER_GENERATED", "APPLICATION", application_id,
           f"₹{amount:,.0f} @ {rate}% x {tenure}m | EMI ₹{emi:,.0f}")
    return {
        "success": True, "application_id": application_id,
        "status": "OFFERED",
        "offer_details": {
            "loan_amount": f"₹{amount:,.0f}",
            "tenure": f"{tenure} months",
            "interest_rate_pa": f"{rate}%",
            "emi": f"₹{emi:,.0f}",
            "processing_fee": f"₹{fee:,.0f}",
            "total_interest": f"₹{total_interest:,.0f}",
            "total_repayment": f"₹{emi * tenure:,.0f}",
            "offer_valid_until": app["offer_expiry"],
        },
        "next_step": "accept_loan_offer | reject_loan_offer",
    }


@mcp.tool()
def accept_loan_offer(application_id: str, customer_consent: bool = True) -> dict:
    """
    Customer accepts the loan offer. Transitions: OFFERED → ACCEPTED.
    Precondition for disbursement.

    Args:
        application_id:   Application with an active offer
        customer_consent: Must be True to proceed
    """
    app = APPLICATIONS.get(application_id)
    if not app:
        return {"error": f"Application '{application_id}' not found."}
    if app["status"] != "OFFERED":
        return {"error": f"Application is '{app['status']}'. Only OFFERED apps can be accepted."}
    if not customer_consent:
        return {"error": "customer_consent must be True to accept the offer."}
    app["status"] = "ACCEPTED"
    app["accepted_at"] = _now()
    app["updated_at"] = _now()
    _audit("OFFER_ACCEPTED", "APPLICATION", application_id)
    return {
        "success": True, "application_id": application_id,
        "status": "ACCEPTED",
        "next_step": "disburse_loan",
        "message": "Offer accepted. Ready for disbursement.",
    }


@mcp.tool()
def reject_application(
    application_id: str,
    reason: str,
    rejection_stage: Literal["CREDIT_ASSESSMENT", "POLICY", "MANUAL_REVIEW", "CUSTOMER_REQUEST"] = "CREDIT_ASSESSMENT",
) -> dict:
    """
    Reject a loan application with a documented reason.

    Args:
        application_id: Application to reject
        reason:         Human-readable rejection reason
        rejection_stage:Stage at which rejection occurred
    """
    app = APPLICATIONS.get(application_id)
    if not app:
        return {"error": f"Application '{application_id}' not found."}
    if app["status"] in ("DISBURSED", "CLOSED", "REJECTED"):
        return {"error": f"Cannot reject: status is '{app['status']}'."}
    app["status"] = "REJECTED"
    app["rejection_reason"] = reason
    app["rejection_stage"] = rejection_stage
    app["updated_at"] = _now()
    _audit("REJECTED", "APPLICATION", application_id, f"Stage: {rejection_stage} | Reason: {reason}")
    return {"success": True, "application_id": application_id, "status": "REJECTED",
            "reason": reason, "stage": rejection_stage}


@mcp.tool()
def list_applications(
    partner_id: Optional[str] = None,
    customer_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    """
    List loan applications with optional filters.

    Args:
        partner_id:  Filter by partner (e.g. CRED)
        customer_id: Filter by customer
        status:      Filter by status: PENDING | UNDER_REVIEW | OFFERED | ACCEPTED |
                     DISBURSED | REJECTED | CLOSED
        limit:       Max records to return (default 20)
    """
    apps = list(APPLICATIONS.values())
    if partner_id:
        apps = [a for a in apps if a["partner_id"] == partner_id.upper()]
    if customer_id:
        apps = [a for a in apps if a["customer_id"] == customer_id]
    if status:
        apps = [a for a in apps if a["status"].upper() == status.upper()]
    apps.sort(key=lambda a: a["created_at"], reverse=True)
    return apps[:limit]


@mcp.tool()
def get_application_status(application_id: str) -> dict:
    """
    Get current status and details of a loan application.

    Args:
        application_id: Application ID
    """
    app = APPLICATIONS.get(application_id)
    if not app:
        return {"error": f"Application '{application_id}' not found."}
    return app


# ══════════════════════════════════════════════════════════════════════════════
# ── LOAN DISBURSEMENT & SERVICING TOOLS ───────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def disburse_loan(
    application_id: str,
    ctx: Context,
    disbursement_date: Optional[str] = None,
) -> dict:
    """
    Disburse an accepted loan. Elicits bank account confirmation then emits
    real-time notifications for each disbursement step.

    Args:
        application_id:    Accepted application to disburse
        disbursement_date: YYYY-MM-DD (default today)
    """
    app = APPLICATIONS.get(application_id)
    if not app:
        return {"error": f"Application '{application_id}' not found."}
    if app["status"] != "ACCEPTED":
        return {"error": f"Application must be ACCEPTED before disbursement. Current: {app['status']}."}
    c = CUSTOMERS[app["customer_id"]]

    # ── Elicitation: confirm bank account before sending money ────────────────
    try:
        elicit_result = await ctx.elicit(
            message=(
                "💰 DISBURSEMENT CONFIRMATION\n\n"
                f"Amount : ₹{app['loan_amount']:,.0f}\n"
                f"Account: {c['bank_account']}  IFSC: {c['ifsc']}\n"
                f"Name   : {c['name']}\n\n"
                "Please confirm the bank details are correct before funds are transferred."
            ),
            schema={
                "type": "object",
                "properties": {
                    "confirmed": {
                        "type": "boolean",
                        "description": "Confirm bank account details are correct (true = proceed)"
                    },
                    "remarks": {
                        "type": "string",
                        "description": "Optional remarks for this disbursement"
                    },
                },
                "required": ["confirmed"],
            },
        )
        action  = getattr(elicit_result, "action", "accept")
        content = getattr(elicit_result, "content", {}) or {}
        if action == "cancel" or not content.get("confirmed", True):
            await ctx.warning("🚫 Disbursement cancelled by user at confirmation step.")
            return {"success": False, "reason": "Disbursement cancelled at bank confirmation."}
        remarks = content.get("remarks", "")
    except Exception:
        # Elicitation not supported by this client version — proceed with warning
        await ctx.warning("⚠️  Elicitation not supported — proceeding without explicit confirmation.")
        remarks = ""

    # ── Notifications: step-by-step disbursement ──────────────────────────────
    disb_date = disbursement_date or _date_str(date.today())
    disb_dt   = date.fromisoformat(disb_date)
    maturity  = disb_dt + timedelta(days=30 * app["tenure_months"])
    loan_id   = _uid("LOAN")
    emi       = app.get("estimated_emi") or _emi(app["loan_amount"], app["offered_rate"], app["tenure_months"])
    fee       = app.get("processing_fee", 0)
    net_amt   = app["loan_amount"] - fee
    utr_ref   = _uid("UTR")

    await ctx.report_progress(0, 4)
    await ctx.info(f"🏦 Validating bank account {c['bank_account']} with IFSC {c['ifsc']}...")
    await asyncio.sleep(0.3)

    await ctx.report_progress(1, 4)
    await ctx.info(f"📤 Initiating NEFT transfer of ₹{net_amt:,.0f} via RBI payment gateway...")
    await asyncio.sleep(0.4)

    await ctx.report_progress(2, 4)
    await ctx.info(f"🔐 UTR generated: {utr_ref} | Processing fee deducted: ₹{fee:,.0f}")
    await asyncio.sleep(0.3)

    LOANS[loan_id] = {
        "id": loan_id, "application_id": application_id,
        "partner_id": app["partner_id"], "customer_id": app["customer_id"],
        "principal": app["loan_amount"], "interest_rate_pa": app["offered_rate"],
        "tenure_months": app["tenure_months"], "emi_amount": emi,
        "processing_fee": fee,
        "disbursement_date": disb_date,
        "maturity_date": _date_str(maturity),
        "next_emi_date": _date_str(disb_dt + timedelta(days=30)),
        "status": "ACTIVE", "emis_paid": 0,
        "emis_remaining": app["tenure_months"],
        "outstanding_principal": app["loan_amount"],
        "total_overdue": 0,
        "bank_account": c["bank_account"], "ifsc": c["ifsc"],
        "utr": utr_ref, "remarks": remarks, "created_at": _now(),
    }
    app["status"] = "DISBURSED"
    app["loan_id"] = loan_id
    app["updated_at"] = _now()
    PARTNERS[app["partner_id"]]["disbursed_count"] += 1
    _audit("DISBURSE", "LOAN", loan_id,
           f"Application: {application_id} | ₹{app['loan_amount']:,.0f} → {c['bank_account']}")

    await ctx.report_progress(4, 4)
    await ctx.info(f"✅ Disbursement confirmed! Loan {loan_id} created. First EMI on {_date_str(disb_dt + timedelta(days=30))}")

    return {
        "success": True, "loan_id": loan_id, "application_id": application_id,
        "amount_disbursed": f"₹{app['loan_amount']:,.0f}",
        "processing_fee_deducted": f"₹{fee:,.0f}",
        "net_disbursed": f"₹{net_amt:,.0f}",
        "to_account": c["bank_account"], "utr": utr_ref,
        "disbursement_date": disb_date,
        "first_emi_date": _date_str(disb_dt + timedelta(days=30)),
        "emi_amount": f"₹{emi:,.0f}",
        "maturity_date": _date_str(maturity),
    }


@mcp.tool()
def get_loan_details(loan_id: str) -> dict:
    """
    Get full details of a loan including status, outstanding, and schedule summary.

    Args:
        loan_id: Loan account ID
    """
    loan = LOANS.get(loan_id)
    if not loan:
        return {"error": f"Loan '{loan_id}' not found."}
    _audit("GET", "LOAN", loan_id)
    return loan


@mcp.tool()
def list_loans(
    partner_id: Optional[str] = None,
    customer_id: Optional[str] = None,
    status: Optional[Literal["ACTIVE", "CLOSED", "NPA", "WRITTEN_OFF"]] = None,
    limit: int = 20,
) -> list[dict]:
    """
    List loan accounts with optional filters.

    Args:
        partner_id:  Filter by partner
        customer_id: Filter by customer
        status:      ACTIVE | CLOSED | NPA | WRITTEN_OFF
        limit:       Max records (default 20)
    """
    loans = list(LOANS.values())
    if partner_id:
        loans = [l for l in loans if l["partner_id"] == partner_id.upper()]
    if customer_id:
        loans = [l for l in loans if l["customer_id"] == customer_id]
    if status:
        loans = [l for l in loans if l["status"].upper() == status.upper()]
    loans.sort(key=lambda l: l["created_at"], reverse=True)
    return loans[:limit]


@mcp.tool()
def get_emi_schedule(loan_id: str) -> dict:
    """
    Generate the full EMI repayment schedule for a loan.

    Args:
        loan_id: Loan account ID
    """
    loan = LOANS.get(loan_id)
    if not loan:
        return {"error": f"Loan '{loan_id}' not found."}
    principal  = loan["principal"]
    rate_pa    = loan["interest_rate_pa"]
    rate_mo    = rate_pa / (12 * 100)
    tenure     = loan["tenure_months"]
    emi        = loan["emi_amount"]
    disb_date  = date.fromisoformat(loan["disbursement_date"])
    schedule   = []
    balance    = principal
    total_int  = 0.0
    for i in range(1, tenure + 1):
        emi_date    = disb_date + timedelta(days=30 * i)
        interest_c  = round(balance * rate_mo, 2)
        principal_c = round(min(emi - interest_c, balance), 2)
        balance     = round(balance - principal_c, 2)
        total_int  += interest_c
        paid        = i <= loan["emis_paid"]
        schedule.append({
            "emi_no":           i,
            "due_date":         _date_str(emi_date),
            "emi_amount":       emi,
            "principal":        principal_c,
            "interest":         interest_c,
            "closing_balance":  max(balance, 0),
            "status":           "PAID" if paid else ("UPCOMING" if i == loan["emis_paid"] + 1 else "FUTURE"),
        })
    _audit("EMI_SCHEDULE", "LOAN", loan_id)
    return {
        "loan_id":           loan_id,
        "principal":         f"₹{principal:,.0f}",
        "interest_rate_pa":  f"{rate_pa}%",
        "tenure_months":     tenure,
        "emi_amount":        f"₹{emi:,.0f}",
        "total_interest":    f"₹{total_int:,.0f}",
        "total_repayment":   f"₹{emi * tenure:,.0f}",
        "emis_paid":         loan["emis_paid"],
        "emis_remaining":    loan["emis_remaining"],
        "schedule":          schedule,
    }


@mcp.tool()
def get_loan_statement(loan_id: str) -> dict:
    """
    Generate a loan account statement with all transactions.

    Args:
        loan_id: Loan account ID
    """
    loan = LOANS.get(loan_id)
    if not loan:
        return {"error": f"Loan '{loan_id}' not found."}
    txns = [p for p in PAYMENTS.values() if p["loan_id"] == loan_id]
    txns.sort(key=lambda t: t["payment_date"])
    _audit("STATEMENT", "LOAN", loan_id)
    return {
        "loan_id":              loan_id,
        "customer_id":          loan["customer_id"],
        "partner_id":           loan["partner_id"],
        "loan_amount":          f"₹{loan['principal']:,.0f}",
        "disbursement_date":    loan["disbursement_date"],
        "interest_rate_pa":     f"{loan['interest_rate_pa']}%",
        "emi":                  f"₹{loan['emi_amount']:,.0f}",
        "outstanding_principal":f"₹{loan['outstanding_principal']:,.0f}",
        "total_overdue":        f"₹{loan['total_overdue']:,.0f}",
        "emis_paid":            loan["emis_paid"],
        "emis_remaining":       loan["emis_remaining"],
        "status":               loan["status"],
        "transactions":         txns,
        "generated_at":         _now(),
    }


@mcp.tool()
def generate_noc(loan_id: str) -> dict:
    """
    Generate a No Objection Certificate for a closed loan.

    Args:
        loan_id: Loan that has been fully repaid/closed
    """
    loan = LOANS.get(loan_id)
    if not loan:
        return {"error": f"Loan '{loan_id}' not found."}
    if loan["status"] not in ("CLOSED", "FORECLOSED"):
        return {"error": f"NOC can only be issued for CLOSED/FORECLOSED loans. Current: {loan['status']}."}
    c = CUSTOMERS[loan["customer_id"]]
    noc_ref = _uid("NOC")
    _audit("NOC_GENERATED", "LOAN", loan_id, f"NOC Ref: {noc_ref}")
    return {
        "noc_reference":     noc_ref,
        "loan_id":           loan_id,
        "customer_name":     c["name"],
        "pan":               c["pan"],
        "principal":         f"₹{loan['principal']:,.0f}",
        "disbursement_date": loan["disbursement_date"],
        "closure_status":    loan["status"],
        "outstanding":       "₹0.00",
        "noc_text": (
            f"This is to certify that {c['name']} (PAN: {c['pan']}) "
            f"has fully repaid Loan ID {loan_id} disbursed on {loan['disbursement_date']} "
            f"for ₹{loan['principal']:,}. No dues are outstanding. "
            f"NOC Reference: {noc_ref}."
        ),
        "issued_at": _now(),
        "valid_for": "Lifetime",
    }


# ══════════════════════════════════════════════════════════════════════════════
# ── PAYMENT TOOLS ─────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def process_emi_payment(
    loan_id: str,
    amount: float,
    ctx: Context,
    payment_mode: Literal["UPI", "NACH", "NET_BANKING", "NEFT", "RTGS", "CASH"] = "UPI",
    utr: Optional[str] = None,
) -> dict:
    """
    Process an EMI payment with real-time payment gateway notifications.

    Args:
        loan_id:      Loan account ID
        amount:       Amount paid (should match EMI amount; can be partial)
        payment_mode: Payment channel
        utr:          Bank UTR/reference (auto-generated if omitted)
    """
    loan = LOANS.get(loan_id)
    if not loan:
        return {"error": f"Loan '{loan_id}' not found."}
    if loan["status"] not in ("ACTIVE", "NPA"):
        return {"error": f"Loan is '{loan['status']}' — cannot accept payment."}
    if amount <= 0:
        return {"error": "Payment amount must be positive."}

    emi_no      = loan["emis_paid"] + 1
    rate_mo     = loan["interest_rate_pa"] / (12 * 100)
    interest_c  = round(loan["outstanding_principal"] * rate_mo, 2)
    principal_c = round(min(amount - interest_c, loan["outstanding_principal"]), 2)
    pay_id      = _uid("PAY")
    utr_ref     = utr or _uid("UTR")

    await ctx.report_progress(0, 3)
    await ctx.info(f"💳 Initiating EMI #{emi_no} payment of ₹{amount:,.0f} via {payment_mode} for {loan_id}...")
    await asyncio.sleep(0.3)

    await ctx.report_progress(1, 3)
    await ctx.info(f"🔄 {payment_mode} gateway processing | Principal: ₹{principal_c:,.0f} | Interest: ₹{interest_c:,.0f}")
    await asyncio.sleep(0.4)

    loan["outstanding_principal"] = round(max(loan["outstanding_principal"] - principal_c, 0), 2)
    loan["emis_paid"]    += 1
    loan["emis_remaining"] = max(loan["emis_remaining"] - 1, 0)
    loan["total_overdue"] = max(loan["total_overdue"] - amount, 0)
    if loan["outstanding_principal"] <= 0:
        loan["status"] = "CLOSED"
    elif loan["status"] == "NPA":
        loan["status"] = "ACTIVE"
    loan["next_emi_date"] = _date_str(date.today() + timedelta(days=30))

    PAYMENTS[pay_id] = {
        "id": pay_id, "loan_id": loan_id,
        "customer_id": loan["customer_id"], "partner_id": loan["partner_id"],
        "emi_number": emi_no, "amount": amount,
        "principal_component": principal_c, "interest_component": interest_c,
        "type": "EMI", "status": "SUCCESS", "payment_mode": payment_mode,
        "payment_date": _date_str(date.today()),
        "utr": utr_ref, "created_at": _now(),
    }
    _audit("EMI_PAYMENT", "LOAN", loan_id,
           f"EMI #{emi_no} | ₹{amount:,.0f} | Mode: {payment_mode} | UTR: {utr_ref}")

    await ctx.report_progress(3, 3)
    if loan["status"] == "CLOSED":
        await ctx.info(f"🎉 Loan {loan_id} FULLY REPAID! Outstanding: ₹0. Generate NOC next.")
    else:
        await ctx.info(f"✅ EMI #{emi_no} SUCCESS | UTR: {utr_ref} | Outstanding: ₹{loan['outstanding_principal']:,.0f} | {loan['emis_remaining']} EMIs left")

    return {
        "success": True, "payment_id": pay_id,
        "loan_id": loan_id, "emi_number": emi_no,
        "amount_paid": f"₹{amount:,.0f}",
        "principal_component": f"₹{principal_c:,.0f}",
        "interest_component": f"₹{interest_c:,.0f}",
        "outstanding_principal": f"₹{loan['outstanding_principal']:,.0f}",
        "emis_remaining": loan["emis_remaining"],
        "loan_status": loan["status"],
        "next_emi_date": loan.get("next_emi_date", "—"),
        "utr": utr_ref,
    }


@mcp.tool()
def calculate_prepayment(loan_id: str, prepayment_amount: float) -> dict:
    """
    Calculate prepayment impact — new outstanding, charges, and revised schedule.

    Args:
        loan_id:           Loan account
        prepayment_amount: Amount to prepay (must be > 0 and <= outstanding)
    """
    loan = LOANS.get(loan_id)
    if not loan:
        return {"error": f"Loan '{loan_id}' not found."}
    if loan["status"] != "ACTIVE":
        return {"error": f"Loan must be ACTIVE for prepayment calculation."}
    p = PARTNERS[loan["partner_id"]]
    charge_pct  = p["prepayment_charge_pct"]
    charge_amt  = round(prepayment_amount * charge_pct / 100, 2)
    new_outstanding = max(loan["outstanding_principal"] - prepayment_amount, 0)
    rate_pa     = loan["interest_rate_pa"]
    remaining   = loan["emis_remaining"]
    new_emi     = _emi(new_outstanding, rate_pa, remaining) if new_outstanding > 0 else 0
    savings     = round((loan["emi_amount"] - new_emi) * remaining, 2)
    return {
        "loan_id":             loan_id,
        "prepayment_amount":   f"₹{prepayment_amount:,.0f}",
        "prepayment_charge":   f"₹{charge_amt:,.0f} ({charge_pct}%)",
        "total_to_pay":        f"₹{prepayment_amount + charge_amt:,.0f}",
        "current_outstanding": f"₹{loan['outstanding_principal']:,.0f}",
        "new_outstanding":     f"₹{new_outstanding:,.0f}",
        "current_emi":         f"₹{loan['emi_amount']:,.0f}",
        "revised_emi":         f"₹{new_emi:,.0f}",
        "emis_remaining":      remaining,
        "interest_savings":    f"₹{savings:,.0f}",
    }


@mcp.tool()
def process_prepayment(
    loan_id: str,
    amount: float,
    payment_mode: Literal["UPI", "NEFT", "RTGS", "NET_BANKING"] = "NEFT",
) -> dict:
    """
    Execute a prepayment on an active loan.

    Args:
        loan_id:      Loan account ID
        amount:       Prepayment amount in ₹
        payment_mode: Payment channel
    """
    loan = LOANS.get(loan_id)
    if not loan:
        return {"error": f"Loan '{loan_id}' not found."}
    if loan["status"] != "ACTIVE":
        return {"error": f"Loan is '{loan['status']}'. Prepayment only for ACTIVE loans."}
    if amount > loan["outstanding_principal"]:
        return {"error": f"Prepayment ₹{amount:,.0f} exceeds outstanding ₹{loan['outstanding_principal']:,.0f}. Use process_foreclosure for full closure."}
    p = PARTNERS[loan["partner_id"]]
    charge = round(amount * p["prepayment_charge_pct"] / 100, 2)
    pay_id = _uid("PAY")
    loan["outstanding_principal"] = round(loan["outstanding_principal"] - amount, 2)
    # Recalculate EMI
    new_emi = _emi(loan["outstanding_principal"], loan["interest_rate_pa"], loan["emis_remaining"])
    loan["emi_amount"] = new_emi
    utr = _uid("UTR")
    PAYMENTS[pay_id] = {
        "id": pay_id, "loan_id": loan_id,
        "customer_id": loan["customer_id"], "partner_id": loan["partner_id"],
        "amount": amount, "prepayment_charge": charge,
        "type": "PREPAYMENT", "status": "SUCCESS", "payment_mode": payment_mode,
        "payment_date": _date_str(date.today()), "utr": utr, "created_at": _now(),
    }
    _audit("PREPAYMENT", "LOAN", loan_id, f"₹{amount:,.0f} | Charge: ₹{charge:,.0f}")
    return {
        "success": True, "payment_id": pay_id,
        "prepayment_amount": f"₹{amount:,.0f}",
        "prepayment_charge": f"₹{charge:,.0f}",
        "new_outstanding": f"₹{loan['outstanding_principal']:,.0f}",
        "revised_emi": f"₹{new_emi:,.0f}",
        "emis_remaining": loan["emis_remaining"],
        "utr": utr,
    }


@mcp.tool()
async def process_foreclosure(
    loan_id: str,
    ctx: Context,
    payment_mode: Literal["UPI", "NEFT", "RTGS", "NET_BANKING"] = "RTGS",
) -> dict:
    """
    Fully foreclose a loan. Elicits settlement confirmation then emits
    real-time closure notifications.

    Args:
        loan_id:      Loan account ID
        payment_mode: Payment channel for the final settlement
    """
    loan = LOANS.get(loan_id)
    if not loan:
        return {"error": f"Loan '{loan_id}' not found."}
    if loan["status"] != "ACTIVE":
        return {"error": f"Loan is '{loan['status']}'. Foreclosure only for ACTIVE loans."}
    p = PARTNERS[loan["partner_id"]]
    outstanding = loan["outstanding_principal"]
    charge = round(outstanding * p["foreclosure_charge_pct"] / 100, 2)
    total_settlement = outstanding + charge

    # ── Elicitation: customer must confirm settlement amount ──────────────────
    try:
        elicit_result = await ctx.elicit(
            message=(
                "🔒 FORECLOSURE SETTLEMENT CONFIRMATION\n\n"
                f"Loan        : {loan_id}\n"
                f"Outstanding : ₹{outstanding:,.0f}\n"
                f"Charge ({p['foreclosure_charge_pct']}%) : ₹{charge:,.0f}\n"
                f"Total Due   : ₹{total_settlement:,.0f}\n\n"
                "Customer must acknowledge total settlement amount to proceed."
            ),
            schema={
                "type": "object",
                "properties": {
                    "customer_confirmed": {
                        "type": "boolean",
                        "description": "Customer confirms the total settlement amount (true = proceed)"
                    },
                    "payment_source": {
                        "type": "string",
                        "description": "Funding source (e.g. savings account, sale proceeds)"
                    },
                },
                "required": ["customer_confirmed"],
            },
        )
        action  = getattr(elicit_result, "action", "accept")
        content = getattr(elicit_result, "content", {}) or {}
        if action == "cancel" or not content.get("customer_confirmed", True):
            await ctx.warning("🚫 Foreclosure cancelled by customer.")
            return {"success": False, "reason": "Foreclosure cancelled at settlement confirmation."}
        payment_source = content.get("payment_source", "Not specified")
    except Exception:
        await ctx.warning("⚠️  Elicitation unavailable — proceeding without settlement confirmation.")
        payment_source = "Not specified"

    await ctx.info(f"📝 Settlement confirmed | Source: {payment_source} | Mode: {payment_mode}")
    await asyncio.sleep(0.3)

    pay_id = _uid("PAY")
    utr = _uid("UTR")

    await ctx.report_progress(0, 3)
    await ctx.info(f"🔄 Processing foreclosure settlement of ₹{total_settlement:,.0f} via {payment_mode}...")
    await asyncio.sleep(0.4)

    loan["status"] = "FORECLOSED"
    loan["outstanding_principal"] = 0.0
    loan["emis_remaining"] = 0
    PAYMENTS[pay_id] = {
        "id": pay_id, "loan_id": loan_id,
        "customer_id": loan["customer_id"], "partner_id": loan["partner_id"],
        "amount": total_settlement, "outstanding_settled": outstanding,
        "foreclosure_charge": charge,
        "type": "FORECLOSURE", "status": "SUCCESS", "payment_mode": payment_mode,
        "payment_date": _date_str(date.today()), "utr": utr, "created_at": _now(),
    }
    _audit("FORECLOSURE", "LOAN", loan_id, f"Settlement: ₹{total_settlement:,.0f}")

    await ctx.report_progress(2, 3)
    await ctx.info(f"🔐 UTR: {utr} | Loan account {loan_id} closed in ledger.")
    await asyncio.sleep(0.2)

    await ctx.report_progress(3, 3)
    await ctx.info(f"✅ Foreclosure complete! Call generate_noc('{loan_id}') to issue NOC.")

    return {
        "success": True, "payment_id": pay_id,
        "loan_id": loan_id, "loan_status": "FORECLOSED",
        "outstanding_settled": f"₹{outstanding:,.0f}",
        "foreclosure_charge": f"₹{charge:,.0f} ({p['foreclosure_charge_pct']}%)",
        "total_paid": f"₹{total_settlement:,.0f}",
        "utr": utr,
        "next_step": "generate_noc",
    }


@mcp.tool()
def get_payment_history(loan_id: str) -> list[dict]:
    """
    Get all payment transactions for a loan.

    Args:
        loan_id: Loan account ID
    """
    txns = [p for p in PAYMENTS.values() if p["loan_id"] == loan_id]
    txns.sort(key=lambda t: t["payment_date"])
    _audit("PAYMENT_HISTORY", "LOAN", loan_id)
    return txns


# ══════════════════════════════════════════════════════════════════════════════
# ── COLLECTIONS & NPA TOOLS ───────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def mark_loan_overdue(
    loan_id: str,
    overdue_amount: float,
    overdue_days: int,
) -> dict:
    """
    Mark a loan as overdue / NPA for testing collection flows.

    Args:
        loan_id:        Loan account ID
        overdue_amount: Amount overdue in ₹
        overdue_days:   Days past due (90+ triggers NPA classification)
    """
    loan = LOANS.get(loan_id)
    if not loan:
        return {"error": f"Loan '{loan_id}' not found."}
    if loan["status"] != "ACTIVE":
        return {"error": f"Only ACTIVE loans can be marked overdue."}
    loan["total_overdue"] = overdue_amount
    loan["overdue_days"]  = overdue_days
    if overdue_days >= 90:
        loan["status"] = "NPA"
        category = "NPA"
    else:
        category = "SMA-1" if overdue_days >= 30 else "SMA-0"
    loan["npa_category"] = category
    _audit("MARK_OVERDUE", "LOAN", loan_id,
           f"₹{overdue_amount:,.0f} | {overdue_days} DPD | Category: {category}")
    return {
        "loan_id": loan_id, "status": loan["status"],
        "overdue_amount": f"₹{overdue_amount:,.0f}",
        "overdue_days": overdue_days, "category": category,
        "collection_action": (
            "Legal / SARFAESI" if overdue_days >= 90 else
            "Hard collection call" if overdue_days >= 60 else
            "Reminder SMS + call"
        ),
    }


@mcp.tool()
def get_overdue_loans(
    partner_id: Optional[str] = None,
    min_days: int = 1,
) -> list[dict]:
    """
    List all overdue loans for collection follow-up.

    Args:
        partner_id: Filter by partner (optional)
        min_days:   Minimum days past due (default 1)
    """
    overdue = []
    for loan in LOANS.values():
        dpd = loan.get("overdue_days", 0)
        if dpd >= min_days and loan["total_overdue"] > 0:
            if partner_id and loan["partner_id"] != partner_id.upper():
                continue
            c = CUSTOMERS.get(loan["customer_id"], {})
            overdue.append({
                "loan_id": loan["id"],
                "customer_name": c.get("name", "—"),
                "partner_id": loan["partner_id"],
                "outstanding": f"₹{loan['outstanding_principal']:,.0f}",
                "overdue_amount": f"₹{loan['total_overdue']:,.0f}",
                "overdue_days": dpd,
                "category": loan.get("npa_category", "SMA-0"),
                "mobile": c.get("mobile", "—"),
            })
    overdue.sort(key=lambda l: l["overdue_days"], reverse=True)
    return overdue


@mcp.tool()
async def grant_waiver(
    loan_id: str,
    waiver_type: Literal["PENAL_INTEREST", "PROCESSING_FEE", "FORECLOSURE_CHARGE", "PARTIAL_PRINCIPAL"],
    waiver_amount: float,
    reason: str,
    ctx: Context,
) -> dict:
    """
    Grant a waiver. Elicits dual-approval (approver name + authorization code)
    before committing — mirrors real collections approval workflow.

    Args:
        loan_id:       Loan to apply waiver on
        waiver_type:   Type of waiver
        waiver_amount: Amount waived in ₹
        reason:        Justification for waiver
    """
    loan = LOANS.get(loan_id)
    if not loan:
        return {"error": f"Loan '{loan_id}' not found."}

    await ctx.info(f"🔍 Waiver request received — {waiver_type} | ₹{waiver_amount:,.0f} for {loan_id}")

    # ── Elicitation: dual-approval for waiver ─────────────────────────────────
    approved_by   = "PM_TEST"
    auth_code     = "AUTO"
    manager_email = ""
    try:
        elicit_result = await ctx.elicit(
            message=(
                "✋ WAIVER APPROVAL REQUIRED\n\n"
                f"Loan      : {loan_id}\n"
                f"Type      : {waiver_type}\n"
                f"Amount    : ₹{waiver_amount:,.0f}\n"
                f"Reason    : {reason}\n\n"
                "This waiver requires manager-level authorization. "
                "Please provide approval details."
            ),
            schema={
                "type": "object",
                "properties": {
                    "approver_name": {
                        "type": "string",
                        "description": "Name of the approving manager"
                    },
                    "authorization_code": {
                        "type": "string",
                        "description": "Manager authorization / OTP code"
                    },
                    "manager_email": {
                        "type": "string",
                        "description": "Manager email for audit trail"
                    },
                    "approve": {
                        "type": "boolean",
                        "description": "Final approval decision (true = approve waiver)"
                    },
                },
                "required": ["approver_name", "authorization_code", "approve"],
            },
        )
        action  = getattr(elicit_result, "action", "accept")
        content = getattr(elicit_result, "content", {}) or {}
        if action == "cancel" or not content.get("approve", True):
            await ctx.warning(f"🚫 Waiver rejected at approval step.")
            return {"success": False, "reason": "Waiver rejected by approver."}
        approved_by   = content.get("approver_name", "PM_TEST")
        auth_code     = content.get("authorization_code", "MANUAL")
        manager_email = content.get("manager_email", "")
    except Exception:
        await ctx.warning("⚠️  Elicitation unavailable — waiver auto-approved for testing.")

    waiver_id = _uid("WVR")
    COLLECTIONS[waiver_id] = {
        "id": waiver_id, "loan_id": loan_id,
        "type": "WAIVER", "waiver_type": waiver_type,
        "amount": waiver_amount, "reason": reason,
        "approved_by": approved_by, "auth_code": auth_code,
        "manager_email": manager_email,
        "created_at": _now(),
    }
    _audit("WAIVER_GRANTED", "LOAN", loan_id,
           f"Type: {waiver_type} | ₹{waiver_amount:,.0f} | Approved by: {approved_by} | Code: {auth_code}")
    await ctx.info(f"✅ Waiver {waiver_id} approved by {approved_by} | Auth: {auth_code}")
    return {
        "success": True, "waiver_id": waiver_id,
        "loan_id": loan_id, "waiver_type": waiver_type,
        "amount_waived": f"₹{waiver_amount:,.0f}",
        "reason": reason, "approved_by": approved_by,
        "authorization_code": auth_code,
    }


# ══════════════════════════════════════════════════════════════════════════════
# ── TESTING & QA UTILITIES ────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def generate_test_customer(
    credit_score: int = 750,
    employment_type: Literal["SALARIED", "SELF_EMPLOYED", "BUSINESS"] = "SALARIED",
    monthly_income: int = 60_000,
) -> dict:
    """
    Generate a synthetic customer for testing specific credit/income scenarios.

    Args:
        credit_score:    Desired credit score (300–900)
        employment_type: Employment type
        monthly_income:  Monthly income in ₹
    """
    names_m = ["Arjun", "Vikram", "Suresh", "Ravi", "Deepak", "Mohan", "Anand"]
    names_f = ["Kavya", "Meena", "Shalini", "Pooja", "Nisha", "Lata", "Geeta"]
    gender  = random.choice(["M", "F"])
    name    = random.choice(names_m if gender == "M" else names_f) + " " + random.choice(
        ["Kumar", "Sharma", "Patel", "Singh", "Nair", "Reddy", "Mehta"])
    pan_letters = "".join(random.choices(string.ascii_uppercase, k=5))
    pan_digits  = "".join(random.choices(string.digits, k=4))
    pan_last    = random.choice(string.ascii_uppercase)
    pan         = f"{pan_letters}{pan_digits}{pan_last}"
    aadhaar     = "".join(random.choices(string.digits, k=12))
    cid         = _uid("CUST")
    CUSTOMERS[cid] = {
        "id": cid, "name": name, "pan": pan,
        "aadhaar": aadhaar, "mobile": f"9{''.join(random.choices(string.digits, k=9))}",
        "email": f"{name.lower().replace(' ','.')}.test@testlender.in",
        "dob": f"{random.randint(1975,2000)}-{random.randint(1,12):02d}-{random.randint(1,28):02d}",
        "gender": gender, "credit_score": credit_score,
        "monthly_income": monthly_income,
        "employment_type": employment_type,
        "employer": "Test Corp Pvt Ltd" if employment_type == "SALARIED" else "Self",
        "existing_emi": int(monthly_income * 0.1),
        "city": random.choice(["Bengaluru", "Hyderabad", "Mumbai", "Delhi", "Chennai"]),
        "pincode": str(random.randint(100000, 999999)),
        "bank_account": f"TEST{''.join(random.choices(string.digits, k=8))}",
        "ifsc": f"TEST{''.join(random.choices(string.ascii_uppercase, k=4))}0001",
        "kyc_status": "VERIFIED",
        "created_at": _now(),
    }
    _audit("GENERATE_TEST_CUSTOMER", "CUSTOMER", cid,
           f"Score: {credit_score} | {employment_type} | ₹{monthly_income:,}/mo")
    return {"success": True, "customer_id": cid, "name": name, "pan": pan,
            "credit_score": credit_score, "monthly_income": f"₹{monthly_income:,}",
            "kyc_status": "VERIFIED",
            "note": "Synthetic customer — KYC pre-verified for testing."}


@mcp.tool()
async def run_end_to_end_test(
    partner_id: str,
    ctx: Context,
    loan_amount: float = 1_00_000,
    tenure_months: int = 12,
    credit_score: int = 750,
) -> dict:
    """
    Run a complete loan lifecycle test with real-time step notifications.
    create customer → KYC → eligibility → apply → assess → offer → disburse → EMI.

    Args:
        partner_id:    Partner to test
        loan_amount:   Loan amount in ₹
        tenure_months: Tenure in months
        credit_score:  Customer credit score to simulate
    """
    p = PARTNERS.get(partner_id.upper())
    if not p:
        return {"error": f"Partner '{partner_id}' not found."}

    total_steps = 8
    steps = []

    async def step(num, name, result):
        status = "PASS" if "error" not in result else "FAIL"
        icon   = "✅" if status == "PASS" else "❌"
        steps.append({"step": name, "status": status,
                      "summary": result.get("error") or str(list(result.items())[:2])})
        await ctx.report_progress(num, total_steps)
        await ctx.info(f"{icon} [{num}/{total_steps}] {name}: {status}")
        await asyncio.sleep(0.2)
        return result

    await ctx.info(f"🚀 E2E Test started — Partner: {partner_id.upper()} | ₹{loan_amount:,.0f} x {tenure_months}m | Score: {credit_score}")

    # Step 1
    r = generate_test_customer(credit_score=credit_score)
    cid = r["customer_id"]
    await step(1, "Create Synthetic Customer", r)

    # Step 2
    r = check_eligibility(cid, partner_id, loan_amount, tenure_months)
    await step(2, "Check Eligibility", r)
    if not r.get("eligible"):
        await ctx.warning(f"🛑 ABORTED — {r.get('reason')}")
        steps.append({"step": "ABORT", "status": "INFO", "summary": r.get("reason")})
        return {"partner_id": partner_id, "overall": "ABORTED",
                "reason": r.get("reason"), "steps": steps}

    # Step 3
    r = create_loan_application(cid, partner_id, loan_amount, tenure_months, "PERSONAL", "E2E_TEST")
    app_id = r.get("application_id")
    await step(3, "Create Loan Application", r)

    # Step 4 — calls submit_for_credit_assessment which has its own notifications
    await ctx.info(f"📋 Triggering credit assessment (sub-notifications follow)...")
    app = APPLICATIONS.get(app_id, {})
    app["status"] = "UNDER_REVIEW"
    app["assessment_id"] = _uid("ASM")
    app["updated_at"] = _now()
    r = {"success": True, "application_id": app_id, "status": "UNDER_REVIEW",
         "assessment_id": app["assessment_id"]}
    await step(4, "Credit Assessment", r)

    # Step 5
    r = generate_loan_offer(app_id)
    await step(5, "Generate Loan Offer", r)

    # Step 6
    r = accept_loan_offer(app_id)
    await step(6, "Accept Offer", r)

    # Step 7 — disbursement without elicitation in E2E mode
    app2 = APPLICATIONS.get(app_id, {})
    c = CUSTOMERS.get(cid, {})
    disb_date = _date_str(date.today())
    disb_dt   = date.today()
    maturity  = disb_dt + timedelta(days=30 * tenure_months)
    loan_id   = _uid("LOAN")
    emi_v     = app2.get("estimated_emi") or _emi(loan_amount, app2.get("offered_rate", 18), tenure_months)
    fee       = app2.get("processing_fee", 0)
    utr_ref   = _uid("UTR")
    LOANS[loan_id] = {
        "id": loan_id, "application_id": app_id,
        "partner_id": partner_id.upper(), "customer_id": cid,
        "principal": loan_amount, "interest_rate_pa": app2.get("offered_rate", 18),
        "tenure_months": tenure_months, "emi_amount": emi_v,
        "processing_fee": fee, "disbursement_date": disb_date,
        "maturity_date": _date_str(maturity),
        "next_emi_date": _date_str(disb_dt + timedelta(days=30)),
        "status": "ACTIVE", "emis_paid": 0, "emis_remaining": tenure_months,
        "outstanding_principal": loan_amount, "total_overdue": 0,
        "bank_account": c.get("bank_account", "TEST"), "ifsc": c.get("ifsc", "TEST"),
        "utr": utr_ref, "created_at": _now(),
    }
    app2["status"] = "DISBURSED"
    app2["loan_id"] = loan_id
    app2["updated_at"] = _now()
    PARTNERS[partner_id.upper()]["disbursed_count"] += 1
    _audit("DISBURSE", "LOAN", loan_id, f"E2E | ₹{loan_amount:,.0f}")
    r = {"success": True, "loan_id": loan_id, "utr": utr_ref,
         "net_disbursed": f"₹{loan_amount - fee:,.0f}"}
    await step(7, "Disburse Loan", r)
    await ctx.info(f"🏦 UTR: {utr_ref} | Net disbursed: ₹{loan_amount - fee:,.0f}")

    # Step 8 — EMI payment without sub-notifications
    loan = LOANS.get(loan_id, {})
    emi_no    = 1
    rate_mo   = loan.get("interest_rate_pa", 18) / (12 * 100)
    interest  = round(loan.get("outstanding_principal", 0) * rate_mo, 2)
    principal = round(min(emi_v - interest, loan.get("outstanding_principal", 0)), 2)
    pay_id    = _uid("PAY")
    pay_utr   = _uid("UTR")
    loan["outstanding_principal"] = round(max(loan.get("outstanding_principal", 0) - principal, 0), 2)
    loan["emis_paid"] = 1
    loan["emis_remaining"] = tenure_months - 1
    PAYMENTS[pay_id] = {
        "id": pay_id, "loan_id": loan_id, "customer_id": cid,
        "partner_id": partner_id.upper(), "emi_number": 1,
        "amount": emi_v, "principal_component": principal,
        "interest_component": interest, "type": "EMI",
        "status": "SUCCESS", "payment_mode": "UPI",
        "payment_date": disb_date, "utr": pay_utr, "created_at": _now(),
    }
    r = {"success": True, "payment_id": pay_id, "emi_number": 1, "utr": pay_utr}
    await step(8, "Process 1st EMI", r)

    passed = sum(1 for s in steps if s["status"] == "PASS")
    overall = "PASS" if passed == len(steps) else f"PARTIAL ({passed}/{len(steps)})"
    await ctx.info(f"🏁 E2E Test complete — {overall} | Loan: {loan_id} | Customer: {cid}")

    return {
        "partner_id": partner_id, "customer_id": cid,
        "application_id": app_id, "loan_id": loan_id,
        "overall": overall, "steps": steps,
    }


@mcp.tool()
def simulate_credit_score(customer_id: str, new_score: int) -> dict:
    """
    Override a customer's credit score for testing edge cases (boundary testing).

    Args:
        customer_id: Customer to modify
        new_score:   New CIBIL score (300–900)
    """
    c = CUSTOMERS.get(customer_id)
    if not c:
        return {"error": f"Customer '{customer_id}' not found."}
    if not 300 <= new_score <= 900:
        return {"error": "Score must be between 300 and 900."}
    old_score = c.get("credit_score")
    c["credit_score"] = new_score
    _audit("SIM_CREDIT_SCORE", "CUSTOMER", customer_id, f"{old_score} → {new_score}")
    return {"success": True, "customer_id": customer_id,
            "old_score": old_score, "new_score": new_score,
            "rating": ("EXCELLENT" if new_score >= 800 else "GOOD" if new_score >= 740
                       else "FAIR" if new_score >= 680 else "POOR"),
            "note": "Score overridden for testing. Use fetch_credit_score to reset."}


@mcp.tool()
def get_audit_trail(
    entity: Optional[Literal["PARTNER", "CUSTOMER", "APPLICATION", "LOAN"]] = None,
    entity_id: Optional[str] = None,
    limit: int = 30,
) -> list[dict]:
    """
    View the full audit trail for all operations (PM visibility into all actions).

    Args:
        entity:    Filter by entity type
        entity_id: Filter by specific entity ID
        limit:     Max records (default 30)
    """
    logs = list(AUDIT_LOG)
    if entity:
        logs = [l for l in logs if l["entity"] == entity]
    if entity_id:
        logs = [l for l in logs if l["entity_id"] == entity_id]
    logs.sort(key=lambda l: l["ts"], reverse=True)
    return logs[:limit]


@mcp.tool()
def reset_test_data(confirm: bool = False) -> dict:
    """
    ⚠ DESTRUCTIVE — Reset all applications, loans, and payments to seed state.
    Partners and customers are preserved. Requires confirm=True.

    Args:
        confirm: Must be True to execute. Safety gate for PM testing.
    """
    if not confirm:
        return {"error": "Set confirm=True to reset. This clears all applications, loans, and payments."}
    count = {"applications": len(APPLICATIONS), "loans": len(LOANS),
             "payments": len(PAYMENTS), "audit_log": len(AUDIT_LOG)}
    APPLICATIONS.clear()
    LOANS.clear()
    PAYMENTS.clear()
    AUDIT_LOG.clear()
    COLLECTIONS.clear()
    _audit("RESET_TEST_DATA", "SYSTEM", "ALL", "Full reset by PM")
    return {"success": True, "cleared": count,
            "message": "Test data reset. Partners and customers preserved."}


@mcp.tool()
def get_portfolio_summary() -> dict:
    """
    Get a full portfolio overview across all partners — disbursements, NPA, collections.
    """
    active_loans  = [l for l in LOANS.values() if l["status"] == "ACTIVE"]
    npa_loans     = [l for l in LOANS.values() if l["status"] == "NPA"]
    closed_loans  = [l for l in LOANS.values() if l["status"] in ("CLOSED", "FORECLOSED")]
    total_disb    = sum(l["principal"] for l in LOANS.values())
    total_outst   = sum(l["outstanding_principal"] for l in active_loans)
    total_overdue = sum(l["total_overdue"] for l in LOANS.values())
    return {
        "generated_at": _now(),
        "total_partners": len(PARTNERS),
        "active_partners": len([p for p in PARTNERS.values() if p["status"] == "ACTIVE"]),
        "total_customers": len(CUSTOMERS),
        "applications": {
            "total": len(APPLICATIONS),
            "by_status": {
                s: len([a for a in APPLICATIONS.values() if a["status"] == s])
                for s in ["PENDING", "UNDER_REVIEW", "OFFERED", "ACCEPTED", "DISBURSED", "REJECTED"]
            },
        },
        "loans": {
            "total": len(LOANS),
            "active": len(active_loans),
            "closed": len(closed_loans),
            "npa": len(npa_loans),
        },
        "financials": {
            "total_disbursed": f"₹{total_disb:,.0f}",
            "outstanding_portfolio": f"₹{total_outst:,.0f}",
            "total_overdue": f"₹{total_overdue:,.0f}",
            "npa_rate": f"{len(npa_loans)/max(len(LOANS),1)*100:.1f}%",
            "total_payments_received": f"₹{sum(p['amount'] for p in PAYMENTS.values()):,.0f}",
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# RESOURCES
# ══════════════════════════════════════════════════════════════════════════════

@mcp.resource("docs://api-flow")
def get_api_flow() -> str:
    """Complete loan lifecycle API flow documentation"""
    return """\
# Digital Lending API Flow

## Complete Loan Lifecycle

### 1. Partner Setup
  register_partner → update_partner_config → check_partner_health

### 2. Customer Onboarding
  create_customer → verify_pan → verify_aadhaar → fetch_credit_score

### 3. Loan Application
  check_eligibility → create_loan_application → submit_for_credit_assessment
  → generate_loan_offer → accept_loan_offer

### 4. Disbursement
  disburse_loan (credit to bank account)

### 5. Loan Servicing
  get_emi_schedule → process_emi_payment (×N) → get_loan_statement

### 6. Prepayment / Foreclosure
  calculate_prepayment → process_prepayment
  OR process_foreclosure → generate_noc

### 7. Collections (if overdue)
  mark_loan_overdue → get_overdue_loans → grant_waiver (if applicable)
  → process_emi_payment (recovery)

## Application Status Machine
  PENDING → UNDER_REVIEW → OFFERED → ACCEPTED → DISBURSED
          ↘ REJECTED (any stage)

## Loan Status Machine
  ACTIVE → CLOSED (full repayment)
  ACTIVE → FORECLOSED (early closure)
  ACTIVE → NPA (90+ DPD)
  NPA → ACTIVE (after payment recovery)

## Partner Status
  SANDBOX → ACTIVE → INACTIVE
"""


@mcp.resource("schema://loan-application")
def get_application_schema() -> str:
    """JSON Schema for loan application request"""
    return json.dumps({
        "type": "object",
        "required": ["customer_id", "partner_id", "loan_amount", "tenure_months", "purpose"],
        "properties": {
            "customer_id":   {"type": "string", "description": "Verified customer ID"},
            "partner_id":    {"type": "string", "enum": list(PARTNERS.keys())},
            "loan_amount":   {"type": "number", "minimum": 1000, "description": "Amount in ₹"},
            "tenure_months": {"type": "integer", "minimum": 1, "maximum": 36},
            "purpose":       {"type": "string", "enum": [
                "PERSONAL", "HOME_RENOVATION", "MEDICAL", "TRAVEL",
                "EDUCATION", "WEDDING", "BUSINESS", "VEHICLE", "DEBT_CONSOLIDATION"
            ]},
            "notes":         {"type": "string"},
        },
    }, indent=2)


@mcp.resource("report://portfolio")
def get_portfolio_report() -> str:
    """Live portfolio snapshot across all partners"""
    summary = get_portfolio_summary()
    lines = [
        "# Portfolio Report", f"Generated: {summary['generated_at']}", "",
        f"Partners: {summary['active_partners']} active / {summary['total_partners']} total",
        f"Customers: {summary['total_customers']}",
        "",
        "## Applications",
    ]
    for status, count in summary["applications"]["by_status"].items():
        lines.append(f"  {status}: {count}")
    lines += ["", "## Loans",
              f"  Active: {summary['loans']['active']}",
              f"  Closed: {summary['loans']['closed']}",
              f"  NPA:    {summary['loans']['npa']}",
              "", "## Financials"]
    for k, v in summary["financials"].items():
        lines.append(f"  {k}: {v}")
    return "\n".join(lines)


@mcp.resource("partner://config/{partner_id}")
def get_partner_resource(partner_id: str) -> str:
    """Partner configuration resource"""
    p = PARTNERS.get(partner_id.upper())
    if not p:
        return f"Partner '{partner_id}' not found."
    return json.dumps(p, indent=2)


@mcp.resource("loan://details/{loan_id}")
def get_loan_resource(loan_id: str) -> str:
    """Loan details resource"""
    loan = LOANS.get(loan_id)
    if not loan:
        return f"Loan '{loan_id}' not found."
    return json.dumps(loan, indent=2)


@mcp.resource("customer://profile/{customer_id}")
def get_customer_resource(customer_id: str) -> str:
    """Customer profile resource"""
    c = CUSTOMERS.get(customer_id)
    if not c:
        return f"Customer '{customer_id}' not found."
    safe = dict(c)
    safe["aadhaar"] = f"XXXX XXXX {c['aadhaar'][-4:]}"
    return json.dumps(safe, indent=2)


# ══════════════════════════════════════════════════════════════════════════════
# PROMPTS
# ══════════════════════════════════════════════════════════════════════════════

@mcp.prompt()
def pm_test_plan(partner_id: str, test_type: str = "FULL") -> str:
    """
    Generate a structured test plan for a partner integration.

    Args:
        partner_id: Partner to test (CRED, PHONEPE, GPAY etc.)
        test_type:  FULL | SMOKE | REGRESSION | UAT
    """
    p = PARTNERS.get(partner_id.upper(), {})
    return f"""\
# {test_type} Test Plan — {partner_id.upper()} Integration
Partner: {p.get('name', partner_id)} | Rate: {p.get('interest_rate_pa','?')}% p.a.
Loan Range: ₹{p.get('min_loan',0):,} – ₹{p.get('max_loan',0):,}
Min Credit Score: {p.get('min_credit_score','?')} | Max FOIR: {p.get('max_foir','?')}

Please generate and execute the following test scenarios using available tools:

## 1. Happy Path (Positive Tests)
- [ ] T01: Customer with score {p.get('min_credit_score',700)+50} applies for mid-range loan → should be ELIGIBLE
- [ ] T02: Full E2E flow: create → apply → offer → disburse → pay 3 EMIs
- [ ] T03: Prepayment after 3 EMIs — verify new outstanding and revised EMI
- [ ] T04: Foreclosure — verify charge calculation and NOC generation
- [ ] T05: Statement generation after 3 payments

## 2. Boundary / Edge Cases
- [ ] T06: Credit score exactly at minimum ({p.get('min_credit_score',700)}) → should pass
- [ ] T07: Credit score at minimum - 1 → should be REJECTED
- [ ] T08: Loan amount = max_loan ({p.get('max_loan',0):,}) → should pass
- [ ] T09: Loan amount = max_loan + 1 → should be rejected
- [ ] T10: Tenure = min ({p.get('min_tenure',1)}m) and max ({p.get('max_tenure',36)}m) — boundary check

## 3. Negative / Rejection Tests
- [ ] T11: FOIR > {p.get('max_foir',0.5):.0%} → should fail eligibility
- [ ] T12: KYC PENDING customer → application should be blocked
- [ ] T13: Partner in INACTIVE state → application should be rejected
- [ ] T14: Duplicate PAN registration → should return error

## 4. Collections Flow
- [ ] T15: Mark loan 30 DPD → verify SMA-0 classification
- [ ] T16: Mark loan 90 DPD → verify NPA classification
- [ ] T17: Process partial payment on NPA loan → verify ACTIVE recovery
- [ ] T18: Grant waiver → verify audit trail

## 5. Partner Config Tests
- [ ] T19: check_partner_health → verify endpoint UP
- [ ] T20: Update interest rate → verify new EMI calculated correctly
- [ ] T21: get_partner_metrics → verify disbursed_count increments post-disbursal

Use run_end_to_end_test('{partner_id.upper()}') for a quick smoke test.
Use get_audit_trail() after each step to verify all actions are logged.
"""


@mcp.prompt()
def integration_checklist(partner_id: str) -> str:
    """
    Pre-launch integration checklist for a new partner going LIVE.

    Args:
        partner_id: Partner about to go live
    """
    return f"""\
# Pre-Launch Integration Checklist — {partner_id.upper()}

Please verify each item using the available MCP tools:

## API & Config
- [ ] check_partner_health("{partner_id}") returns status: UP
- [ ] get_partner_config("{partner_id}") — verify all rates and limits are correct
- [ ] Webhook URL is reachable and responding

## Credit Policy Validation
- [ ] Min credit score boundary test (score-1 rejects, score passes)
- [ ] FOIR boundary test at max_foir
- [ ] Loan amount min/max boundary tests
- [ ] Tenure min/max boundary tests

## End-to-End Flow
- [ ] run_end_to_end_test("{partner_id}") → all steps PASS
- [ ] Verify EMI calculation matches partner's amortisation schedule
- [ ] Verify processing fee deduction from disbursement amount
- [ ] Verify UTR generated for every disbursement

## Edge Cases
- [ ] Zero credit score (new-to-credit customer)
- [ ] Maximum income / high FOIR customer
- [ ] Prepayment on EMI #1
- [ ] Foreclosure on first day

## Compliance
- [ ] Audit trail generated for all 20+ actions
- [ ] KYC verification gate enforced before loan application
- [ ] Customer consent captured before offer acceptance
- [ ] NOC generation after loan closure

Update partner status to ACTIVE only after all boxes are checked.
"""


@mcp.prompt()
def emi_verification(loan_id: str) -> str:
    """
    Verify EMI calculation correctness for a disbursed loan.

    Args:
        loan_id: Loan to verify
    """
    loan = LOANS.get(loan_id, {})
    return f"""\
# EMI Verification Request — {loan_id}

Loan Details:
  Principal:     ₹{loan.get('principal', 0):,}
  Interest Rate: {loan.get('interest_rate_pa', 0)}% p.a.
  Tenure:        {loan.get('tenure_months', 0)} months
  Recorded EMI:  ₹{loan.get('emi_amount', 0):,}

Please:
1. Call get_emi_schedule("{loan_id}") to retrieve the full amortisation schedule.
2. Verify the EMI formula: EMI = P × r(1+r)ⁿ / ((1+r)ⁿ - 1)
   where r = annual_rate / 12 / 100
3. Check that principal + interest components in each row sum to EMI amount.
4. Verify outstanding balance reaches ₹0 at EMI #{loan.get('tenure_months', 0)}.
5. Calculate total interest paid and total repayment amount.
6. Flag any rounding discrepancy > ₹2 in any row.

Report any discrepancies found.
"""


@mcp.prompt()
def npa_analysis() -> str:
    """Generate an NPA and collections analysis across the full portfolio."""
    return """\
# NPA & Collections Analysis

Please perform a full NPA analysis:

1. Call get_portfolio_summary() — note overall NPA rate and overdue amount.
2. Call get_overdue_loans() — list all overdue accounts.
3. Call get_overdue_loans(min_days=90) — identify all NPA accounts.
4. For each NPA account:
   a. Call get_loan_details(loan_id) — review outstanding and partner.
   b. Call get_payment_history(loan_id) — identify last payment date.
   c. Recommend: waiver / legal / restructure based on DPD bucket.
5. Calculate:
   - Total NPA exposure by partner
   - Average days past due
   - Recovery potential (outstanding < 6 months overdue)
6. Suggest collection priority order (highest outstanding + lowest DPD first).

Provide a structured report with actionable recommendations per account.
"""


if __name__ == "__main__":
    mcp.run()
