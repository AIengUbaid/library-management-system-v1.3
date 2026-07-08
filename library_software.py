import streamlit as st
import pandas as pd
from datetime import datetime, date
import os
from supabase import create_client, Client
from dotenv import load_dotenv
load_dotenv()

# ── CONFIGURATION ──────────────────────────────────────────────────────────────

SUPABASE_URL   = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY   = os.environ.get("SUPABASE_KEY", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "") or None  # fail closed if unset

LIBRARY_NAME = "TOPPERS CORNER Library"

EXAM_OPTIONS = [
    "UPSC", "SSC", "Banking", "Railways", "State PSC", "NEET", "JEE",
    "Judiciary", "Teaching (CTET/TET)", "Defence (NDA/CDS)", "Other",
]

REQUIRED_TABLES = ["students", "fee"]

SETUP_SQL = """-- Run ONCE in Supabase → SQL Editor → New Query

CREATE TABLE IF NOT EXISTS students (
    id              BIGSERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    parentage       TEXT NOT NULL,
    student_aadhar  TEXT NOT NULL,
    parent_aadhar   TEXT NOT NULL,
    phone           TEXT NOT NULL,
    parent_phone    TEXT NOT NULL,
    seat_no         INTEGER,
    gender          TEXT NOT NULL,
    exam_name       TEXT NOT NULL,
    join_date       TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'Active',
    total_fee       NUMERIC NOT NULL DEFAULT 0,
    paid_fee        NUMERIC NOT NULL DEFAULT 0,
    pending_fee     NUMERIC NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS fee (
    id          BIGSERIAL PRIMARY KEY,
    student_id  BIGINT NOT NULL REFERENCES students(id),
    amount      NUMERIC NOT NULL,
    date        TEXT NOT NULL,
    status      TEXT NOT NULL
);

ALTER TABLE students DISABLE ROW LEVEL SECURITY;
ALTER TABLE fee      DISABLE ROW LEVEL SECURITY;"""

st.set_page_config(page_title="TOPPERS CORNER Library", layout="wide")

# ── SESSION STATE DEFAULTS ─────────────────────────────────────────────────────
# Messages and settings are kept in session — no extra Supabase tables needed.

if "messages" not in st.session_state:
    st.session_state.messages = []          # [{student_name, sender, text, ts}]

if "daily_log" not in st.session_state:
    st.session_state.daily_log = []         # [{name, student_id, shift, date, time_in, purpose}]

if "wifi_status" not in st.session_state:
    st.session_state.wifi_status = "OFF"

if "lib_name" not in st.session_state:
    st.session_state.lib_name = LIBRARY_NAME

if "day_timing" not in st.session_state:
    st.session_state.day_timing = "8:00 AM – 8:00 PM"

if "night_timing" not in st.session_state:
    st.session_state.night_timing = "8:00 PM – 8:00 AM"

# ── SUPABASE CLIENT ────────────────────────────────────────────────────────────

@st.cache_resource
def get_supabase() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        st.error(
            "⚠️ **Supabase credentials missing.**  "
            "Set `SUPABASE_URL` and `SUPABASE_KEY` in Secrets and restart."
        )
        st.stop()
    try:
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        st.error(f"⚠️ **Cannot connect to Supabase:** {e}")
        st.stop()


supabase = get_supabase()

# ── DB HEALTH CHECK ────────────────────────────────────────────────────────────

def check_db_tables() -> list[str]:
    missing = []
    for t in REQUIRED_TABLES:
        try:
            supabase.table(t).select("id").limit(1).execute()
        except Exception:
            missing.append(t)
    return missing


def show_setup_banner(missing: list[str]):
    st.error(
        f"⚠️ **Database not ready.** Missing tables: `{'`, `'.join(missing)}`  \n"
        "Run the SQL below in **Supabase → SQL Editor → New Query**, then refresh."
    )
    with st.expander("📋 Setup SQL", expanded=True):
        st.code(SETUP_SQL, language="sql")
    st.stop()


_missing = check_db_tables()
if _missing:
    show_setup_banner(_missing)

# ── MASKING ────────────────────────────────────────────────────────────────────

def mask_phone(v):
    s = str(v).strip() if v else ""
    return (s[:4] + "X" * (len(s) - 4)) if len(s) >= 6 else (s or "Not provided")


def mask_aadhar(v):
    s = str(v).strip() if v else ""
    return (s[:6] + "X" * (len(s) - 6)) if len(s) >= 6 else (s or "Not provided")


def mask_df(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    for col in ("phone", "parent_phone"):
        if col in d.columns:
            d[col] = d[col].apply(lambda v: mask_phone(v) if pd.notna(v) and str(v).strip() else "")
    for col in ("student_aadhar", "parent_aadhar"):
        if col in d.columns:
            d[col] = d[col].apply(lambda v: mask_aadhar(v) if pd.notna(v) and str(v).strip() else "")
    return d

# ── ERROR HELPER ───────────────────────────────────────────────────────────────

def _db_err(ctx: str, exc: Exception) -> str:
    msg = str(exc)
    if "PGRST205" in msg or "schema cache" in msg:
        return f"{ctx}: table not found — run the setup SQL."
    if "401" in msg or "403" in msg or "JWT" in msg:
        return f"{ctx}: permission denied — check your Supabase key."
    if "duplicate key" in msg or "unique" in msg.lower():
        return f"{ctx}: duplicate record already exists."
    if "foreign key" in msg.lower():
        return f"{ctx}: student does not exist."
    return f"{ctx}: {msg}"


def _valid_aadhar(v: str) -> bool:
    return v.isdigit() and len(v) == 12

# ── STUDENT FUNCTIONS ──────────────────────────────────────────────────────────

def get_all_students() -> pd.DataFrame:
    try:
        r = supabase.table("students").select("*").execute()
        return pd.DataFrame(r.data) if r.data else pd.DataFrame()
    except Exception as e:
        st.error(_db_err("Error loading students", e))
        return pd.DataFrame()


def get_student_by_id(sid: int):
    try:
        r = supabase.table("students").select("*").eq("id", sid).execute()
        return r.data[0] if r.data else None
    except Exception as e:
        st.error(_db_err("Error fetching student", e))
        return None


def _phone_exists(phone: str, exclude_id=None) -> bool:
    q = supabase.table("students").select("id").eq("phone", phone)
    if exclude_id:
        q = q.neq("id", exclude_id)
    return len(q.execute().data) > 0


def _seat_taken(seat: int, exclude_id=None) -> bool:
    q = supabase.table("students").select("id").eq("seat_no", seat)
    if exclude_id:
        q = q.neq("id", exclude_id)
    return len(q.execute().data) > 0


def add_student(name, parentage, student_aadhar, parent_aadhar,
                phone, parent_phone, gender, exam_name, join_date_str):
    name           = name.strip()
    parentage      = parentage.strip()
    student_aadhar = student_aadhar.strip()
    parent_aadhar  = parent_aadhar.strip()
    phone          = phone.strip()
    parent_phone   = parent_phone.strip()

    if not name:                                          return False, "Student name is required."
    if not parentage:                                     return False, "Parentage is required."
    if not phone or not phone.isdigit() or len(phone) != 10:
                                                          return False, "Student phone must be exactly 10 digits."
    if not parent_phone or not parent_phone.isdigit() or len(parent_phone) != 10:
                                                          return False, "Parent phone must be exactly 10 digits."
    if not _valid_aadhar(student_aadhar):                 return False, "Student Aadhar must be exactly 12 digits."
    if not _valid_aadhar(parent_aadhar):                  return False, "Parent Aadhar must be exactly 12 digits."
    if not exam_name:                                     return False, "Please select an exam."

    try:
        if _phone_exists(phone):
            return False, f"Phone {phone} is already registered to another student."
        r = supabase.table("students").insert({
            "name": name, "parentage": parentage,
            "student_aadhar": student_aadhar, "parent_aadhar": parent_aadhar,
            "phone": phone, "parent_phone": parent_phone,
            "gender": gender, "exam_name": exam_name,
            "join_date": join_date_str, "status": "Active",
            "total_fee": 0, "paid_fee": 0, "pending_fee": 0,
        }).execute()
        if not r.data:
            return False, "Not saved — Supabase returned no confirmation. Check table permissions."
        return True, r.data[0]["id"]
    except Exception as e:
        return False, _db_err("Could not register student", e)


def assign_seat(sid: int, seat: int):
    if seat <= 0:
        return False, "Seat number must be greater than 0."
    try:
        if _seat_taken(seat, exclude_id=sid):
            return False, f"Seat {seat} is already taken by another student."
        r = supabase.table("students").update({"seat_no": seat}).eq("id", sid).execute()
        if not r.data: return False, "Not updated — student not found."
        return True, f"Seat {seat} assigned successfully."
    except Exception as e:
        return False, _db_err("Could not assign seat", e)


def update_student_status(sid: int, status: str):
    try:
        r = supabase.table("students").update({"status": status}).eq("id", sid).execute()
        if not r.data: return False, "Not updated — student not found."
        return True, "Status updated."
    except Exception as e:
        return False, _db_err("Could not update status", e)


def update_join_date(sid: int, new_date: str):
    try:
        r = supabase.table("students").update({"join_date": new_date}).eq("id", sid).execute()
        if not r.data: return False, "Not updated — student not found."
        return True, "Joining date updated."
    except Exception as e:
        return False, _db_err("Could not update joining date", e)


def delete_student(sid: int):
    try:
        supabase.table("fee").delete().eq("student_id", sid).execute()
        r = supabase.table("students").delete().eq("id", sid).execute()
        if not r.data: return False, "Student not found or already deleted."
        return True, "Student and all fee records deleted."
    except Exception as e:
        return False, _db_err("Could not delete student", e)

# ── FEE FUNCTIONS ──────────────────────────────────────────────────────────────

def add_fee(sid: int, amount: float, status: str):
    if not amount or amount <= 0:
        return False, "Amount must be greater than ₹0."
    try:
        student = get_student_by_id(sid)
        if student is None:
            return False, "Student not found."
        r = supabase.table("fee").insert({
            "student_id": sid,
            "amount": amount,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "status": status,
        }).execute()
        if not r.data:
            return False, "Not saved — Supabase returned no confirmation."

        new_total   = float(student.get("total_fee") or 0) + amount
        new_paid    = float(student.get("paid_fee") or 0)    + (amount if status == "Paid"    else 0)
        new_pending = float(student.get("pending_fee") or 0) + (amount if status == "Pending" else 0)
        supabase.table("students").update({
            "total_fee": new_total, "paid_fee": new_paid, "pending_fee": new_pending,
        }).eq("id", sid).execute()
        return True, "Fee saved to Supabase."
    except Exception as e:
        return False, _db_err("Could not save fee", e)


def get_fees_for_student(sid: int) -> pd.DataFrame:
    try:
        r = supabase.table("fee").select("*").eq("student_id", sid).order("id", desc=True).execute()
        return pd.DataFrame(r.data) if r.data else pd.DataFrame()
    except Exception as e:
        st.error(_db_err("Error loading fee history", e))
        return pd.DataFrame()


def get_students_with_pending_fees() -> pd.DataFrame:
    try:
        r = supabase.table("students").select("*").gt("pending_fee", 0).order("pending_fee", desc=True).execute()
        return pd.DataFrame(r.data) if r.data else pd.DataFrame()
    except Exception as e:
        st.error(_db_err("Error loading pending fees", e))
        return pd.DataFrame()

# ── RECEIPT HTML ───────────────────────────────────────────────────────────────

def receipt_html(student: dict, fee_row, lib_name: str) -> str:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Receipt #{fee_row['id']}</title>
<style>
  body{{font-family:Arial,sans-serif;padding:40px;color:#222}}
  .box{{max-width:600px;margin:auto;border:1px solid #ccc;padding:30px;border-radius:8px}}
  h1{{text-align:center;margin-bottom:4px}}.sub{{text-align:center;color:#666}}
  table{{width:100%;border-collapse:collapse;margin-top:20px}}
  td{{padding:8px 4px;border-bottom:1px solid #eee}}td.l{{font-weight:bold;width:40%}}
  .amt{{font-size:1.5em;font-weight:bold;text-align:center;margin:20px 0}}
  .paid{{color:#1a7f37}}.pending{{color:#b54708}}
  .ft{{text-align:center;color:#888;font-size:.85em;margin-top:24px}}
</style></head><body><div class="box">
<h1>{lib_name}</h1><p class="sub">Fee Payment Receipt</p>
<table>
  <tr><td class="l">Receipt No.</td><td>#{fee_row['id']}</td></tr>
  <tr><td class="l">Student Name</td><td>{student['name']}</td></tr>
  <tr><td class="l">Student ID</td><td>{student['id']}</td></tr>
  <tr><td class="l">Phone</td><td>{student['phone']}</td></tr>
  <tr><td class="l">Date</td><td>{fee_row['date']}</td></tr>
  <tr><td class="l">Status</td><td class="{fee_row['status'].lower()}">{fee_row['status']}</td></tr>
</table>
<div class="amt">&#8377;{float(fee_row['amount']):.2f}</div>
<p class="ft">Generated {ts} &middot; System-generated receipt</p>
</div></body></html>"""

# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════

st.sidebar.title(f"📚 {st.session_state.lib_name}")
admin_mode     = st.sidebar.checkbox("🔐 Admin Mode")
admin_show_full = False

if admin_mode:
    if ADMIN_PASSWORD is None:
        st.sidebar.error("⚠️ Admin password not configured on this server.")
        admin_mode = False
    else:
        pw = st.sidebar.text_input("Admin Password", type="password")
        if pw != ADMIN_PASSWORD:
            if pw:
                st.sidebar.error("❌ Incorrect password.")
            admin_mode = False
        else:
            st.sidebar.success("✅ Logged in as Admin")
            st.sidebar.divider()
            admin_show_full = st.sidebar.toggle(
                "🔓 Show Full Aadhar & Phone", value=False,
                help="Toggle ON to see unmasked Aadhar and phone numbers.",
            )

st.sidebar.divider()
st.sidebar.markdown(f"📡 **WiFi:** {'🟢 ON' if st.session_state.wifi_status == 'ON' else '🔴 OFF'}")
st.sidebar.caption("Library Management System v2.0")

# ══════════════════════════════════════════════════════════════════════════════
# TAB LAYOUT
# ══════════════════════════════════════════════════════════════════════════════

if admin_mode:
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📋 Register Student",
        "💰 Fee Management",
        "🔄 Manage Status",
        "⚙️ Settings",
        "📊 Dashboard",
    ])
else:
    tab1, tab2, tab3, tab4 = st.tabs([
        "👤 View Student Info",
        "💬 Messages",
        "📝 Daily Attendance",
        "⚧ Gender Ratio",
    ])

# ══════════════════════════════════════════════════════════════════════════════
# ADMIN — TAB 1: REGISTER STUDENT + DELETE
# ══════════════════════════════════════════════════════════════════════════════

if admin_mode:
    with tab1:
        st.header("Library Registration Form")

        c1, c2, c3 = st.columns(3)
        with c1: name       = st.text_input("Student Name")
        with c2: parentage  = st.text_input("Parentage (Father's / Guardian's Name)")
        with c3: gender     = st.selectbox("Gender", ["Male", "Female"])

        c1, c2 = st.columns(2)
        with c1: student_aadhar = st.text_input("Student Aadhar Number", max_chars=12)
        with c2: parent_aadhar  = st.text_input("Parent Aadhar Number",  max_chars=12)

        c1, c2 = st.columns(2)
        with c1: phone        = st.text_input("Student Phone", max_chars=10)
        with c2: parent_phone = st.text_input("Parent Phone",  max_chars=10)

        c1, c2 = st.columns(2)
        with c1:
            exam_choice = st.selectbox("Exam Preparing For", EXAM_OPTIONS)
            exam_name   = exam_choice
            if exam_choice == "Other":
                exam_name = st.text_input("Specify exam name")
        with c2:
            join_date_input = st.date_input("Joining Date", value=date.today())

        if st.button("✅ Register Student", key="reg_btn"):
            with st.spinner("Saving to Supabase…"):
                ok, result = add_student(
                    name, parentage, student_aadhar, parent_aadhar,
                    phone, parent_phone, gender, exam_name,
                    join_date_input.strftime("%Y-%m-%d"),
                )
            if ok:
                st.success(f"✅ Registered! Student ID: **{result}**")
                st.rerun()
            else:
                st.error(f"❌ {result}")

        # ── All Students table ──
        st.divider()
        st.subheader("All Students")
        students_df = get_all_students()

        if not students_df.empty:
            disp = students_df if admin_show_full else mask_df(students_df)
            st.dataframe(disp, use_container_width=True)

            # ── Assign Seat ──
            st.divider()
            st.subheader("Assign Seat")
            c1, c2 = st.columns(2)
            with c1:
                seat_sid = st.selectbox(
                    "Student", students_df["id"].tolist(),
                    format_func=lambda x: f"{students_df.loc[students_df['id']==x,'name'].values[0]} (ID {x})",
                    key="seat_sid",
                )
            with c2:
                seat_no = st.number_input("Seat No.", min_value=1, step=1, key="seat_no_input")
            if st.button("Assign Seat", key="assign_seat_btn"):
                with st.spinner("Saving…"):
                    ok, msg = assign_seat(int(seat_sid), int(seat_no))
                st.success(f"✅ {msg}") if ok else st.error(f"❌ {msg}")
                if ok: st.rerun()

            # ── Update Joining Date ──
            st.divider()
            st.subheader("Update Joining Date")
            jd_sid = st.selectbox(
                "Student", students_df["id"].tolist(),
                format_func=lambda x: f"{students_df.loc[students_df['id']==x,'name'].values[0]} (ID {x})",
                key="jd_sid",
            )
            cur = get_student_by_id(int(jd_sid))
            try:
                default_d = datetime.strptime(cur["join_date"], "%Y-%m-%d").date() if cur and cur.get("join_date") else date.today()
            except ValueError:
                default_d = date.today()
            new_jd = st.date_input("New Joining Date", value=default_d, key="new_jd")
            if st.button("Update Date", key="upd_date_btn"):
                with st.spinner("Saving…"):
                    ok, msg = update_join_date(int(jd_sid), new_jd.strftime("%Y-%m-%d"))
                st.success(f"✅ {msg}") if ok else st.error(f"❌ {msg}")
                if ok: st.rerun()

            # ── Delete Student ──
            st.divider()
            st.subheader("🗑️ Delete Student")
            st.warning("This permanently removes the student and all their fee records from Supabase.")
            del_sid = st.selectbox(
                "Select Student to Delete",
                students_df["id"].tolist(),
                format_func=lambda x: f"{students_df.loc[students_df['id']==x,'name'].values[0]} (ID {x})",
                key="del_sid",
            )
            confirm = st.checkbox("I understand this cannot be undone", key="del_confirm")
            if st.button("🗑️ Delete Student", type="primary", disabled=not confirm, key="del_btn"):
                with st.spinner("Deleting…"):
                    ok, msg = delete_student(int(del_sid))
                st.success(f"✅ {msg}") if ok else st.error(f"❌ {msg}")
                if ok: st.rerun()
        else:
            st.info("No students registered yet.")

# ══════════════════════════════════════════════════════════════════════════════
# ADMIN — TAB 2: FEE MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

    with tab2:
        st.header("💰 Fee Management")
        students_df = get_all_students()

        if not students_df.empty:
            fee_sid = st.selectbox(
                "Select Student",
                students_df["id"].tolist(),
                format_func=lambda x: f"{students_df.loc[students_df['id']==x,'name'].values[0]} (ID {x})",
                key="fee_sid",
            )
            student = get_student_by_id(int(fee_sid))

            if student is None:
                st.error("Student not found. Reload the page.")
            else:
                c1, c2, c3 = st.columns(3)
                with c1: st.metric("Total Fee", f"₹{float(student['total_fee']):.2f}")
                with c2: st.metric("Paid",       f"₹{float(student['paid_fee']):.2f}")
                with c3: st.metric("Pending",    f"₹{float(student['pending_fee']):.2f}")

                st.divider()
                c1, c2 = st.columns(2)
                with c1: amount     = st.number_input("Amount (₹)", min_value=1, step=100, key="fee_amt")
                with c2: fee_status = st.selectbox("Status", ["Paid", "Pending"], key="fee_status")

                if st.button("Add Fee Record", key="add_fee_btn"):
                    with st.spinner("Saving to Supabase…"):
                        ok, msg = add_fee(int(fee_sid), float(amount), fee_status)
                    st.success(f"✅ {msg}") if ok else st.error(f"❌ {msg}")
                    if ok: st.rerun()

                st.divider()
                st.subheader("Payment History & Receipts")
                fees_df = get_fees_for_student(int(fee_sid))
                if not fees_df.empty:
                    st.dataframe(fees_df, use_container_width=True)
                    r_opts = {
                        int(row["id"]): f"Receipt #{int(row['id'])} — ₹{float(row['amount']):.2f} ({row['status']}, {row['date']})"
                        for _, row in fees_df.iterrows()
                    }
                    r_id  = st.selectbox("Generate receipt for", list(r_opts.keys()), format_func=lambda x: r_opts[x], key="receipt_sel")
                    r_row = fees_df[fees_df["id"] == r_id].iloc[0]
                    html  = receipt_html(student, r_row, st.session_state.lib_name)
                    st.download_button(
                        "⬇️ Download Receipt (HTML)", data=html,
                        file_name=f"receipt_{student['name'].replace(' ','_')}_{r_id}.html",
                        mime="text/html", key="dl_receipt",
                    )
                    st.caption("Open in browser → Print → Save as PDF.")
                else:
                    st.info("No transactions recorded yet for this student.")
        else:
            st.info("Register a student first.")

# ══════════════════════════════════════════════════════════════════════════════
# ADMIN — TAB 3: MANAGE STATUS
# ══════════════════════════════════════════════════════════════════════════════

    with tab3:
        st.header("🔄 Manage Student Status")
        students_df = get_all_students()

        if not students_df.empty:
            st_sid = st.selectbox(
                "Select Student",
                students_df["id"].tolist(),
                format_func=lambda x: f"{students_df.loc[students_df['id']==x,'name'].values[0]} (ID {x})",
                key="st_sid",
            )
            cur_status = students_df.loc[students_df["id"] == st_sid, "status"].values[0]
            status_options = ["Active", "Inactive", "Suspended", "Left"]
            new_status = st.selectbox(
                "New Status", status_options,
                index=status_options.index(cur_status) if cur_status in status_options else 0,
                key="new_status",
            )
            if st.button("Update Status", key="upd_status_btn"):
                with st.spinner("Saving…"):
                    ok, msg = update_student_status(int(st_sid), new_status)
                st.success(f"✅ {msg}") if ok else st.error(f"❌ {msg}")
                if ok: st.rerun()
        else:
            st.info("Register a student first.")

# ══════════════════════════════════════════════════════════════════════════════
# ADMIN — TAB 4: SETTINGS
# ══════════════════════════════════════════════════════════════════════════════

    with tab4:
        st.header("⚙️ Library Settings")
        st.caption("Settings are controlled by admin only and apply for the current session.")

        # ── Library Name ──
        st.subheader("Library Profile")
        new_lib_name = st.text_input("Library Name", value=st.session_state.lib_name, key="lib_name_input")
        if st.button("Save Library Name", key="save_lib_name"):
            if new_lib_name.strip():
                st.session_state.lib_name = new_lib_name.strip()
                st.success(f"✅ Library name updated to **{st.session_state.lib_name}**")
                st.rerun()
            else:
                st.error("❌ Library name cannot be empty.")

        st.divider()

        # ── WiFi Status ──
        st.subheader("📡 WiFi Control")
        c1, c2 = st.columns([1, 2])
        with c1:
            wifi_choice = st.radio(
                "WiFi Status", ["ON", "OFF"],
                index=0 if st.session_state.wifi_status == "ON" else 1,
                key="wifi_radio",
            )
        with c2:
            if st.session_state.wifi_status == "ON":
                st.success("🟢 WiFi is currently ON")
            else:
                st.error("🔴 WiFi is currently OFF")
        if st.button("Update WiFi Status", key="upd_wifi_btn"):
            st.session_state.wifi_status = wifi_choice
            st.success(f"✅ WiFi set to **{wifi_choice}**")
            st.rerun()

        st.divider()

        # ── Library Timings ──
        st.subheader("🕐 Library Timings")
        c1, c2 = st.columns(2)
        with c1:
            new_day = st.text_input("Day Shift Timing", value=st.session_state.day_timing, key="day_time")
        with c2:
            new_night = st.text_input("Night Shift Timing", value=st.session_state.night_timing, key="night_time")
        if st.button("Save Timings", key="save_timings"):
            st.session_state.day_timing   = new_day.strip() or st.session_state.day_timing
            st.session_state.night_timing = new_night.strip() or st.session_state.night_timing
            st.success("✅ Timings updated.")
            st.rerun()

        st.divider()

        # ── Break Times ──
        st.subheader("☕ Break Times")
        st.info("Girls: 1:00 PM – 2:00 PM")
        st.info("Boys: No fixed break time")

        st.divider()

        # ── DB Status ──
        st.subheader("🗄️ Database Status")
        if st.button("Check Tables", key="check_tables_btn"):
            with st.spinner("Checking…"):
                missing = check_db_tables()
            if missing:
                st.error(f"❌ Missing: `{'`, `'.join(missing)}`")
                with st.expander("Setup SQL"):
                    st.code(SETUP_SQL, language="sql")
            else:
                st.success("✅ All tables present and accessible.")

# ══════════════════════════════════════════════════════════════════════════════
# ADMIN — TAB 5: DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

    with tab5:
        st.header("📊 Dashboard")
        students_df = get_all_students()

        c1, c2, c3, c4 = st.columns(4)
        total     = len(students_df)
        active    = len(students_df[students_df["status"] == "Active"]) if not students_df.empty else 0
        pending_t = students_df["pending_fee"].astype(float).sum() if not students_df.empty else 0
        paid_t    = students_df["paid_fee"].astype(float).sum() if not students_df.empty else 0

        with c1: st.metric("Total Students", total)
        with c2: st.metric("Active",          active)
        with c3: st.metric("Total Paid",      f"₹{paid_t:.2f}")
        with c4: st.metric("Total Pending",   f"₹{pending_t:.2f}")

        st.divider()
        st.subheader("⚠️ Students with Pending Fees")
        pending_df = get_students_with_pending_fees()
        if not pending_df.empty:
            st.caption(f"{len(pending_df)} student(s) have outstanding fees.")
            p_disp = pending_df if admin_show_full else mask_df(pending_df)
            cols   = [c for c in ["id", "name", "phone", "seat_no", "status", "pending_fee"] if c in p_disp.columns]
            st.dataframe(p_disp[cols], use_container_width=True)
        else:
            st.success("✅ No pending fees — everyone is up to date.")

        st.divider()
        st.subheader("📋 All Students — Full Report")
        if not students_df.empty:
            st.dataframe(students_df if admin_show_full else mask_df(students_df), use_container_width=True)
        else:
            st.info("No student data yet.")

# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC — TAB 1: VIEW STUDENT INFO
# ══════════════════════════════════════════════════════════════════════════════

else:
    with tab1:
        st.header("👤 Student Information")
        st.caption("Search by your Student ID. Aadhar and phone numbers are masked for privacy.")

        # ── WiFi banner ──
        if st.session_state.wifi_status == "ON":
            st.success("📡 WiFi is **ON**")
        else:
            st.error("📡 WiFi is **OFF**")

        st.divider()

        sid_input = st.number_input("Enter Your Student ID", min_value=1, step=1, key="pub_sid")
        if st.button("🔍 Search", key="pub_search_btn"):
            with st.spinner("Looking up…"):
                student = get_student_by_id(int(sid_input))
            if student:
                st.subheader(f"📌 {student['name']}")
                c1, c2 = st.columns(2)
                with c1:
                    st.metric("Parentage",  student.get("parentage") or "—")
                    st.metric("Seat No.",   student["seat_no"] if student.get("seat_no") else "Not assigned")
                    st.metric("Status",     student["status"])
                    st.metric("Exam",       student.get("exam_name") or "—")
                    st.metric("Joined",     student.get("join_date") or "—")
                    st.metric("Gender",     student.get("gender") or "—")
                with c2:
                    st.metric("Phone",          mask_phone(student.get("phone", "")))
                    st.metric("Parent Phone",   mask_phone(student.get("parent_phone", "")))
                    st.metric("Student Aadhar", mask_aadhar(student.get("student_aadhar", "")))
                    st.metric("Parent Aadhar",  mask_aadhar(student.get("parent_aadhar", "")))

                st.divider()
                c1, c2, c3 = st.columns(3)
                with c1: st.metric("Total Fee", f"₹{float(student['total_fee']):.2f}")
                with c2: st.metric("Paid",       f"₹{float(student['paid_fee']):.2f}")
                with c3: st.metric("Pending",    f"₹{float(student['pending_fee']):.2f}")

                st.divider()
                st.subheader("🕐 Library Timings")
                c1, c2 = st.columns(2)
                with c1: st.info(f"☀️ Day Shift: {st.session_state.day_timing}")
                with c2: st.info(f"🌙 Night Shift: {st.session_state.night_timing}")
            else:
                st.error("❌ Student not found. Please check your ID.")

# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC — TAB 2: MESSAGES
# ══════════════════════════════════════════════════════════════════════════════

    with tab2:
        st.header("💬 Messages")
        st.caption("Anyone can send a message to any student. All messages are visible to everyone.")

        # ── Send a message ──
        st.subheader("Send a Message")
        students_df = get_all_students()

        if students_df.empty:
            st.info("No students registered yet.")
        else:
            student_opts = {
                int(row["id"]): f"{row['name']} (ID {int(row['id'])})"
                for _, row in students_df.iterrows()
            }
            c1, c2 = st.columns([2, 1])
            with c1:
                to_sid = st.selectbox(
                    "Send to", list(student_opts.keys()),
                    format_func=lambda x: student_opts[x],
                    key="msg_to_sid",
                )
            with c2:
                sender_name = st.text_input("Your name (optional)", placeholder="Anonymous", key="msg_sender")

            msg_text = st.text_area("Message", key="msg_text", height=80, max_chars=500)

            if st.button("📨 Send Message", key="send_msg_btn"):
                msg_text_stripped = msg_text.strip()
                if not msg_text_stripped:
                    st.error("❌ Message cannot be empty.")
                else:
                    to_name    = student_opts[to_sid]
                    from_label = sender_name.strip() if sender_name.strip() else "Anonymous"
                    st.session_state.messages.append({
                        "to":     to_name,
                        "from":   from_label,
                        "text":   msg_text_stripped,
                        "ts":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    })
                    st.success("✅ Message sent.")
                    st.rerun()

        # ── All messages ──
        st.divider()
        st.subheader("All Messages")

        if not st.session_state.messages:
            st.info("No messages yet. Be the first to send one!")
        else:
            for m in reversed(st.session_state.messages):
                st.markdown(f"**{m['from']}** → *{m['to']}* &nbsp;&nbsp; `{m['ts']}`")
                st.write(m["text"])
                st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC — TAB 3: DAILY ATTENDANCE
# ══════════════════════════════════════════════════════════════════════════════

    with tab3:
        st.header("📝 Daily Attendance")
        st.caption("Fill in your details every time you enter the library.")

        students_df = get_all_students()

        if students_df.empty:
            st.info("No students registered yet.")
        else:
            student_opts = {
                int(row["id"]): f"{row['name']} (ID {int(row['id'])})"
                for _, row in students_df.iterrows()
            }

            with st.form("daily_form", clear_on_submit=True):
                st.subheader("Mark Your Attendance")

                c1, c2 = st.columns(2)
                with c1:
                    att_sid = st.selectbox(
                        "Select Your Name",
                        list(student_opts.keys()),
                        format_func=lambda x: student_opts[x],
                    )
                with c2:
                    shift = st.selectbox("Shift", ["Day (8 AM – 8 PM)", "Night (8 PM – 8 AM)"])

                c1, c2 = st.columns(2)
                with c1:
                    att_date = st.date_input("Date", value=date.today())
                with c2:
                    time_in = st.time_input("Time In", value=datetime.now().time())

                purpose = st.text_input("Purpose / Subject (optional)", placeholder="e.g. UPSC revision, Reading")

                submitted = st.form_submit_button("✅ Mark Attendance")

            if submitted:
                st.session_state.daily_log.append({
                    "student_id":   att_sid,
                    "name":         student_opts[att_sid],
                    "shift":        shift,
                    "date":         att_date.strftime("%Y-%m-%d"),
                    "time_in":      time_in.strftime("%I:%M %p"),
                    "purpose":      purpose.strip() or "—",
                    "marked_at":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
                st.success(f"✅ Attendance marked for **{student_opts[att_sid]}**!")
                st.rerun()

        # ── Today's attendance log ──
        st.divider()
        today_str = date.today().strftime("%Y-%m-%d")
        today_log = [e for e in st.session_state.daily_log if e["date"] == today_str]

        st.subheader(f"Today's Attendance — {date.today().strftime('%d %b %Y')}")
        if not today_log:
            st.info("No entries yet for today.")
        else:
            st.caption(f"{len(today_log)} student(s) present today.")
            log_df = pd.DataFrame(today_log)[["name", "shift", "time_in", "purpose", "marked_at"]]
            log_df.columns = ["Name", "Shift", "Time In", "Purpose", "Marked At"]
            st.dataframe(log_df, use_container_width=True, hide_index=True)

        # ── Full history ──
        if len(st.session_state.daily_log) > len(today_log):
            with st.expander("📅 View full attendance history"):
                hist_df = pd.DataFrame(st.session_state.daily_log)[
                    ["date", "name", "shift", "time_in", "purpose"]
                ]
                hist_df.columns = ["Date", "Name", "Shift", "Time In", "Purpose"]
                hist_df = hist_df.sort_values("Date", ascending=False)
                st.dataframe(hist_df, use_container_width=True, hide_index=True)

# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC — TAB 4: GENDER RATIO
# ══════════════════════════════════════════════════════════════════════════════

    with tab4:
        st.header("⚧ Gender Ratio")
        st.caption("Live gender breakdown of all registered students.")

        students_df = get_all_students()

        if students_df.empty:
            st.info("No students registered yet.")
        else:
            total   = len(students_df)
            male    = len(students_df[students_df["gender"].str.lower() == "male"])
            female  = len(students_df[students_df["gender"].str.lower() == "female"])
            other   = total - male - female

            # ── Big numbers ──
            c1, c2, c3, c4 = st.columns(4)
            with c1: st.metric("Total Students", total)
            with c2: st.metric("👨 Male",   male)
            with c3: st.metric("👩 Female", female)
            with c4: st.metric("Other / Unset", other)

            st.divider()

            # ── Visual bar ──
            if total > 0:
                male_pct   = male   / total * 100
                female_pct = female / total * 100
                other_pct  = other  / total * 100

                st.subheader("Distribution")

                st.markdown(f"""
<div style="display:flex;height:36px;border-radius:8px;overflow:hidden;margin-bottom:8px">
  <div style="width:{male_pct:.1f}%;background:#4A90D9;display:flex;align-items:center;justify-content:center;color:white;font-weight:600;font-size:13px">
    {"👨 " + f"{male_pct:.1f}%" if male_pct > 8 else ""}
  </div>
  <div style="width:{female_pct:.1f}%;background:#E87070;display:flex;align-items:center;justify-content:center;color:white;font-weight:600;font-size:13px">
    {"👩 " + f"{female_pct:.1f}%" if female_pct > 8 else ""}
  </div>
  {"<div style='width:" + f"{other_pct:.1f}" + "%;background:#AAA;display:flex;align-items:center;justify-content:center;color:white;font-weight:600;font-size:13px'>" + ("Other" if other_pct > 8 else "") + "</div>" if other > 0 else ""}
</div>
<div style="display:flex;gap:20px;margin-top:4px;font-size:13px">
  <span>🔵 Male &nbsp;<b>{male_pct:.1f}%</b></span>
  <span>🔴 Female &nbsp;<b>{female_pct:.1f}%</b></span>
  {"<span>⚪ Other &nbsp;<b>" + f"{other_pct:.1f}%" + "</b></span>" if other > 0 else ""}
</div>
""", unsafe_allow_html=True)

            st.divider()

            # ── Shift breakdown ──
            st.subheader("Gender by Shift")
            if "seat_no" in students_df.columns:
                # Use exam as a grouping proxy since we don't store shift per student
                pass

            # Exam-wise gender breakdown
            st.subheader("Gender by Exam")
            exam_group = (
                students_df.groupby(["exam_name", "gender"])
                .size()
                .unstack(fill_value=0)
                .reset_index()
            )
            exam_group.columns.name = None
            st.dataframe(exam_group, use_container_width=True, hide_index=True)

            st.divider()

            # ── Status breakdown ──
            st.subheader("Gender by Status")
            status_group = (
                students_df.groupby(["status", "gender"])
                .size()
                .unstack(fill_value=0)
                .reset_index()
            )
            status_group.columns.name = None
            st.dataframe(status_group, use_container_width=True, hide_index=True)
