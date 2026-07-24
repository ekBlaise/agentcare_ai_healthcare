"""
AgentCare - Streamlit UI (patient + staff views), wired to the FastAPI backend.

Run the backend first:
    uvicorn app.api.main:app --reload
Then run this UI (from the project root):
    streamlit run app/ui/streamlit_app.py

Colors come from .streamlit/config.toml (native theme) so they render reliably
across Streamlit versions. All data shown is from live API calls.
"""
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import streamlit as st
from app.ui import api_client as api

st.set_page_config(page_title="AgentCare", page_icon="🏥", layout="centered",
                   initial_sidebar_state="collapsed")

# Minimal, SAFE styling only. Colors are handled by the native theme
# (.streamlit/config.toml), which never half-fails like deep CSS hacks do.
st.markdown("""
<style>
#MainMenu, footer, header {visibility:hidden;}
.block-container{padding-top:2.2rem; max-width:560px;}
.ac-logo{width:56px;height:56px;border-radius:15px;display:flex;align-items:center;
  justify-content:center;font-size:28px;margin:0 auto 12px;
  background:linear-gradient(135deg,#0f766e,#0d9488);
  box-shadow:0 6px 18px rgba(15,118,110,.35);}
.ac-title{text-align:center;font-size:1.9rem;font-weight:700;color:#132520;margin:0;}
.ac-sub{text-align:center;color:#5b6b67;font-size:.95rem;margin:.15rem 0 0;}
.ac-foot{text-align:center;color:#5b6b67;font-size:.82rem;line-height:1.7;}
.ac-foot b{color:#132520;}
</style>
""", unsafe_allow_html=True)


def _init_state():
    for k in ("token", "role", "name"):
        st.session_state.setdefault(k, None)


def logout():
    for k in ("token", "role", "name"):
        st.session_state[k] = None


def _safe(fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception as e:
        return False, {"detail": "Cannot reach the backend. Start it with: "
                                 "uvicorn app.api.main:app --reload"}


# ── LOGIN ──────────────────────────────────────────────────────────────────
def login_view():
    st.markdown('<div class="ac-logo">🏥</div>', unsafe_allow_html=True)
    st.markdown('<p class="ac-title">AgentCare</p>', unsafe_allow_html=True)
    st.markdown('<p class="ac-sub">Patient administration &amp; care coordination</p>',
                unsafe_allow_html=True)
    st.write("")

    with st.container(border=True):
        st.subheader("Sign in")
        with st.form("login"):
            email = st.text_input("Email", value="patient@agentcare.local")
            password = st.text_input("Password", type="password")
            ok_btn = st.form_submit_button("Sign in", type="primary",
                                           use_container_width=True)
        if ok_btn:
            ok, data = _safe(api.login, email.strip(), password)
            if ok:
                st.session_state.update(token=data["access_token"],
                                        role=data["role"], name=data["name"])
                st.rerun()
            else:
                st.error(data.get("detail", "Login failed"))

    st.write("")
    st.markdown('<p class="ac-foot"><b>Demo accounts</b><br>'
                'patient@agentcare.local &nbsp;·&nbsp; patient123<br>'
                'staff@agentcare.local &nbsp;·&nbsp; staff123</p>',
                unsafe_allow_html=True)


# ── PATIENT ────────────────────────────────────────────────────────────────
def patient_view(token):
    with st.container(border=True):
        st.subheader("New request")
        st.caption("Describe what you need — the agents route it, book an "
                   "appointment, and coordinate documents.")
        with st.form("request"):
            req = st.text_area("Request", label_visibility="collapsed", height=100,
                               placeholder="e.g. I need a cardiology follow-up next week "
                                           "and want to attach my ECG.")
            up = st.file_uploader("Attach a document (optional)",
                                  type=["pdf", "png", "jpg", "txt", "csv"])
            go = st.form_submit_button("Submit request", type="primary",
                                       use_container_width=True)
        if go and req.strip():
            docs = [{"filename": up.name, "content": up.getvalue()}] if up else []
            with st.spinner("Agents are coordinating your request…"):
                ok, data = _safe(api.submit_request, token, req, documents=docs)
            if ok:
                s = data.get("status")
                msg = data.get("confirmation", f"Status: {s}")
                (st.success if s == "completed" else
                 st.warning if s == "escalated" else st.info)(msg)
                if data.get("missing_documents"):
                    st.info("📄 Please bring: " + ", ".join(data["missing_documents"]))
                with st.expander("View agent trace"):
                    for line in data.get("trace", []):
                        st.markdown(f"- {line}")
            else:
                st.error(data.get("detail", "Request failed."))

    st.write("")
    with st.container(border=True):
        t = st.tabs(["📅 Appointments", "📄 Documents", "🔔 Reminders"])
        with t[0]:
            ok, d = _safe(api.my_appointments, token)
            st.dataframe(d, use_container_width=True, hide_index=True) if ok and d else st.caption("None yet.")
        with t[1]:
            ok, d = _safe(api.my_documents, token)
            st.dataframe(d, use_container_width=True, hide_index=True) if ok and d else st.caption("None yet.")
        with t[2]:
            ok, d = _safe(api.my_reminders, token)
            st.dataframe(d, use_container_width=True, hide_index=True) if ok and d else st.caption("None yet.")


# ── STAFF ──────────────────────────────────────────────────────────────────
def staff_view(token):
    with st.container(border=True):
        t = st.tabs(["⚠️ Escalations", "🗂 Workflows", "🧾 Audit"])
        with t[0]:
            st.subheader("Escalations awaiting review")
            ok, escs = _safe(api.list_escalations, token, status="open")
            if ok and escs:
                for e in escs:
                    with st.container(border=True):
                        st.markdown(f"**#{e['escalation_id']} · {e['category'].upper()}**")
                        st.write(e["reason"])
                        a, r, n = st.columns([1, 1, 3])
                        notes = n.text_input("Notes", key=f"n{e['escalation_id']}",
                                             label_visibility="collapsed",
                                             placeholder="Review notes")
                        if a.button("Approve", key=f"a{e['escalation_id']}",
                                    type="primary", use_container_width=True):
                            _safe(api.review_escalation, token, e["escalation_id"], "approve", notes)
                            st.rerun()
                        if r.button("Reject", key=f"r{e['escalation_id']}",
                                    use_container_width=True):
                            _safe(api.review_escalation, token, e["escalation_id"], "reject", notes)
                            st.rerun()
            else:
                st.caption("No open escalations.")
        with t[1]:
            st.subheader("Workflow runs")
            ok, d = _safe(api.list_workflows, token)
            st.dataframe(d, use_container_width=True, hide_index=True) if ok and d else st.caption("None yet.")
        with t[2]:
            st.subheader("Audit trail")
            ok, d = _safe(api.audit_trail, token, limit=100)
            st.dataframe(d, use_container_width=True, hide_index=True) if ok and d else st.caption("None yet.")


def main():
    _init_state()
    if not st.session_state.token:
        login_view()
        return

    # top bar
    c1, c2 = st.columns([3, 1])
    role = st.session_state.role
    c1.subheader("Patient portal" if role == "patient" else "Staff console")
    c1.caption(f"Signed in as {st.session_state.name} · {role}")
    if c2.button("Sign out", use_container_width=True):
        logout(); st.rerun()
    st.divider()

    (patient_view if role == "patient" else staff_view)(st.session_state.token)


if __name__ == "__main__":
    main()