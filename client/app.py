import streamlit as st
import requests
import json
from requests.auth import AuthBase


class BearerAuth(AuthBase):
    """Attach the JWT to every request; the password is only sent once, at login."""

    def __init__(self, token):
        self.token = token

    def __call__(self, request):
        request.headers["Authorization"] = f"Bearer {self.token}"
        return request
import datetime
from dotenv import load_dotenv
import os

load_dotenv()

# Configuration
API_URL=os.getenv("BASE_URL")
# st.write(API_URL)

# set page configurationRR
st.set_page_config(
    page_title="Medical Report Diagnosis",
    layout="wide",
    initial_sidebar_state="expanded"
)

# initial  state management 

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "username" not in st.session_state:
    st.session_state.username = ""
if "full_name" not in st.session_state:
    st.session_state.full_name = None
if "role" not in st.session_state:
    st.session_state.role = ""
if "auth" not in st.session_state:
    st.session_state.auth = None

# API Functions :

# 1. Signup Function (public signup always creates a patient account)
def signup_user(username, password, full_name=None):
    try:
        response = requests.post(
            f"{API_URL}/auth/signup",
            json={"username": username, "password": password, "full_name": full_name}
        )
        return response.status_code, response.json()
    except requests.exceptions.ConnectionError:
        return 503, {"detail": "Server is unavailable. Please try again later."}
    
# 2. Authenticate Function
def authenticate_user(username, password):
    try:
        # Password goes to the server once; we get back a short-lived signed token
        response = requests.post(
            f"{API_URL}/auth/token",
            data={"username": username, "password": password}
        )
        return response.status_code, response.json()
    except requests.exceptions.ConnectionError:
        return 503, {"detail": "Server is unavailable. Please try again later."}
    
# 3. Upload Medical Report 
def upload_report(auth, files):
    try:
        headers = {'accept': 'application/json'}
        files_data = [('files', (file.name, file.getvalue(), file.type)) for file in files]
        response = requests.post(
            f"{API_URL}/reports/upload",
            auth=auth,
            files=files_data,
            headers=headers
        )
        return response.status_code, response.json()
    except requests.exceptions.ConnectionError:
        return 503, {"detail": "Server is unavailable. Please try again later."}
    
# 3b. List the logged-in patient's reports
def get_my_reports(auth):
    try:
        response = requests.get(f"{API_URL}/reports/mine", auth=auth)
        return response.status_code, response.json()
    except requests.exceptions.ConnectionError:
        return 503, {"detail": "Server is unavailable. Please try again later."}


def report_label(report):
    uploaded = datetime.datetime.fromtimestamp(report["uploaded_at"]).strftime("%Y-%m-%d %H:%M")
    return f"{', '.join(report['filenames'])} — {uploaded} ({report['num_chunks']} chunks)"

#  4. Diagnosis  Function
def get_diagnosis(auth, doc_id, question):
    try:
        data = {
            'doc_id': doc_id,
            'question': question
        }
        response = requests.post(
            f"{API_URL}/diagnosis/from_report",
            auth=auth,
            data=data
        )
        return response.status_code, response.json()
    except requests.exceptions.ConnectionError:
        return 503, {"detail": "Server is unavailable. Please try again later."}
    
# 5. All Diagnosis Function
def get_doctor_diagnosis(auth, patient_name):
    try:
        response = requests.get(
            f"{API_URL}/diagnosis/by_patient_name",
            auth=auth,
            params={'patient_name': patient_name}
        )
        return response.status_code, response.json()
    except requests.exceptions.ConnectionError:
        return 503, {"detail": "Server is unavailable. Please try again later."}

# 6. Admin: create a user with a role (e.g. doctor)
def admin_create_user(auth, username, password, role, full_name=None):
    try:
        response = requests.post(
            f"{API_URL}/auth/users",
            auth=auth,
            json={"username": username, "password": password, "role": role, "full_name": full_name}
        )
        return response.status_code, response.json()
    except requests.exceptions.ConnectionError:
        return 503, {"detail": "Server is unavailable. Please try again later."}

# 7. Admin: list users
def admin_list_users(auth):
    try:
        response = requests.get(f"{API_URL}/auth/users", auth=auth)
        return response.status_code, response.json()
    except requests.exceptions.ConnectionError:
        return 503, {"detail": "Server is unavailable. Please try again later."}

# 8. Assignments: admin sees all; a doctor sees their own patients
def get_assignments(auth):
    try:
        response = requests.get(f"{API_URL}/assignments", auth=auth)
        return response.status_code, response.json()
    except requests.exceptions.ConnectionError:
        return 503, {"detail": "Server is unavailable. Please try again later."}

# 9. Admin: assign / unassign a patient to a doctor
def admin_set_assignment(auth, doctor, patient, remove=False):
    try:
        response = requests.request(
            "DELETE" if remove else "POST",
            f"{API_URL}/assignments",
            auth=auth,
            json={"doctor": doctor, "patient": patient},
        )
        return response.status_code, response.json()
    except requests.exceptions.ConnectionError:
        return 503, {"detail": "Server is unavailable. Please try again later."}


def show_critical_banner(alerts):
    """Red URGENT banner for rule-detected critical values (shown before any AI text)."""
    if alerts:
        st.error(
            "🚨 **URGENT — critical lab value(s) detected. Please seek medical care immediately.**\n\n"
            + "\n".join(f"- {alert}" for alert in alerts)
        )


def show_lab_table(labs):
    rows = []
    for lab in labs:
        low, high = lab.get("ref_low"), lab.get("ref_high")
        if low is not None and high is not None:
            ref = f"{low:g} – {high:g}"
        elif high is not None:
            ref = f"≤ {high:g}"
        elif low is not None:
            ref = f"≥ {low:g}"
        else:
            ref = "—"
        rows.append({
            "Test": lab["test"],
            "Value": f"{lab['value']:g} {lab.get('unit') or ''}".strip(),
            "Reference": ref,
            "Flag": ("🔴 CRITICAL " if lab.get("critical") else "") + lab["flag"],
            "Range from": lab.get("range_source") or "—",
            "Source": lab.get("source", ""),
        })
    st.table(rows)


def show_differential_table(differential):
    badge = {"High": "🟥 High", "Medium": "🟧 Medium", "Low": "🟨 Low"}
    st.table([
        {
            "Possible condition": d["name"],
            "Likelihood": badge.get(d["likelihood"], d["likelihood"]),
            "Supporting findings": "; ".join(d["supporting"]),
            "Against": "; ".join(d["against"]) or "—",
            "Not measured": ", ".join(d["not_measured"]) or "—",
            "Tests to confirm": "; ".join(d["confirm_tests"]),
        }
        for d in differential
    ])
    st.caption("Ranking is computed by rules from the lab pattern, not by the AI. "
               "It is a list of possibilities to discuss with a doctor, not a diagnosis.")


AUDIT_ACTIONS = ["(all)", "auth_failed", "login", "signup", "user_created", "assignment_created",
                 "assignment_removed", "report_uploaded", "labs_viewed", "diagnosis_created",
                 "history_viewed", "diagnosis_reviewed", "report_deleted"]

REVIEW_BADGE = {
    "pending_review": "🕒 Awaiting doctor review",
    "approved": "✅ Doctor-verified",
    "edited": "✅ Doctor-verified (edited)",
    "rejected": "❌ Rejected by doctor",
}


def api_get(auth, path):
    try:
        response = requests.get(f"{API_URL}{path}", auth=auth)
        return response.status_code, response.json()
    except requests.exceptions.ConnectionError:
        return 503, {"detail": "Server is unavailable. Please try again later."}


def api_post(auth, path, payload):
    try:
        response = requests.post(f"{API_URL}{path}", auth=auth, json=payload)
        return response.status_code, response.json()
    except requests.exceptions.ConnectionError:
        return 503, {"detail": "Server is unavailable. Please try again later."}


def format_error(data):
    """FastAPI returns a string detail, or a list of validation errors (422)."""
    detail = data.get("detail", "Unknown error") if isinstance(data, dict) else data
    if isinstance(detail, list):
        return "; ".join(err.get("msg", str(err)) for err in detail)
    return detail

# Session check: an expired or invalid token logs the user out with a clear message
if st.session_state.logged_in and st.session_state.auth is not None:
    try:
        me = requests.get(f"{API_URL}/auth/me", auth=st.session_state.auth, timeout=10)
        if me.status_code == 401:
            st.session_state.logged_in = False
            st.session_state.username = ""
            st.session_state.role = ""
            st.session_state.full_name = None
            st.session_state.auth = None
            st.warning(f"🔒 {me.json().get('detail', 'Your session ended')}. Please log in again.")
    except requests.exceptions.RequestException:
        pass  # server unreachable: individual calls will show their own errors

# Sidebar and Authentication Flow
st.sidebar.title("Navigation")
st.sidebar.markdown("---")

if st.session_state.logged_in:
    display = st.session_state.full_name or st.session_state.username
    st.sidebar.success(f"Logged in as **{display}** ({st.session_state.role})")
    if st.sidebar.button("Logout"):
        st.session_state.logged_in = False
        st.session_state.username = ""
        st.session_state.role = ""
        st.session_state.full_name = None
        st.session_state.auth = None
        st.rerun()
else:
    st.sidebar.header("Login")
    login_username = st.sidebar.text_input("Username", key="login_username")
    login_password = st.sidebar.text_input("Password", type="password", key="login_password")
    if st.sidebar.button("Login"):
        if login_username and login_password:
            status_code, data = authenticate_user(login_username, login_password)
            if status_code == 200:
                st.session_state.logged_in = True
                st.session_state.username = login_username
                st.session_state.role = data["role"]
                st.session_state.full_name = data.get("full_name")
                st.session_state.auth = BearerAuth(data["access_token"])
                st.sidebar.success("Logged in successfully!")
                st.rerun()
            else:
                st.sidebar.error(f"Login failed: {data.get('detail', 'Unknown error')}")
        else:
            st.sidebar.warning("Please enter a username and password.")

    st.sidebar.header("Patient Signup")
    st.sidebar.caption("Doctor accounts are created by an administrator.")
    signup_username = st.sidebar.text_input("New Username", key="signup_username")
    signup_password = st.sidebar.text_input("New Password (min 6 chars)", type="password", key="signup_password")
    signup_full_name = st.sidebar.text_input("Full name (optional, shown to your doctor)", key="signup_full_name")
    if st.sidebar.button("Signup"):
        if signup_username and signup_password:
            status_code, data = signup_user(signup_username, signup_password, signup_full_name or None)
            if status_code == 200:
                st.sidebar.success("Patient account created! You can now log in.")
            else:
                st.sidebar.error(f"Signup failed: {format_error(data)}")
        else:
            st.sidebar.warning("Please fill in all fields.")


# Main Page Application

st.title("👨‍⚕️ GenAI-Powered Medical Diagnosis")
st.markdown("This application uses a FastAPI backend with a LangChain/GenAI stack to help patients get a diagnosis from their reports and allow doctors to access their patients' diagnosis history.")

if not st.session_state.logged_in:
    st.info("Please log in or sign up to use the application.")
else:
    if st.session_state.role == "patient":
        st.header("Patient Dashboard")
        st.markdown("---")

        st.subheader("Upload Your Report")
        with st.form("upload_form"):
            uploaded_files = st.file_uploader(
                "Choose medical report files (PDF, TXT, or a photo/scan: PNG, JPG)",
                type=["pdf", "txt", "png", "jpg", "jpeg"],
                accept_multiple_files=True
            )
            upload_submitted = st.form_submit_button("Upload Reports")
            if upload_submitted and uploaded_files:
                with st.spinner("Uploading and processing reports..."):
                    status_code, data = upload_report(st.session_state.auth, uploaded_files)
                    if status_code == 200:
                        show_critical_banner(data.get("critical_alerts", []))
                        st.success(
                            f"Reports uploaded and indexed ({data.get('num_chunks', '?')} chunks). "
                            f"Found {data.get('labs_found', 0)} lab values, "
                            f"{data.get('abnormal_count', 0)} outside the reference range."
                        )
                        if data.get("redacted"):
                            st.caption(f"🔒 {data['redacted']} personal identifier(s) (name, ID, phone, etc.) "
                                       "were removed before indexing and AI analysis.")
                        st.session_state.doc_id = data['doc_id'] # Store doc_id for later use
                    else:
                        st.error(f"Upload failed: {format_error(data)}")

        st.markdown("---")

        st.subheader("Get a Diagnosis")
        reports_status, my_reports = get_my_reports(st.session_state.auth)
        if reports_status != 200:
            st.error(f"Could not load your reports: {format_error(my_reports)}")
            my_reports = []

        if my_reports:
            with st.form("diagnosis_form"):
                report_ids = [r["doc_id"] for r in my_reports]
                labels = {r["doc_id"]: report_label(r) for r in my_reports}
                # Pre-select the report just uploaded, otherwise the newest one
                default_id = st.session_state.get("doc_id")
                default_index = report_ids.index(default_id) if default_id in report_ids else 0
                diagnosis_doc_id = st.selectbox(
                    "Choose one of your reports",
                    report_ids,
                    index=default_index,
                    format_func=lambda doc_id: labels[doc_id],
                )
                diagnosis_question = st.text_area(
                    "Enter your question for the diagnosis model:",
                    "Please provide a diagnosis based on my report."
                )
                diagnosis_submitted = st.form_submit_button("Get Diagnosis")
                if diagnosis_submitted:
                    with st.spinner("Generating diagnosis..."):
                        status_code, data = get_diagnosis(
                            st.session_state.auth,
                            diagnosis_doc_id,
                            diagnosis_question
                        )
                        if status_code == 200:
                            # Rule-based alerts come BEFORE any AI-generated text
                            show_critical_banner(data.get("critical_alerts", []))
                            if data.get("abnormal_labs"):
                                st.subheader("Abnormal Lab Values (rule-checked)")
                                show_lab_table(data["abnormal_labs"])
                            if data.get("differential"):
                                st.subheader("Differential Diagnosis (ranked by lab pattern)")
                                show_differential_table(data["differential"])
                            st.success("Diagnosis Generated!")
                            st.write("---")
                            st.subheader("Diagnosis Result")
                            if data.get("grounded") is True:
                                st.caption("✅ Checked: patient-specific statements are supported by your report.")
                            elif data.get("grounded") is False:
                                st.warning(
                                    "⚠️ Some statements could not be verified against your report: "
                                    f"{data.get('grounding_note') or 'unknown'}"
                                )
                            st.markdown(data.get("diagnosis") or "No diagnosis provided.")
                            st.write("---")
                            st.subheader("Sources")
                            for source in data.get("sources", []):
                                st.write(f"- {source}")
                            if data.get("knowledge_sources"):
                                st.caption("Reference medical knowledge used:")
                                for ref in data["knowledge_sources"]:
                                    st.write(f"- {ref['name']} — [{ref['source']}]({ref['url']})")
                            st.caption(
                                f"Generated by {data.get('model', 'AI model')}. "
                                "This is AI-generated information, not medical advice. Please consult a doctor."
                            )
                            st.info("🕒 This AI draft is awaiting review by your doctor. "
                                    "See **My Diagnosis History** below for the doctor's verdict.")
                        else:
                            st.error(f"Diagnosis failed: {format_error(data)}")
        else:
            st.info("You have no reports yet. Upload a report above to get started.")

        st.markdown("---")
        st.subheader("My Diagnosis History")
        status_code, history = api_get(st.session_state.auth, "/diagnosis/mine")
        if status_code != 200:
            st.error(f"Could not load your history: {format_error(history)}")
        elif not history:
            st.caption("No diagnoses yet.")
        for record in history if status_code == 200 else []:
            status = record.get("review_status", "pending_review")
            when = datetime.datetime.fromtimestamp(record["timestamp"]).strftime("%Y-%m-%d %H:%M")
            with st.expander(f"{REVIEW_BADGE.get(status, status)} — {when} — {record['question'][:60]}"):
                if status in ("approved", "edited"):
                    st.success(f"✅ Doctor-verified by Dr. {record.get('reviewed_by')}")
                    st.markdown(record.get("final_answer") or "")
                elif status == "rejected":
                    st.error(f"❌ Your doctor did not confirm this AI answer (Dr. {record.get('reviewed_by')}).")
                else:
                    st.caption("🕒 AI draft — not yet reviewed by a doctor:")
                    st.markdown(record["answer"])
                if record.get("doctor_note"):
                    st.info(f"**Doctor's note:** {record['doctor_note']}")

        if my_reports:
            st.markdown("---")
            with st.expander("🗑️ Delete a report"):
                st.caption("Permanently removes the file, its search index entries and its diagnosis history.")
                with st.form("delete_form"):
                    delete_id = st.selectbox("Report to delete", [r["doc_id"] for r in my_reports],
                                             format_func=lambda doc_id: report_label(
                                                 next(r for r in my_reports if r["doc_id"] == doc_id)))
                    confirm = st.checkbox("I understand this cannot be undone")
                    if st.form_submit_button("Delete permanently"):
                        if not confirm:
                            st.warning("Please tick the confirmation box first.")
                        else:
                            try:
                                response = requests.delete(f"{API_URL}/reports/{delete_id}", auth=st.session_state.auth)
                                data = response.json()
                                if response.status_code == 200:
                                    st.success(f"Deleted ({data['diagnoses_deleted']} diagnosis record(s) removed). "
                                               "Refresh to update the lists.")
                                    if st.session_state.get("doc_id") == delete_id:
                                        del st.session_state["doc_id"]
                                else:
                                    st.error(format_error(data))
                            except requests.exceptions.ConnectionError:
                                st.error("Server is unavailable. Please try again later.")

    elif st.session_state.role == "doctor":
        st.header("Doctor Dashboard")
        st.markdown("---")

        st.subheader("Pending Reviews")
        status_code, pending = api_get(st.session_state.auth, "/diagnosis/pending")
        if status_code != 200:
            st.error(f"Could not load pending reviews: {format_error(pending)}")
        elif not pending:
            st.caption("Nothing to review. 🎉")
        for record in pending if status_code == 200 else []:
            when = datetime.datetime.fromtimestamp(record["timestamp"]).strftime("%Y-%m-%d %H:%M")
            with st.expander(f"🕒 {record['requester']} — {when} — {record['question'][:60]}"):
                show_critical_banner(record.get("critical_alerts", []))
                if record.get("abnormal_labs"):
                    st.markdown("**Abnormal lab values (rule-checked)**")
                    show_lab_table(record["abnormal_labs"])
                if record.get("differential"):
                    st.markdown("**Differential (rule-based)**")
                    show_differential_table(record["differential"])
                st.markdown("**AI draft answer**")
                st.markdown(record["answer"])
                with st.form(f"review_{record['_id']}"):
                    action = st.radio("Decision", ["approve", "edit", "reject"], horizontal=True,
                                      format_func=lambda a: {"approve": "✅ Approve", "edit": "✏️ Edit",
                                                             "reject": "❌ Reject"}[a])
                    edited = st.text_area("Corrected answer (used only for Edit)", value=record["answer"], height=200)
                    note = st.text_input("Note to the patient (optional)")
                    if st.form_submit_button("Submit review"):
                        payload = {"action": action, "note": note or None}
                        if action == "edit":
                            payload["edited_answer"] = edited
                        status_code, data = api_post(st.session_state.auth, f"/diagnosis/{record['_id']}/review", payload)
                        if status_code == 200:
                            st.success(f"Saved: {data['review_status']}. Refresh to update the list.")
                        else:
                            st.error(format_error(data))

        st.markdown("---")
        st.subheader("View Patient Diagnosis History")
        status_code, mine = get_assignments(st.session_state.auth)
        my_patients = mine.get("patients", []) if status_code == 200 else []
        if not my_patients:
            st.info("No patients are assigned to you yet. Ask an administrator to assign patients.")
        with st.form("doctor_form"):
            patient_name_input = st.selectbox("Your patients", my_patients) if my_patients else None
            view_submitted = st.form_submit_button("View Diagnosis Records", disabled=not my_patients)
            if view_submitted:
                with st.spinner(f"Fetching diagnosis records for {patient_name_input}..."):
                    status_code, data = get_doctor_diagnosis(st.session_state.auth, patient_name_input)
                    if status_code == 200:
                        st.success(f"Found {len(data)} diagnosis record(s) for **{patient_name_input}**.")
                        st.markdown("---")
                        
                        # Loop through each diagnosis record and format it
                        for record in data:
                            st.info(f"**Diagnosis Record ID:** {record['_id']}")
                            st.write(f"**Date:** {datetime.datetime.fromtimestamp(record['timestamp']).strftime('%Y-%m-%d %H:%M:%S')}")
                            st.write(f"**Document ID:** {record['doc_id']}")
                            st.write(f"**Question:** {record['question']}")
                            st.write(f"**Model:** {record.get('model', 'unknown')}")
                            status = record.get("review_status", "pending_review")
                            st.write(f"**Review:** {REVIEW_BADGE.get(status, status)}"
                                     + (f" by Dr. {record['reviewed_by']}" if record.get("reviewed_by") else ""))
                            st.subheader("Diagnosis Answer")
                            # The 'answer' field contains markdown, so render it as such
                            st.markdown(record['answer'])
                            
                            st.subheader("Sources")
                            if record.get('sources'):
                                for source in record['sources']:
                                    st.write(f"- {source}")
                            else:
                                st.write("No sources found.")
                                
                            st.markdown("---")
                    else:
                        st.error(f"Failed to fetch records: {format_error(data)}")

    elif st.session_state.role == "admin":
        st.header("Admin Dashboard")
        st.markdown("---")

        st.subheader("Create User")
        with st.form("create_user_form"):
            new_username = st.text_input("Username")
            new_password = st.text_input("Password (min 6 chars)", type="password")
            new_full_name = st.text_input("Full name (optional)")
            new_role = st.selectbox("Role", ["doctor", "patient", "admin"])
            create_submitted = st.form_submit_button("Create User")
            if create_submitted:
                if new_username and new_password:
                    status_code, data = admin_create_user(
                        st.session_state.auth, new_username, new_password, new_role, new_full_name or None
                    )
                    if status_code == 200:
                        st.success(data.get("message", "User created."))
                    else:
                        st.error(f"Create user failed: {format_error(data)}")
                else:
                    st.warning("Please fill in all fields.")

        st.markdown("---")
        st.subheader("Doctor–Patient Assignments")
        st.caption("Doctors can only see the records of patients assigned to them.")
        users_status, users = admin_list_users(st.session_state.auth)
        users = users if users_status == 200 else []
        doctors = [u["username"] for u in users if u["role"] == "doctor"]
        patients = [u["username"] for u in users if u["role"] == "patient"]
        if doctors and patients:
            with st.form("assignment_form"):
                col1, col2 = st.columns(2)
                chosen_doctor = col1.selectbox("Doctor", doctors)
                chosen_patient = col2.selectbox("Patient", patients)
                col_a, col_b = st.columns(2)
                do_assign = col_a.form_submit_button("Assign")
                do_unassign = col_b.form_submit_button("Unassign")
                if do_assign or do_unassign:
                    status_code, data = admin_set_assignment(
                        st.session_state.auth, chosen_doctor, chosen_patient, remove=do_unassign
                    )
                    if status_code == 200:
                        st.success(data.get("message", "Done."))
                    else:
                        st.error(format_error(data))
        else:
            st.info("Create at least one doctor and one patient to make assignments.")
        status_code, assignments = get_assignments(st.session_state.auth)
        if status_code == 200 and assignments:
            st.table([
                {"Doctor": a["doctor"], "Patient": a["patient"],
                 "Since": datetime.datetime.fromtimestamp(a["assigned_at"]).strftime("%Y-%m-%d %H:%M")}
                for a in assignments
            ])

        st.markdown("---")
        st.subheader("All Users")
        if st.button("Refresh user list"):
            status_code, data = admin_list_users(st.session_state.auth)
            if status_code == 200:
                st.table(data)
            else:
                st.error(f"Failed to fetch users: {format_error(data)}")

        st.markdown("---")
        st.subheader("Audit Log")
        st.caption("Who did what, and when. Failed logins are recorded too.")
        col1, col2, col3 = st.columns([2, 2, 1])
        actor_filter = col1.text_input("Filter by user", key="audit_actor")
        action_filter = col2.selectbox("Filter by action", AUDIT_ACTIONS, key="audit_action")
        limit = col3.number_input("Show", min_value=10, max_value=1000, value=50, step=10, key="audit_limit")
        params = {"limit": int(limit)}
        if actor_filter:
            params["actor"] = actor_filter
        if action_filter != "(all)":
            params["action"] = action_filter
        try:
            response = requests.get(f"{API_URL}/audit", auth=st.session_state.auth, params=params)
            events = response.json() if response.status_code == 200 else []
        except requests.exceptions.ConnectionError:
            events = []
        if events:
            st.table([
                {
                    "Time": datetime.datetime.fromtimestamp(e["timestamp"]).strftime("%Y-%m-%d %H:%M:%S"),
                    "User": e["actor"],
                    "Role": e.get("role") or "—",
                    "Action": e["action"],
                    "Target": e.get("target") or "—",
                    "Details": ", ".join(f"{k}={v}" for k, v in (e.get("details") or {}).items()) or "—",
                }
                for e in events
            ])
        else:
            st.caption("No matching events.")

    else:
        st.warning("Your role is not recognized. Please contact support.")