"""
AgentCare — Streamlit UI, wired to the FastAPI backend.

Layout is a three-region app shell:
  • left  — sidebar navigation (role-aware: patient / staff / admin)
  • main  — the active section's content
  • right — a contextual panel (guidance, legends, safety boundary)

Run the backend first:
    uvicorn app.api.main:app --reload
Then run this UI (from the project root):
    streamlit run app/ui/streamlit_app.py

Every value shown comes from a live API call (app/ui/api_client.py). Read-only
data is rendered as HTML-escaped cards; all interaction uses native Streamlit
widgets so the UI degrades gracefully across Streamlit versions.
"""
import os
import sys
import html
import secrets
from datetime import datetime

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import streamlit as st
from app.ui import api_client as api

# Server-side session store so a browser refresh doesn't drop the login. Keyed by
# an opaque id kept in the URL (?sid=...) — never the JWT, which stays server-side.
# st.cache_resource is the one store Streamlit guarantees to persist across script
# reruns AND page refreshes for the life of the server process. A plain module
# global does NOT reliably survive, which is why refresh appeared to log you out.
@st.cache_resource
def _session_store() -> dict:
    return {}

st.set_page_config(
    page_title="AgentCare",
    page_icon="🩺",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Role -> ordered navigation (label, icon)
NAV = {
    "patient": [("Overview", "🏠"), ("New request", "➕"), ("My requests", "📨"),
                ("Appointments", "📅"), ("Documents", "📄"), ("Reminders", "🔔"),
                ("Privacy", "🔒")],
    "staff":   [("Overview", "🏠"), ("Escalations", "⚠️"), ("Appointments", "📅"),
                ("Analytics", "📊"), ("Workflows", "🗂️"), ("Audit trail", "🧾")],
    "admin":   [("Overview", "🏠"), ("People", "👥"), ("Escalations", "⚠️"),
                ("Appointments", "📅"), ("Analytics", "📊"), ("Workflows", "🗂️"),
                ("Audit trail", "🧾"), ("Departments", "🏥")],
}


# ── DESIGN SYSTEM ────────────────────────────────────────────────────────────
def inject_css():
    st.markdown(
        """
<style>
.ac-hint{color:var(--muted, #6b7280);font-size:.82rem;}
:root{
  --teal-700:#0f766e; --teal-600:#0d9488; --teal-500:#14b8a6;
  --ink:#122421; --muted:#5f716c; --line:#e4ece9;
  --bg:#f4f8f7; --card:#ffffff;
  --green:#0f9d6b; --green-bg:#e8f7f0;
  --amber:#b7791f; --amber-bg:#fdf3e3;
  --red:#c53434;   --red-bg:#fdecec;
  --blue:#2563a8;  --blue-bg:#e9f1fb;
  --gray:#5f716c;  --gray-bg:#eef2f1;
  --radius:16px; --shadow:0 1px 2px rgba(18,36,33,.05),0 8px 24px rgba(18,36,33,.06);
}
#MainMenu, footer, [data-testid="stStatusWidget"]{visibility:hidden;}
[data-testid="stHeader"]{background:transparent; height:0;}
.stApp{background:
  radial-gradient(900px 480px at 92% -8%, #e2f2ee 0%, rgba(226,242,238,0) 60%),
  radial-gradient(760px 420px at 20% 2%, #eaf3fb 0%, rgba(234,243,251,0) 55%),
  var(--bg);}
.block-container{padding-top:1.6rem; padding-bottom:3rem; max-width:1320px;}
h1,h2,h3,h4{color:var(--ink); letter-spacing:-.01em;}

/* ---- Buttons ---- */
.stButton>button, .stFormSubmitButton>button, .stDownloadButton>button{
  border-radius:11px; font-weight:600; border:1px solid var(--line);
  transition:transform .05s ease, box-shadow .2s ease, background .2s ease;}
.stButton>button:active, .stFormSubmitButton>button:active{transform:translateY(1px);}
.stButton>button[kind="primary"], .stFormSubmitButton>button[kind="primary"]{
  background:linear-gradient(135deg,var(--teal-700),var(--teal-500));
  border:none; color:#fff; box-shadow:0 6px 16px rgba(13,148,136,.28);}
.stButton>button[kind="primary"]:hover, .stFormSubmitButton>button[kind="primary"]:hover{
  box-shadow:0 8px 22px rgba(13,148,136,.36);}

[data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea{border-radius:11px !important;}
[data-testid="stFileUploaderDropzone"]{border-radius:12px; background:#f7fbfa;}
[data-testid="stAlert"]{border-radius:12px;}

/* ---- Sidebar: dark app-shell ---- */
section[data-testid="stSidebar"]{background:linear-gradient(185deg,#0f403a 0%,#0b2b28 100%);
  border-right:1px solid rgba(255,255,255,.06);}
section[data-testid="stSidebar"] .block-container{padding-top:1.2rem;}
section[data-testid="stSidebar"] *{color:#dbeee9;}
section[data-testid="stSidebar"] hr{border-color:rgba(255,255,255,.10);}
section[data-testid="stSidebar"] .stButton>button{
  background:transparent; border:1px solid transparent; color:#cfe3de;
  justify-content:flex-start; text-align:left; font-weight:600; padding:8px 12px;}
section[data-testid="stSidebar"] .stButton>button:hover{
  background:rgba(255,255,255,.07); border-color:rgba(255,255,255,.09);}
section[data-testid="stSidebar"] .stButton>button[kind="primary"]{
  background:linear-gradient(135deg,var(--teal-500),var(--teal-600)); color:#fff;
  box-shadow:0 6px 16px rgba(13,148,136,.4);}
.sb-brand{display:flex;align-items:center;gap:11px;margin:2px 4px 18px;}
.sb-brand .mk{width:38px;height:38px;border-radius:11px;display:flex;align-items:center;
  justify-content:center;font-size:21px;background:linear-gradient(135deg,var(--teal-500),var(--teal-600));
  box-shadow:0 6px 14px rgba(13,148,136,.4);}
.sb-brand .nm{font-weight:800;font-size:1.15rem;color:#fff;letter-spacing:-.01em;line-height:1;}
.sb-brand .tg{font-size:.68rem;color:#8fb8b0;text-transform:uppercase;letter-spacing:.09em;}
.sb-user{display:flex;align-items:center;gap:11px;background:rgba(255,255,255,.06);
  border:1px solid rgba(255,255,255,.08);border-radius:13px;padding:10px 12px;margin:0 2px 16px;}
.sb-user .av{width:36px;height:36px;border-radius:50%;flex:none;display:flex;align-items:center;
  justify-content:center;font-weight:800;color:#0b2b28;background:#a7ded3;font-size:.95rem;}
.sb-user .nm{font-weight:700;color:#fff;font-size:.92rem;line-height:1.15;}
.sb-user .rl{font-size:.72rem;color:#8fb8b0;text-transform:uppercase;letter-spacing:.06em;}
.sb-cap{font-size:.68rem;color:#7ea79f;text-transform:uppercase;letter-spacing:.09em;
  margin:6px 6px 6px;font-weight:700;}
.sb-conn{display:flex;align-items:center;gap:8px;font-size:.78rem;color:#a7c7c0;margin:10px 4px 2px;}
.sb-conn .d{width:8px;height:8px;border-radius:50%;}
.sb-conn .d.ok{background:#34d399;box-shadow:0 0 0 3px rgba(52,211,153,.2);}
.sb-conn .d.no{background:#f87171;box-shadow:0 0 0 3px rgba(248,113,113,.2);}

/* ---- Breadcrumb / page head ---- */
.crumb{color:var(--muted);font-size:.82rem;font-weight:600;margin:2px 0 2px;}
.crumb b{color:var(--teal-700);}
.page-h{font-size:1.6rem;font-weight:800;color:var(--ink);margin:0 0 4px;letter-spacing:-.02em;}
.page-s{color:var(--muted);font-size:.9rem;margin:0 0 18px;}

/* ---- KPI stats ---- */
.ac-stats{display:grid;grid-template-columns:repeat(var(--cols,3),1fr);gap:14px;margin-bottom:18px;}
.ac-stat{background:var(--card);border:1px solid var(--line);border-radius:14px;
  padding:15px 17px;box-shadow:var(--shadow);}
.ac-stat .n{font-size:1.85rem;font-weight:800;color:var(--ink);line-height:1;}
.ac-stat .l{font-size:.76rem;color:var(--muted);margin-top:6px;text-transform:uppercase;
  letter-spacing:.05em;font-weight:700;display:flex;align-items:center;gap:6px;}

/* ---- List items ---- */
.ac-item{border:1px solid var(--line);border-radius:13px;padding:13px 15px;margin-bottom:10px;
  background:var(--card);display:flex;justify-content:space-between;align-items:flex-start;gap:14px;
  transition:border-color .15s ease, box-shadow .15s ease;}
.ac-item:hover{border-color:#cfe1dc;box-shadow:0 4px 14px rgba(18,36,33,.06);}
.ac-item .t{font-weight:650;color:var(--ink);font-size:.96rem;}
.ac-item .s{color:var(--muted);font-size:.84rem;margin-top:3px;line-height:1.5;}
.ac-item .r{text-align:right;flex:none;}

.pill{display:inline-block;padding:3px 11px;border-radius:999px;font-size:.71rem;
  font-weight:700;letter-spacing:.02em;white-space:nowrap;}
.pill.green{background:var(--green-bg);color:var(--green);}
.pill.amber{background:var(--amber-bg);color:var(--amber);}
.pill.red{background:var(--red-bg);color:var(--red);}
.pill.blue{background:var(--blue-bg);color:var(--blue);}
.pill.gray{background:var(--gray-bg);color:var(--gray);}

.ac-empty{text-align:center;color:var(--muted);padding:32px 16px;border:1px dashed var(--line);
  border-radius:13px;background:#fafcfb;}
.ac-empty .ico{font-size:1.7rem;opacity:.6;}
.ac-empty .m{margin-top:8px;font-size:.9rem;}
.ac-sec{display:flex;align-items:center;gap:9px;margin:6px 0 12px;font-weight:750;
  color:var(--ink);font-size:1.02rem;}
.ac-sec .dot{width:8px;height:8px;border-radius:3px;background:var(--teal-600);}

/* Agent trace */
.trace{border-left:2px solid var(--line);margin:4px 0 2px;padding-left:16px;}
.trace .step{position:relative;padding:5px 0;color:var(--ink);font-size:.88rem;line-height:1.5;}
.trace .step::before{content:"";position:absolute;left:-21px;top:9px;width:9px;height:9px;
  border-radius:50%;background:var(--teal-500);border:2px solid var(--card);box-shadow:0 0 0 2px var(--teal-500);}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.8rem;color:var(--muted);}

.callout{border-radius:12px;padding:12px 15px;font-size:.88rem;margin:4px 0 12px;line-height:1.5;}
.callout.warn{background:var(--amber-bg);border:1px solid #f2dcae;color:#7a5410;}

/* ---- Right panel ---- */
.rp-card{background:var(--card);border:1px solid var(--line);border-radius:14px;
  padding:15px 16px;margin-bottom:14px;box-shadow:var(--shadow);}
.rp-card h4{margin:0 0 9px;font-size:.74rem;text-transform:uppercase;letter-spacing:.07em;
  color:var(--muted);font-weight:800;}
.rp-card p{margin:0;color:var(--ink);font-size:.86rem;line-height:1.55;}
.rp-safety{background:linear-gradient(140deg,#0f766e,#0d9488);border:none;}
.rp-safety h4{color:rgba(255,255,255,.85);}
.rp-safety p{color:#eafaf6;}
.rp-step{display:flex;gap:10px;margin:9px 0;font-size:.85rem;color:var(--ink);line-height:1.4;}
.rp-step .num{flex:none;width:21px;height:21px;border-radius:7px;background:var(--teal-600);
  color:#fff;font-weight:700;font-size:.72rem;display:flex;align-items:center;justify-content:center;}
.rp-leg{display:flex;align-items:center;gap:9px;margin:7px 0;font-size:.83rem;color:var(--ink);}

/* Login */
.login-wrap{max-width:420px;margin:5vh auto 0;}
.login-mark{width:60px;height:60px;border-radius:17px;margin:0 auto 14px;display:flex;
  align-items:center;justify-content:center;font-size:30px;
  background:linear-gradient(135deg,var(--teal-700),var(--teal-500));
  box-shadow:0 10px 26px rgba(13,148,136,.35);}
.login-title{text-align:center;font-size:2rem;font-weight:800;margin:0;color:var(--ink);}
.login-sub{text-align:center;color:var(--muted);font-size:.95rem;margin:.2rem 0 0;}
.demo{background:#f3f8f6;border:1px solid var(--line);border-radius:12px;padding:12px 14px;
  font-size:.82rem;color:var(--muted);}
.demo b{color:var(--ink);}
.demo .row{display:flex;justify-content:space-between;padding:3px 0;}
</style>
""",
        unsafe_allow_html=True,
    )


# ── PRIMITIVES ───────────────────────────────────────────────────────────────
def esc(v) -> str:
    return html.escape("" if v is None else str(v))


def fmt_dt(iso, fallback="—"):
    if not iso:
        return fallback
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return dt.strftime("%b %d, %Y · %I:%M %p").replace(" 0", " ")
    except Exception:
        return str(iso)


_TONES = {
    "completed": "green", "booked": "green", "approved": "green",
    "sent": "green", "active": "green", "done": "green", "resolved": "green",
    "attended": "green",
    "confirmed": "blue", "rescheduled": "blue", "scheduled": "blue",
    "running": "blue", "in_progress": "blue",
    "escalated": "amber", "open": "amber", "pending": "amber", "sensitive": "amber",
    "awaiting_confirmation": "amber", "awaiting confirmation": "amber",
    "cancelled": "red", "rejected": "red", "failed": "red", "emergency": "red",
    "missed": "red", "no_show": "red",
}


def pill(text) -> str:
    tone = _TONES.get(str(text).lower(), "gray")
    return f'<span class="pill {tone}">{esc(str(text).replace("_", " ").upper())}</span>'


def stat(n, label, icon) -> str:
    return (f'<div class="ac-stat"><div class="n">{esc(n)}</div>'
            f'<div class="l">{icon} {esc(label)}</div></div>')


def kpis(items) -> str:
    cols = len(items)
    body = "".join(stat(n, l, i) for n, l, i in items)
    return f'<div class="ac-stats" style="--cols:{cols}">{body}</div>'


def empty(icon, msg) -> str:
    return f'<div class="ac-empty"><div class="ico">{icon}</div><div class="m">{esc(msg)}</div></div>'


def sec_header(title) -> str:
    return f'<div class="ac-sec"><span class="dot"></span>{esc(title)}</div>'


def page_head(crumb_role, section_label, subtitle):
    st.markdown(
        f'<div class="crumb"><b>{esc(crumb_role)}</b> &nbsp;/&nbsp; {esc(section_label)}</div>'
        f'<div class="page-h">{esc(section_label)}</div>'
        f'<div class="page-s">{esc(subtitle)}</div>',
        unsafe_allow_html=True)


def _safe(fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception:
        return False, {"detail": "Cannot reach the backend. Start it with: "
                                 "uvicorn app.api.main:app --reload"}


def _init_state():
    for k in ("token", "role", "name", "nav", "sid", "focus_esc"):
        st.session_state.setdefault(k, None)


def start_session(data):
    """Record a fresh login and pin it to an opaque id in the URL so a browser
    refresh restores it instead of bouncing back to the login page."""
    sid = secrets.token_urlsafe(16)
    _session_store()[sid] = {"token": data["access_token"], "role": data["role"],
                      "name": data["name"]}
    st.session_state.update(token=data["access_token"], role=data["role"],
                            name=data["name"], nav="Overview", sid=sid)
    st.query_params["sid"] = sid


def restore_session():
    """On a fresh page load (refresh), rehydrate the login from the URL's sid."""
    if st.session_state.get("token"):
        return
    sid = st.query_params.get("sid")
    if sid and sid in _session_store():
        s = _session_store()[sid]
        st.session_state.update(token=s["token"], role=s["role"],
                                name=s["name"], sid=sid)
        if st.session_state.get("nav") is None:
            st.session_state.nav = "Overview"


def logout():
    sid = st.session_state.get("sid")
    if sid:
        _session_store().pop(sid, None)
    st.query_params.clear()
    for k in ("token", "role", "name", "nav", "sid", "focus_esc"):
        st.session_state[k] = None


def go(section):
    st.session_state.nav = section
    st.rerun()


# ── DATA LOADERS ─────────────────────────────────────────────────────────────
def load_patient(token):
    oa, a = _safe(api.my_appointments, token)
    od, d = _safe(api.my_documents, token)
    orr, r = _safe(api.my_reminders, token)
    oe, e = _safe(api.my_escalations, token)
    oc, cs = _safe(api.my_consents, token)
    return {
        "ok": bool(oa and od and orr),
        "appts": a if oa and isinstance(a, list) else [],
        "docs": d if od and isinstance(d, list) else [],
        "rems": r if orr and isinstance(r, list) else [],
        "escs": e if oe and isinstance(e, list) else [],
        "consents": cs if oc and isinstance(cs, list) else [],
    }


def load_staff(token, role):
    oe, e = _safe(api.list_escalations, token, status="open")
    ow, w = _safe(api.list_workflows, token)
    oau, au = _safe(api.audit_trail, token, limit=100)
    oap, ap = _safe(api.list_appointments, token, status="awaiting_confirmation")
    oup, up = _safe(api.list_appointments, token, status="upcoming")
    oan, an = _safe(api.analytics, token)
    data = {
        "ok": bool(oe and ow and oau),
        "escs": e if oe and isinstance(e, list) else [],
        "wfs": w if ow and isinstance(w, list) else [],
        "audit": au if oau and isinstance(au, list) else [],
        "appts": ap if oap and isinstance(ap, list) else [],
        "upcoming": up if oup and isinstance(up, list) else [],
        "analytics": an if oan and isinstance(an, dict) else {},
        "depts": [],
        "users": [],
    }
    if role == "admin":
        odp, dp = _safe(api.list_departments, token)
        data["depts"] = dp if odp and isinstance(dp, list) else []
        ou, us = _safe(api.list_users, token)
        data["users"] = us if ou and isinstance(us, list) else []
    return data


# ── CARD RENDERERS (read-only → HTML) ────────────────────────────────────────
def appts_html(appts):
    if not appts:
        return empty("📅", "No appointments yet. Submit a request to book one.")
    out = ""
    for a in appts:
        out += (
            f'<div class="ac-item"><div>'
            f'<div class="t">{esc(a.get("department") or "Appointment")}'
            f'{" · " + esc(a["doctor"]) if a.get("doctor") else ""}</div>'
            f'<div class="s">🕑 {esc(fmt_dt(a.get("start_time")))}'
            f'{" — " + esc(a["reason"]) if a.get("reason") else ""}</div></div>'
            f'<div class="r">{pill(a.get("status") or "—")}'
            f'<div class="s mono">#{esc(a.get("appointment_id"))}</div></div></div>')
    return out


def docs_html(docs):
    if not docs:
        return empty("📄", "No documents yet. Attach one when you submit a request.")
    out = ""
    for d in docs:
        cs = str(d.get("checksum") or "")
        out += (
            f'<div class="ac-item"><div>'
            f'<div class="t">📄 {esc((d.get("type") or "document").replace("_", " ").title())}</div>'
            f'<div class="s">{esc(fmt_dt(d.get("date")) if d.get("date") else "Date not set")}'
            f'{" · <span class=mono>" + esc(cs[:12]) + "…</span>" if cs else ""}</div></div>'
            f'<div class="r"><div class="s mono">#{esc(d.get("document_id"))}</div></div></div>')
    return out


def rems_html(rems):
    if not rems:
        return empty("🔔", "No reminders yet.")
    out = ""
    for r in rems:
        out += (
            f'<div class="ac-item"><div>'
            f'<div class="t">🔔 {esc((r.get("type") or "reminder").replace("_", " ").title())}</div>'
            f'<div class="s">{esc(r.get("message") or "")}'
            f'{"<br>🕑 " + esc(fmt_dt(r.get("scheduled_at"))) if r.get("scheduled_at") else ""}</div></div>'
            f'<div class="r">{pill(r.get("status") or "—")}</div></div>')
    return out


def workflows_html(wfs):
    if not wfs:
        return empty("🗂️", "No workflow runs yet.")
    out = ""
    for w in wfs:
        out += (
            f'<div class="ac-item"><div>'
            f'<div class="t">Run #{esc(w.get("workflow_run_id"))} · Patient {esc(w.get("patient_id"))}</div>'
            f'<div class="s">{esc(w.get("request") or "")}</div>'
            f'<div class="s mono">Step: {esc(w.get("current_step") or "—")} · '
            f'{esc(fmt_dt(w.get("created_at")))}</div></div>'
            f'<div class="r">{pill(w.get("status") or "—")}</div></div>')
    return out


def audit_html(audit):
    if not audit:
        return empty("🧾", "No audit events yet.")
    out = ""
    for ev in audit:
        out += (
            f'<div class="ac-item"><div>'
            f'<div class="t">{esc((ev.get("action") or "event").replace("_", " ").title())}</div>'
            f'<div class="s mono">{esc(ev.get("actor_type") or "?")} #{esc(ev.get("actor_id"))} '
            f'→ {esc(ev.get("entity_type") or "?")} #{esc(ev.get("entity_id"))}</div></div>'
            f'<div class="r"><div class="s mono">{esc(fmt_dt(ev.get("created_at")))}</div></div></div>')
    return out


def departments_html(depts):
    if not depts:
        return empty("🏥", "No departments configured.")
    out = ""
    for d in depts:
        out += (
            f'<div class="ac-item"><div>'
            f'<div class="t">🏥 {esc(d.get("name"))}</div>'
            f'<div class="s mono">Department #{esc(d.get("id"))} · '
            f'{esc(d.get("doctors"))} doctor(s)</div></div>'
            f'<div class="r">{pill("active" if d.get("active") else "inactive")}</div></div>')
    return out


_ROLE_ICON = {"patient": "🧑", "staff": "🧑‍⚕️", "admin": "🛡️"}


def users_html(users):
    if not users:
        return empty("👥", "No accounts yet.")
    out = ""
    for u in users:
        role = str(u.get("role") or "")
        out += (
            f'<div class="ac-item"><div>'
            f'<div class="t">{_ROLE_ICON.get(role, "👤")} {esc(u.get("name"))}</div>'
            f'<div class="s mono">{esc(u.get("email"))} · joined {esc(fmt_dt(u.get("created_at")))}</div></div>'
            f'<div class="r">{pill(role or "—")}</div></div>')
    return out


def patient_escs_html(escs):
    if not escs:
        return empty("📨", "No requests under review. Anything clinical you submit "
                           "is reviewed by a person and its status shows here.")
    out = ""
    for e in escs:
        status = str(e.get("status") or "open")
        notes = e.get("review_notes")
        head = {"open": "Under review", "approved": "Approved by staff",
                "rejected": "Declined by staff", "resolved": "Resolved"}.get(status, status.title())
        out += (
            f'<div class="ac-item"><div>'
            f'<div class="t">📨 {esc(head)}</div>'
            f'<div class="s">{esc(e.get("reason"))}'
            f'{"<br>📝 " + esc(notes) if notes else ""}'
            f'{"<br>🕑 reviewed " + esc(fmt_dt(e.get("reviewed_at"))) if e.get("reviewed_at") else ""}</div></div>'
            f'<div class="r">{pill(status)}<div class="s mono">#{esc(e.get("escalation_id"))}</div></div></div>')
    return out


# ── RESULT (New request outcome) ─────────────────────────────────────────────
def render_result(data):
    status = data.get("status")
    appt_id = data.get("appointment_id")
    trace = data.get("trace", []) or []
    failed = next((l for l in trace if "fail" in l.lower()), None)
    confirmation = data.get("confirmation")

    if status == "completed" and appt_id:
        st.success(confirmation or "Your request was completed and an appointment was booked.")
    elif status == "escalated":
        st.warning(confirmation or "This request was routed to a human coordinator for review "
                                   "(clinical or emergency content is never handled automatically).")
    elif failed and not appt_id:
        st.warning("Your request was processed, but a booking couldn't be completed automatically.")
    else:
        st.info(confirmation or f"Status: {status}")

    chips = []
    if data.get("department_name"):
        chips.append(f'<span class="pill blue">🏥 {esc(data["department_name"])}</span>')
    if appt_id:
        chips.append(f'<span class="pill green">📅 Appointment #{esc(appt_id)}</span>')
    if data.get("workflow_run_id"):
        chips.append(f'<span class="pill gray">Run #{esc(data["workflow_run_id"])}</span>')
    if chips:
        st.markdown("&nbsp;".join(chips), unsafe_allow_html=True)

    if failed and not appt_id:
        reason = failed.split("(")[-1].rstrip(").") if "(" in failed else failed
        st.markdown(
            f'<div class="callout warn">⚠️ <b>Booking not completed —</b> '
            f'{esc(reason.replace("_", " "))}. This often means the time slot conflicts with an '
            f'existing appointment. Try a different time, or a coordinator can arrange it for you.</div>',
            unsafe_allow_html=True)

    if data.get("missing_documents"):
        st.info("📄 Please bring: " + ", ".join(data["missing_documents"]))

    if trace:
        with st.expander(f"🧭 Agent trace · {len(trace)} steps"):
            steps = "".join(f'<div class="step">{esc(line)}</div>' for line in trace)
            st.markdown(f'<div class="trace">{steps}</div>', unsafe_allow_html=True)


# ── RIGHT PANEL (contextual) ─────────────────────────────────────────────────
def _safety_card():
    return (
        '<div class="rp-card rp-safety"><h4>🛡️ Safety boundary</h4>'
        '<p>AgentCare handles <b>administration only</b> — routing, booking, documents, '
        'reminders. It never diagnoses, prescribes, or gives clinical advice. Emergency or '
        'clinical requests are escalated to a human.</p></div>')


def right_panel(role, section, data):
    blocks = []

    if section == "New request":
        blocks.append(
            '<div class="rp-card"><h4>How it works</h4>'
            '<div class="rp-step"><span class="num">1</span><span>The <b>Coordinator</b> reads your request and plans the steps.</span></div>'
            '<div class="rp-step"><span class="num">2</span><span>The <b>Safety</b> agent screens for emergencies or clinical advice.</span></div>'
            '<div class="rp-step"><span class="num">3</span><span><b>Routing</b> matches you to the right department.</span></div>'
            '<div class="rp-step"><span class="num">4</span><span><b>Appointment</b> finds a slot and books it (conflict-checked).</span></div>'
            '<div class="rp-step"><span class="num">5</span><span><b>Documents</b> &amp; <b>Follow-up</b> coordinate the rest.</span></div>'
            '</div>')
        blocks.append(_safety_card())

    elif section == "Overview" and role == "patient":
        blocks.append(
            '<div class="rp-card"><h4>Tips</h4>'
            '<p>Describe what you need in plain language — e.g. "a dermatology appointment '
            'next week" — and attach any relevant document. The agents handle the rest.</p></div>')
        blocks.append(_safety_card())

    elif section == "My requests":
        blocks.append(
            '<div class="rp-card"><h4>What you\'ll see here</h4>'
            '<p>Anything clinical or urgent is sent to a person to review. When staff '
            'approve or decline it, the decision and any note appear here and in your '
            'reminders.</p></div>')
        blocks.append(
            '<div class="rp-card"><h4>Status</h4>'
            f'<div class="rp-leg">{pill("open")}<span>Waiting for staff review</span></div>'
            f'<div class="rp-leg">{pill("approved")}<span>Approved — staff will proceed</span></div>'
            f'<div class="rp-leg">{pill("rejected")}<span>Declined by staff</span></div>'
            '</div>')

    elif section == "People":
        blocks.append(
            '<div class="rp-card"><h4>Managing people</h4>'
            '<p>Create <b>staff</b> accounts for coordinators and reviewers, or add a '
            '<b>patient</b> on their behalf. New patients can also sign themselves up from '
            'the login screen.</p></div>')
        blocks.append(
            '<div class="rp-card"><h4>Roles</h4>'
            f'<div class="rp-leg">{pill("admin")}<span>Full access + user management</span></div>'
            f'<div class="rp-leg">{pill("staff")}<span>Reviews escalations & workflows</span></div>'
            f'<div class="rp-leg">{pill("patient")}<span>Submits requests, sees own data</span></div>'
            '</div>')

    elif section == "Escalations":
        blocks.append(
            '<div class="rp-card"><h4>Reviewing escalations</h4>'
            '<p><b>Approve</b> to authorize a coordinator to proceed; <b>Reject</b> to decline. '
            'Every decision is persisted and written to the audit trail.</p></div>')
        blocks.append(
            '<div class="rp-card"><h4>Categories</h4>'
            f'<div class="rp-leg">{pill("emergency")}<span>Acute — needs immediate human care</span></div>'
            f'<div class="rp-leg">{pill("sensitive")}<span>Diagnosis / prescription request</span></div>'
            '</div>')

    elif section == "Workflows":
        blocks.append(
            '<div class="rp-card"><h4>Run status</h4>'
            f'<div class="rp-leg">{pill("completed")}<span>Finished end-to-end</span></div>'
            f'<div class="rp-leg">{pill("escalated")}<span>Handed to a human</span></div>'
            f'<div class="rp-leg">{pill("running")}<span>In progress</span></div>'
            '</div>')

    elif section == "Audit trail":
        blocks.append(
            '<div class="rp-card"><h4>Audit trail</h4>'
            '<p>An append-only record of every action — logins, agent steps, bookings, and '
            'escalation decisions — with the actor and affected entity. It is never edited.</p></div>')

    elif section == "Departments":
        active = sum(1 for d in data.get("depts", []) if d.get("active"))
        docs = sum(int(d.get("doctors") or 0) for d in data.get("depts", []))
        blocks.append(
            '<div class="rp-card"><h4>At a glance</h4>'
            f'<p><b>{active}</b> active departments<br><b>{docs}</b> doctors across all departments</p></div>')
        blocks.append(_safety_card())

    else:  # staff/admin overview and fallbacks
        blocks.append(_safety_card())

    st.markdown("".join(blocks), unsafe_allow_html=True)


# ── SIDEBAR ──────────────────────────────────────────────────────────────────
def sidebar(backend_ok):
    role = st.session_state.role
    items = NAV.get(role, NAV["patient"])
    labels = [l for l, _ in items]
    if st.session_state.get("nav") not in labels:
        st.session_state.nav = labels[0]

    with st.sidebar:
        st.markdown(
            '<div class="sb-brand"><div class="mk">🩺</div>'
            '<div><div class="nm">AgentCare</div>'
            '<div class="tg">Care coordination</div></div></div>',
            unsafe_allow_html=True)

        name = st.session_state.name or "User"
        st.markdown(
            f'<div class="sb-user"><div class="av">{esc(name[:1].upper())}</div>'
            f'<div><div class="nm">{esc(name)}</div><div class="rl">{esc(role)}</div></div></div>',
            unsafe_allow_html=True)

        st.markdown('<div class="sb-cap">Menu</div>', unsafe_allow_html=True)
        for label, icon in items:
            active = st.session_state.nav == label
            if st.button(f"{icon}  {label}", key=f"nav_{label}",
                         type="primary" if active else "secondary",
                         use_container_width=True):
                go(label)

        st.divider()
        if st.button("⎋  Sign out", key="signout", use_container_width=True):
            logout(); st.rerun()

        dot = "ok" if backend_ok else "no"
        txt = "Backend connected" if backend_ok else "Backend offline"
        st.markdown(f'<div class="sb-conn"><span class="d {dot}"></span>{txt}</div>',
                    unsafe_allow_html=True)


# ── LOGIN ────────────────────────────────────────────────────────────────────
def login_view():
    # Center a narrow column so the auth card never spans the wide layout.
    _, mid, _ = st.columns([1, 1.15, 1])
    with mid:
        st.markdown('<div class="login-mark">🩺</div>', unsafe_allow_html=True)
        st.markdown('<p class="login-title">AgentCare</p>', unsafe_allow_html=True)
        st.markdown('<p class="login-sub">Agentic patient administration &amp; care coordination</p>',
                    unsafe_allow_html=True)
        st.write("")
        with st.container(border=True):
            tab_in, tab_up = st.tabs(["Sign in", "Create account"])

            with tab_in:
                with st.form("login"):
                    email = st.text_input("Email", value="patient@agentcare.local")
                    password = st.text_input("Password", type="password", value="patient123")
                    ok_btn = st.form_submit_button("Sign in", type="primary",
                                                   use_container_width=True)
                if ok_btn:
                    ok, data = _safe(api.login, email.strip(), password)
                    if ok:
                        start_session(data)
                        st.rerun()
                    else:
                        st.error(data.get("detail", "Login failed"))

            with tab_up:
                st.caption("New patients can create an account and sign in right away.")
                with st.form("register"):
                    rname = st.text_input("Full name", placeholder="Jane Doe")
                    remail = st.text_input("Email", placeholder="you@example.com", key="reg_email")
                    rpass = st.text_input("Password", type="password",
                                          help="At least 6 characters.", key="reg_pass")
                    up_btn = st.form_submit_button("Create account & sign in",
                                                   type="primary", use_container_width=True)
                if up_btn:
                    if not (rname.strip() and remail.strip() and rpass):
                        st.warning("Please fill in your name, email, and a password.")
                    else:
                        ok, data = _safe(api.register, rname.strip(), remail.strip(), rpass)
                        if ok:
                            start_session(data)
                            st.rerun()
                        else:
                            st.error(data.get("detail", "Registration failed"))

        st.write("")
        st.markdown(
            '<div class="demo"><b>Demo accounts</b>'
            '<div class="row"><span>Patient</span><span>patient@agentcare.local · patient123</span></div>'
            '<div class="row"><span>Staff</span><span>staff@agentcare.local · staff123</span></div>'
            '<div class="row"><span>Admin</span><span>admin@agentcare.local · admin123</span></div>'
            '</div>', unsafe_allow_html=True)


# ── SECTION CONTENT (main column) ────────────────────────────────────────────
def patient_section(section, token, data):
    if section == "Overview":
        page_head("Patient portal", "Overview", f"Welcome back, {st.session_state.name}.")
        upcoming = sum(1 for a in data["appts"]
                       if str(a.get("status", "")).lower() in ("booked", "confirmed"))
        reviewed = [e for e in data["escs"]
                    if str(e.get("status")) in ("approved", "rejected")]
        st.markdown(kpis([
            (upcoming or len(data["appts"]), "Appointments", "📅"),
            (len(data["docs"]), "Documents", "📄"),
            (len(data["rems"]), "Reminders", "🔔"),
        ]), unsafe_allow_html=True)
        if st.button("➕  Start a new request", type="primary"):
            go("New request")

        # Surface staff decisions on the patient's escalated requests.
        updates = [e for e in data["escs"] if str(e.get("status")) != "open"]
        if updates:
            st.markdown(sec_header("Request updates"), unsafe_allow_html=True)
            st.markdown(patient_escs_html(updates[:3]), unsafe_allow_html=True)

        st.markdown(sec_header("Recent appointments"), unsafe_allow_html=True)
        st.markdown(appts_html(data["appts"][:3]), unsafe_allow_html=True)
        st.markdown(sec_header("Reminders"), unsafe_allow_html=True)
        st.markdown(rems_html(data["rems"][:3]), unsafe_allow_html=True)

    elif section == "New request":
        page_head("Patient portal", "New request",
                  "Describe what you need — the agents route, book, and coordinate it.")
        with st.form("request"):
            req = st.text_area(
                "Request", label_visibility="collapsed", height=120,
                placeholder="e.g. I need a cardiology follow-up next week and want to attach my ECG.")
            up = st.file_uploader("Attach a document (optional)",
                                  type=["pdf", "png", "jpg", "txt", "csv"])
            submit = st.form_submit_button("Submit request", type="primary", use_container_width=True)
        if submit and req.strip():
            documents = [{"filename": up.name, "content": up.getvalue()}] if up else []
            with st.spinner("Agents are coordinating your request…"):
                ok, result = _safe(api.submit_request, token, req, documents=documents)
            if ok:
                render_result(result)
            else:
                st.error(result.get("detail", "Request failed."))
        elif submit:
            st.warning("Please describe your request first.")

    elif section == "My requests":
        page_head("Patient portal", "My requests",
                  "Requests that were sent for staff review, and their outcome.")
        st.markdown(patient_escs_html(data["escs"]), unsafe_allow_html=True)

    elif section == "Appointments":
        page_head("Patient portal", "Appointments", "Every appointment booked for you.")
        st.markdown(appts_html(data["appts"]), unsafe_allow_html=True)

        # Interactive management: reschedule / cancel active appointments.
        active = [a for a in data["appts"]
                  if a.get("status") in ("pending", "confirmed", "rescheduled")]
        if active:
            st.markdown(sec_header("Manage an appointment"), unsafe_allow_html=True)
            labels = {f"#{a['appointment_id']} · {a.get('department','')} · "
                      f"{(a.get('start_time') or '')[:16].replace('T',' ')}": a
                      for a in active}
            pick = st.selectbox("Select an appointment", list(labels.keys()),
                                key="appt_pick")
            aid = labels[pick]["appointment_id"]
            col_r, col_c = st.columns(2)

            with col_r:
                ok, slots = _safe(api.available_slots, token, aid)
                if ok and slots:
                    slot_labels = {f"{s['doctor_name']} · "
                                   f"{s['start_time'][:16].replace('T',' ')}": s["slot_id"]
                                   for s in slots}
                    new_slot = st.selectbox("Reschedule to", list(slot_labels.keys()),
                                            key=f"slot_{aid}")
                    if st.button("Reschedule", key=f"resc_{aid}", use_container_width=True):
                        ok2, res = _safe(api.reschedule_appointment, token, aid,
                                         slot_labels[new_slot])
                        if ok2:
                            st.success("Appointment rescheduled.")
                            st.rerun()
                        else:
                            st.error(res.get("detail", "Could not reschedule."))
                else:
                    st.caption("No open slots to reschedule into right now.")

            with col_c:
                st.write("")
                st.write("")
                if st.button("Cancel appointment", key=f"canc_{aid}",
                             use_container_width=True):
                    ok2, res = _safe(api.cancel_appointment, token, aid)
                    if ok2:
                        st.success("Appointment cancelled.")
                        st.rerun()
                    else:
                        st.error(res.get("detail", "Could not cancel."))

    elif section == "Documents":
        page_head("Patient portal", "Documents", "Documents on file, classified and de-duplicated.")
        st.markdown(docs_html(data["docs"]), unsafe_allow_html=True)

    elif section == "Reminders":
        page_head("Patient portal", "Reminders", "Appointment and follow-up reminders.")
        st.markdown(rems_html(data["rems"]), unsafe_allow_html=True)

    elif section == "Privacy":
        page_head("Patient portal", "Privacy & consent",
                  "You control how AgentCare uses your data. Changes take effect immediately.")
        labels = {
            "document_storage": ("Document storage",
                                 "Allow storing and processing documents you attach "
                                 "(e.g. ECG, referrals). If off, attachments are not saved."),
            "data_processing": ("Data processing",
                                "Allow processing your data to handle administrative requests."),
            "communications": ("Communications",
                               "Allow appointment reminders and follow-up messages."),
        }
        consents = {c["consent_type"]: c for c in data.get("consents", [])}
        for ctype, (title, desc) in labels.items():
            c = consents.get(ctype, {"granted": False})
            with st.container(border=True):
                col_t, col_s = st.columns([4, 1])
                col_t.markdown(f"**{title}**  \n<span class='ac-hint'>{esc(desc)}</span>",
                               unsafe_allow_html=True)
                new_val = col_s.toggle("Allowed", value=bool(c.get("granted")),
                                       key=f"consent_{ctype}")
                if new_val != bool(c.get("granted")):
                    ok, _ = _safe(api.set_consent, token, ctype, new_val)
                    if ok:
                        st.rerun()


def staff_section(section, token, data, role):
    crumb = "Admin console" if role == "admin" else "Staff console"

    if section == "Overview":
        page_head(crumb, "Overview", "Operational snapshot across the coordination pipeline.")
        if role == "admin":
            st.markdown(kpis([
                (len(data["depts"]), "Departments", "🏥"),
                (len(data["escs"]), "Open escalations", "⚠️"),
                (len(data["wfs"]), "Workflow runs", "🗂️"),
                (len(data["audit"]), "Audit events", "🧾"),
            ]), unsafe_allow_html=True)
        else:
            st.markdown(kpis([
                (len(data["escs"]), "Open escalations", "⚠️"),
                (len(data["wfs"]), "Workflow runs", "🗂️"),
                (len(data["audit"]), "Audit events", "🧾"),
            ]), unsafe_allow_html=True)

        st.markdown(sec_header("Open escalations"), unsafe_allow_html=True)
        if data["escs"]:
            st.caption("Click a request to open it for review.")
            for e in data["escs"][:4]:
                eid = e["escalation_id"]
                st.markdown(
                    f'<div class="ac-item" style="margin-bottom:6px"><div>'
                    f'<div class="t">Escalation #{esc(eid)}</div>'
                    f'<div class="s">{esc(e.get("reason"))}</div></div>'
                    f'<div class="r">{pill(e.get("category") or "review")}</div></div>',
                    unsafe_allow_html=True)
                if st.button(f"Open review #{eid} →", key=f"ov_esc_{eid}",
                             use_container_width=True):
                    st.session_state.focus_esc = eid
                    go("Escalations")
        else:
            st.markdown(empty("✅", "No open escalations. You're all caught up."),
                        unsafe_allow_html=True)

        st.markdown(sec_header("Recent workflows"), unsafe_allow_html=True)
        st.markdown(workflows_html(data["wfs"][:4]), unsafe_allow_html=True)

    elif section == "Escalations":
        page_head(crumb, "Escalations", "Human-in-the-loop review — approve or reject.")
        focus = st.session_state.get("focus_esc")
        escs = data["escs"]
        if focus is not None:
            # Bring the clicked-through request to the top so it's front and center.
            escs = sorted(escs, key=lambda e: e["escalation_id"] != focus)
        if escs:
            for e in escs:
                eid = e["escalation_id"]
                focused = (eid == focus)
                with st.container(border=True):
                    if focused:
                        st.markdown(
                            '<div class="callout warn" style="margin:0 0 10px">'
                            '➡️ Opened from your overview.</div>', unsafe_allow_html=True)
                    st.markdown(
                        f'<div style="display:flex;justify-content:space-between;align-items:center">'
                        f'<div class="t" style="font-weight:750">Escalation #{esc(eid)}</div>'
                        f'{pill(e.get("category") or "review")}</div>'
                        f'<div class="s" style="margin-top:8px">{esc(e.get("reason"))}</div>'
                        f'<div class="s mono" style="margin-top:6px">Run #{esc(e.get("workflow_run_id"))} · '
                        f'{esc(fmt_dt(e.get("created_at")))}</div>',
                        unsafe_allow_html=True)
                    notes = st.text_input("Review notes", key=f"n{eid}",
                                          placeholder="Optional notes for the audit record")
                    a, r, _ = st.columns([1, 1, 3])
                    if a.button("Approve", key=f"a{eid}",
                                type="primary", use_container_width=True):
                        _safe(api.review_escalation, token, eid, "approve", notes)
                        st.session_state.focus_esc = None
                        st.rerun()
                    if r.button("Reject", key=f"r{eid}", use_container_width=True):
                        _safe(api.review_escalation, token, eid, "reject", notes)
                        st.session_state.focus_esc = None
                        st.rerun()
        else:
            st.session_state.focus_esc = None
            st.markdown(empty("✅", "No open escalations. You're all caught up."),
                        unsafe_allow_html=True)

    elif section == "Appointments":
        page_head(crumb, "Appointments",
                  "Upcoming schedule and past appointments awaiting confirmation.")
        tab_upcoming, tab_confirm = st.tabs(
            [f"📅 Upcoming ({len(data.get('upcoming', []))})",
             f"✅ Awaiting confirmation ({len(data.get('appts', []))})"])

        with tab_upcoming:
            upcoming = data.get("upcoming", [])
            if not upcoming:
                st.markdown(empty("📅", "No upcoming appointments scheduled."),
                            unsafe_allow_html=True)
            else:
                st.caption("Confirmed and pending appointments, earliest first.")
                st.markdown(appts_html(upcoming), unsafe_allow_html=True)

        with tab_confirm:
            awaiting = data.get("appts", [])
            if not awaiting:
                st.markdown(empty("✅", "No appointments awaiting confirmation."),
                            unsafe_allow_html=True)
            else:
                st.caption("Confirm whether each past appointment was attended. "
                           "Completed = attended · Missed = no-show.")
                for a in awaiting:
                    aid = a["appointment_id"]
                    with st.container(border=True):
                        when = (a.get("start_time") or "")[:16].replace("T", " ")
                        st.markdown(f"**#{aid} · {esc(a.get('department',''))} · "
                                    f"{esc(a.get('doctor',''))}**  \n"
                                    f"🕑 {esc(when)} — {esc(a.get('reason') or '')}")
                        c1, c2 = st.columns(2)
                        if c1.button("✓ Attended (complete)", key=f"att_{aid}",
                                     type="primary", use_container_width=True):
                            ok, _ = _safe(api.record_outcome, token, aid, True)
                            if ok:
                                st.success(f"Appointment #{aid} marked completed.")
                                st.rerun()
                        if c2.button("✗ Missed", key=f"miss_{aid}", use_container_width=True):
                            ok, _ = _safe(api.record_outcome, token, aid, False)
                            if ok:
                                st.warning(f"Appointment #{aid} marked missed.")
                                st.rerun()

    elif section == "Analytics":
        page_head(crumb, "Analytics",
                  "Operational metrics computed live from persisted data.")
        a = data.get("analytics", {})
        if not a:
            st.markdown(empty("📊", "No analytics available yet."), unsafe_allow_html=True)
        else:
            import pandas as pd
            k = a.get("kpis", {})
            att = k.get("attendance_rate_pct")
            st.markdown(kpis([
                (k.get("total_appointments", 0), "Appointments", "📅"),
                (k.get("total_patients", 0), "Patients", "🧑"),
                (k.get("open_escalations", 0), "Open escalations", "⚠️"),
                (f"{att}%" if att is not None else "—", "Attendance rate", "✅"),
            ]), unsafe_allow_html=True)
            st.markdown(kpis([
                (k.get("total_documents", 0), "Documents", "📄"),
                (k.get("total_reminders", 0), "Reminders", "🔔"),
            ]), unsafe_allow_html=True)

            def _bar(title, mapping, xlabel):
                st.markdown(sec_header(title), unsafe_allow_html=True)
                if mapping:
                    df = pd.DataFrame(
                        {xlabel: [str(x).replace("_", " ").title() for x in mapping.keys()],
                         "Count": list(mapping.values())}).set_index(xlabel)
                    st.bar_chart(df, height=240)
                else:
                    st.caption("No data yet.")

            c1, c2 = st.columns(2)
            with c1:
                _bar("Appointments by status", a.get("appointments_by_status", {}), "Status")
            with c2:
                _bar("Workflows by status", a.get("workflows_by_status", {}), "Status")
            c3, c4 = st.columns(2)
            with c3:
                _bar("Escalations by category", a.get("escalations_by_category", {}), "Category")
            with c4:
                _bar("Documents by type", a.get("documents_by_type", {}), "Type")

            st.markdown(sec_header("Department load"), unsafe_allow_html=True)
            dl = a.get("department_load", [])
            if dl:
                df = pd.DataFrame(dl).rename(
                    columns={"department": "Department", "appointments": "Appointments"}
                ).set_index("Department")
                st.bar_chart(df, height=280)
            else:
                st.caption("No appointments booked yet.")

    elif section == "Workflows":
        page_head(crumb, "Workflows", "Every agent run, with its status and current step.")
        st.markdown(workflows_html(data["wfs"]), unsafe_allow_html=True)

    elif section == "Audit trail":
        page_head(crumb, "Audit trail", "Append-only record of every action in the system.")
        st.markdown(audit_html(data["audit"]), unsafe_allow_html=True)

    elif section == "People":
        page_head(crumb, "People", "All staff and patients — and add new accounts.")
        users = data["users"]
        staff_users = [u for u in users if u.get("role") in ("staff", "admin")]
        patient_users = [u for u in users if u.get("role") == "patient"]
        st.markdown(kpis([
            (len(users), "Total accounts", "👥"),
            (len(staff_users), "Staff & admins", "🧑‍⚕️"),
            (len(patient_users), "Patients", "🧑"),
        ]), unsafe_allow_html=True)

        with st.expander("➕  Add a new account"):
            with st.form("add_user"):
                c1, c2 = st.columns(2)
                nu_name = c1.text_input("Full name", placeholder="Jane Doe")
                nu_email = c2.text_input("Email", placeholder="jane@agentcare.local")
                c3, c4 = st.columns(2)
                nu_role = c3.selectbox("Role", ["staff", "patient", "admin"])
                nu_pass = c4.text_input("Temporary password", type="password",
                                        help="At least 6 characters.")
                add_btn = st.form_submit_button("Create account", type="primary",
                                                use_container_width=True)
            if add_btn:
                if not (nu_name.strip() and nu_email.strip() and nu_pass):
                    st.warning("Name, email, and password are all required.")
                else:
                    ok, res = _safe(api.create_user, token, nu_name.strip(),
                                    nu_email.strip(), nu_pass, nu_role)
                    if ok:
                        st.success(f"Created {res.get('role')} account for {res.get('name')}.")
                        st.rerun()
                    else:
                        st.error(res.get("detail", "Could not create the account."))

        tabs = st.tabs([f"🧑‍⚕️ Staff & admins · {len(staff_users)}",
                        f"🧑 Patients · {len(patient_users)}"])
        with tabs[0]:
            st.markdown(users_html(staff_users), unsafe_allow_html=True)
        with tabs[1]:
            st.markdown(users_html(patient_users), unsafe_allow_html=True)

    elif section == "Departments":
        page_head(crumb, "Departments", "Departments and their staffing.")
        st.markdown(departments_html(data["depts"]), unsafe_allow_html=True)


# ── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    _init_state()
    inject_css()
    restore_session()   # rehydrate login from ?sid= so a refresh doesn't log out

    if not st.session_state.token:
        login_view()
        return

    role = st.session_state.role
    token = st.session_state.token
    data = load_patient(token) if role == "patient" else load_staff(token, role)

    sidebar(data["ok"])
    section = st.session_state.nav

    if not data["ok"]:
        st.error("Cannot reach the backend. Start it with:  "
                 "`uvicorn app.api.main:app --reload`")

    main_col, right_col = st.columns([2.6, 1], gap="large")
    with main_col:
        if role == "patient":
            patient_section(section, token, data)
        else:
            staff_section(section, token, data, role)
    with right_col:
        right_panel(role, section, data)


if __name__ == "__main__":
    main()