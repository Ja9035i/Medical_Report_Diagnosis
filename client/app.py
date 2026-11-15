import streamlit as st
import requests
import json
from requests.auth import HTTPBasicAuth
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
if "role" not in st.session_state:
    st.session_state.role = ""
if "auth" not in st.session_state:
    st.session_state.auth = None

# API Functions :

# 1. Signup Function (public signup always creates a patient account)
def signup_user(username, password):
    try:
        response = requests.post(
            f"{API_URL}/auth/signup",
            json={"username": username, "password": password}
        )
        return response.status_code, response.json()
    except requests.exceptions.ConnectionError:
        return 503, {"detail": "Server is unavailable. Please try again later."}
    
# 2. Authenticate Function
def authenticate_user(username, password):
    try:
        response = requests.get(
            f"{API_URL}/auth/login",
            auth=HTTPBasicAuth(username, password)
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
def admin_create_user(auth, username, password, role):
    try:
        response = requests.post(
            f"{API_URL}/auth/users",
            auth=auth,
            json={"username": username, "password": password, "role": role}
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


def format_error(data):
    """FastAPI returns a string detail, or a list of validation errors (422)."""
    detail = data.get("detail", "Unknown error") if isinstance(data, dict) else data
    if isinstance(detail, list):
        return "; ".join(err.get("msg", str(err)) for err in detail)
    return detail

# Sidebar and Authentication Flow
st.sidebar.title("Navigation")
st.sidebar.markdown("---")

if st.session_state.logged_in:
    st.sidebar.success(f"Logged in as **{st.session_state.username}** ({st.session_state.role})")
    if st.sidebar.button("Logout"):
        st.session_state.logged_in = False
        st.session_state.username = ""
        st.session_state.role = ""
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
                st.session_state.auth = HTTPBasicAuth(login_username, login_password)
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
    if st.sidebar.button("Signup"):
        if signup_username and signup_password:
            status_code, data = signup_user(signup_username, signup_password)
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
                            st.success("Diagnosis Generated!")
                            st.write("---")
                            st.subheader("Diagnosis Result")
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
                        else:
                            st.error(f"Diagnosis failed: {format_error(data)}")
        else:
            st.info("You have no reports yet. Upload a report above to get started.")

    elif st.session_state.role == "doctor":
        st.header("Doctor Dashboard")
        st.markdown("---")

        st.subheader("View Patient Diagnosis History")
        with st.form("doctor_form"):
            patient_name_input = st.text_input("Enter Patient's Username:")
            view_submitted = st.form_submit_button("View Diagnosis Records")
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
            new_role = st.selectbox("Role", ["doctor", "patient", "admin"])
            create_submitted = st.form_submit_button("Create User")
            if create_submitted:
                if new_username and new_password:
                    status_code, data = admin_create_user(
                        st.session_state.auth, new_username, new_password, new_role
                    )
                    if status_code == 200:
                        st.success(data.get("message", "User created."))
                    else:
                        st.error(f"Create user failed: {format_error(data)}")
                else:
                    st.warning("Please fill in all fields.")

        st.markdown("---")
        st.subheader("All Users")
        if st.button("Refresh user list"):
            status_code, data = admin_list_users(st.session_state.auth)
            if status_code == 200:
                st.table(data)
            else:
                st.error(f"Failed to fetch users: {format_error(data)}")

    else:
        st.warning("Your role is not recognized. Please contact support.")