import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, date
import os
from dotenv import load_dotenv
load_dotenv()


ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "change_me_before_deploy")

st.set_page_config(page_title="TOPPERS_CORNER_Library Management", layout="wide")

ASSETS_DIR = "library_assets"
BACKUP_DIR = "backups"
os.makedirs(ASSETS_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)

EXAM_OPTIONS = [
    "UPSC", "SSC", "Banking", "Railways", "State PSC", "NEET", "JEE",
    "Judiciary", "Teaching (CTET/TET)", "Defence (NDA/CDS)", "Other"
]


def init_db():
    try:
        conn = sqlite3.connect('library.db')
        c = conn.cursor()

        c.execute('''CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            parentage TEXT,
            student_aadhar TEXT,
            parent_aadhar TEXT,
            phone TEXT,
            parent_phone TEXT,
            seat_no INTEGER,
            gender TEXT,
            exam_name TEXT,
            join_date TEXT,
            status TEXT,
            total_fee REAL,
            paid_fee REAL,
            pending_fee REAL
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS fees (
            id INTEGER PRIMARY KEY,
            student_id INTEGER,
            amount REAL,
            date TEXT,
            status TEXT,
            FOREIGN KEY (student_id) REFERENCES students(id)
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY,
            wifi_status TEXT,
            day_fee REAL,
            night_fee REAL,
            library_name TEXT,
            library_photo TEXT,
            last_updated TEXT
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY,
            student_id INTEGER,
            sender TEXT,
            message TEXT,
            timestamp TEXT,
            FOREIGN KEY (student_id) REFERENCES students(id)
        )''')

        conn.commit()

        existing_cols = {row[1] for row in c.execute("PRAGMA table_info(students)").fetchall()}
        new_cols = {
            "parentage": "TEXT",
            "student_aadhar": "TEXT",
            "parent_aadhar": "TEXT",
            "parent_phone": "TEXT",
            "exam_name": "TEXT",
        }
        for col, coltype in new_cols.items():
            if col not in existing_cols:
                c.execute(f"ALTER TABLE students ADD COLUMN {col} {coltype}")

        settings_cols = {row[1] for row in c.execute("PRAGMA table_info(settings)").fetchall()}
        for col, coltype in {"library_name": "TEXT", "library_photo": "TEXT"}.items():
            if col not in settings_cols:
                c.execute(f"ALTER TABLE settings ADD COLUMN {col} {coltype}")

        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        st.error(f"⚠️ Database could not be initialised: {e}")
        st.stop()


init_db()


def get_db_connection():
    conn = sqlite3.connect('library.db')
    conn.row_factory = sqlite3.Row
    return conn


def sync_backup_csv():
    try:
        conn = sqlite3.connect('library.db')
        for table in ("students", "fees", "settings", "messages"):
            df = pd.read_sql_query(f'SELECT * FROM {table}', conn)
            df.to_csv(os.path.join(BACKUP_DIR, f"{table}.csv"), index=False)
        conn.close()
        with open(os.path.join(BACKUP_DIR, "last_backup.txt"), "w") as f:
            f.write(f"Last backed up: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        return True
    except (sqlite3.Error, OSError) as e:
        st.warning(f"⚠️ Could not write CSV backup (your data is still saved in the database): {e}")
        return False


def phone_exists(phone, exclude_id=None):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        if exclude_id:
            c.execute('SELECT id FROM students WHERE phone = ? AND id != ?', (phone, exclude_id))
        else:
            c.execute('SELECT id FROM students WHERE phone = ?', (phone,))
        row = c.fetchone()
        conn.close()
        return row is not None
    except sqlite3.Error as e:
        raise sqlite3.Error(f"Database error while checking phone: {e}")


def seat_taken(seat_no, exclude_id=None):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        if exclude_id:
            c.execute('SELECT id FROM students WHERE seat_no = ? AND id != ?', (seat_no, exclude_id))
        else:
            c.execute('SELECT id FROM students WHERE seat_no = ?', (seat_no,))
        row = c.fetchone()
        conn.close()
        return row is not None
    except sqlite3.Error as e:
        raise sqlite3.Error(f"Database error while checking seat: {e}")


def _valid_aadhar(aadhar):
    return aadhar.isdigit() and len(aadhar) == 12


def mask_phone(phone):
    if not phone:
        return "Not provided"
    phone = str(phone)
    if len(phone) >= 6:
        return phone[:4] + "X" * (len(phone) - 4)
    return phone


def mask_aadhar(aadhar):
    if not aadhar:
        return "Not provided"
    aadhar = str(aadhar)
    if len(aadhar) >= 6:
        return aadhar[:6] + "X" * (len(aadhar) - 6)
    return aadhar


def mask_df_columns(df):
    display = df.copy()
    for col in ("phone", "parent_phone"):
        if col in display.columns:
            display[col] = display[col].apply(lambda v: mask_phone(str(v)) if pd.notna(v) else "")
    for col in ("student_aadhar", "parent_aadhar"):
        if col in display.columns:
            display[col] = display[col].apply(lambda v: mask_aadhar(str(v)) if pd.notna(v) else "")
    return display


def add_student(name, parentage, student_aadhar, parent_aadhar, phone, parent_phone,
                 gender, exam_name, join_date_str):
    name = name.strip()
    parentage = parentage.strip()
    student_aadhar = student_aadhar.strip()
    parent_aadhar = parent_aadhar.strip()
    phone = phone.strip()
    parent_phone = parent_phone.strip()

    if not name:
        return False, "Student name cannot be empty."
    if not parentage:
        return False, "Parentage (father's/guardian's name) is required."
    if not phone:
        return False, "Student phone number is required."
    if not phone.isdigit() or len(phone) != 10:
        return False, "Student phone number must be exactly 10 digits (numbers only)."
    if not parent_phone:
        return False, "Parent's phone number is required."
    if not parent_phone.isdigit() or len(parent_phone) != 10:
        return False, "Parent's phone number must be exactly 10 digits (numbers only)."
    if not student_aadhar or not _valid_aadhar(student_aadhar):
        return False, "Student's Aadhar number must be exactly 12 digits (numbers only)."
    if not parent_aadhar or not _valid_aadhar(parent_aadhar):
        return False, "Parent's Aadhar number must be exactly 12 digits (numbers only)."
    if not exam_name:
        return False, "Please select the exam the student is preparing for."

    try:
        if phone_exists(phone):
            return False, f"Phone number ({phone}) is already registered to another student."

        conn = get_db_connection()
        c = conn.cursor()
        c.execute(
            '''INSERT INTO students
               (name, parentage, student_aadhar, parent_aadhar, phone, parent_phone,
                gender, exam_name, join_date, status,
                total_fee, paid_fee, pending_fee)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (name, parentage, student_aadhar, parent_aadhar, phone, parent_phone,
             gender, exam_name, join_date_str, 'Active', 0, 0, 0)
        )
        conn.commit()
        student_id = c.lastrowid
        conn.close()
        sync_backup_csv()
        return True, student_id
    except sqlite3.Error as e:
        return False, f"Database error: {e}"


def assign_seat(student_id, seat_no):
    if seat_no <= 0:
        return False, "Seat number must be greater than 0."
    try:
        if seat_taken(seat_no, exclude_id=student_id):
            return False, f"Seat {seat_no} is already assigned to another student."
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('UPDATE students SET seat_no = ? WHERE id = ?', (seat_no, student_id))
        conn.commit()
        conn.close()
        sync_backup_csv()
        return True, f"Seat {seat_no} assigned successfully."
    except sqlite3.Error as e:
        return False, f"Database error: {e}"


def update_student_status(student_id, status):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('UPDATE students SET status = ? WHERE id = ?', (status, student_id))
        conn.commit()
        conn.close()
        sync_backup_csv()
        return True, "Status updated successfully."
    except sqlite3.Error as e:
        return False, f"Database error: {e}"


def update_join_date(student_id, new_join_date_str):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('UPDATE students SET join_date = ? WHERE id = ?', (new_join_date_str, student_id))
        conn.commit()
        conn.close()
        sync_backup_csv()
        return True, "Joining date updated successfully."
    except sqlite3.Error as e:
        return False, f"Database error: {e}"


def delete_student(student_id):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('DELETE FROM fees WHERE student_id = ?', (student_id,))
        c.execute('DELETE FROM messages WHERE student_id = ?', (student_id,))
        c.execute('DELETE FROM students WHERE id = ?', (student_id,))
        conn.commit()
        conn.close()
        sync_backup_csv()
        return True, "Student record deleted successfully."
    except sqlite3.Error as e:
        return False, f"Database error: {e}"


def add_fee(student_id, amount, status):
    if amount is None or amount <= 0:
        return False, "Amount must be greater than 0."
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute(
            'INSERT INTO fees (student_id, amount, date, status) VALUES (?, ?, ?, ?)',
            (student_id, amount, datetime.now().strftime('%Y-%m-%d'), status)
        )
        c.execute('SELECT total_fee, paid_fee, pending_fee FROM students WHERE id = ?', (student_id,))
        row = c.fetchone()
        if row is None:
            conn.close()
            return False, "Student record not found."
        new_total = row['total_fee'] + amount
        if status == 'Paid':
            new_paid = row['paid_fee'] + amount
            new_pending = row['pending_fee']
        else:
            new_paid = row['paid_fee']
            new_pending = row['pending_fee'] + amount
        c.execute(
            'UPDATE students SET total_fee = ?, paid_fee = ?, pending_fee = ? WHERE id = ?',
            (new_total, new_paid, new_pending, student_id)
        )
        conn.commit()
        conn.close()
        sync_backup_csv()
        return True, "Fee record added successfully."
    except sqlite3.Error as e:
        return False, f"Database error: {e}"


def get_fees_for_student(student_id):
    try:
        conn = get_db_connection()
        df = pd.read_sql_query(
            'SELECT * FROM fees WHERE student_id = ? ORDER BY id DESC', conn, params=(student_id,)
        )
        conn.close()
        return df
    except sqlite3.Error as e:
        st.error(f"Database error while loading fee history: {e}")
        return pd.DataFrame()


def generate_receipt_html(student, fee_row, library_name):
    generated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Receipt #{fee_row['id']}</title>
<style>
  body {{ font-family: Arial, sans-serif; padding: 40px; color: #222; }}
  .receipt {{ max-width: 600px; margin: auto; border: 1px solid #ccc; padding: 30px; border-radius: 8px; }}
  h1 {{ text-align: center; margin-bottom: 0; }}
  .subtitle {{ text-align: center; color: #666; margin-top: 4px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 24px; }}
  td {{ padding: 8px 4px; border-bottom: 1px solid #eee; }}
  td.label {{ font-weight: bold; width: 40%; }}
  .amount {{ font-size: 1.4em; font-weight: bold; text-align: center; margin-top: 24px; }}
  .status-paid {{ color: #1a7f37; }}
  .status-pending {{ color: #b54708; }}
  .footer {{ text-align: center; margin-top: 30px; color: #888; font-size: 0.85em; }}
</style>
</head>
<body>
  <div class="receipt">
    <h1>{library_name}</h1>
    <p class="subtitle">Fee Payment Receipt</p>
    <table>
      <tr><td class="label">Receipt No.</td><td>{fee_row['id']}</td></tr>
      <tr><td class="label">Student Name</td><td>{student['name']}</td></tr>
      <tr><td class="label">Student ID</td><td>{student['id']}</td></tr>
      <tr><td class="label">Phone</td><td>{student['phone']}</td></tr>
      <tr><td class="label">Transaction Date</td><td>{fee_row['date']}</td></tr>
      <tr><td class="label">Status</td><td class="status-{fee_row['status'].lower()}">{fee_row['status']}</td></tr>
    </table>
    <div class="amount">₹{fee_row['amount']:.2f}</div>
    <p class="footer">Generated on {generated_at} · This is a system-generated receipt.</p>
  </div>
</body>
</html>"""


def get_all_students():
    try:
        conn = get_db_connection()
        df = pd.read_sql_query('SELECT * FROM students', conn)
        conn.close()
        return df
    except sqlite3.Error as e:
        st.error(f"Database error while loading students: {e}")
        return pd.DataFrame()


def get_students_with_pending_fees():
    try:
        conn = get_db_connection()
        df = pd.read_sql_query(
            'SELECT * FROM students WHERE pending_fee > 0 ORDER BY pending_fee DESC', conn
        )
        conn.close()
        return df
    except sqlite3.Error as e:
        st.error(f"Database error while loading pending fee reminders: {e}")
        return pd.DataFrame()


def get_student_by_id(student_id):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('SELECT * FROM students WHERE id = ?', (student_id,))
        row = c.fetchone()
        conn.close()
        return row
    except sqlite3.Error as e:
        st.error(f"Database error while fetching student: {e}")
        return None


def get_wifi_status():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('SELECT wifi_status FROM settings WHERE id = 1')
        row = c.fetchone()
        conn.close()
        return row['wifi_status'] if row else 'OFF'
    except sqlite3.Error as e:
        st.error(f"Database error while checking WiFi: {e}")
        return 'OFF'


def get_settings_row():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('SELECT * FROM settings WHERE id = 1')
        row = c.fetchone()
        conn.close()
        return row
    except sqlite3.Error as e:
        st.error(f"Database error while loading settings: {e}")
        return None


def _ensure_settings_row():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT * FROM settings WHERE id = 1')
    if not c.fetchone():
        c.execute(
            '''INSERT INTO settings (id, wifi_status, day_fee, night_fee, library_name, library_photo, last_updated)
               VALUES (1, ?, ?, ?, ?, ?, ?)''',
            ('OFF', 0, 0, 'TOPPERS CORNER Library', None, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        )
        conn.commit()
    conn.close()


def update_wifi_status(status):
    try:
        _ensure_settings_row()
        conn = get_db_connection()
        c = conn.cursor()
        c.execute(
            'UPDATE settings SET wifi_status = ?, last_updated = ? WHERE id = 1',
            (status, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        )
        conn.commit()
        conn.close()
        sync_backup_csv()
        return True, f"WiFi set to {status}."
    except sqlite3.Error as e:
        return False, f"Database error: {e}"


def update_library_profile(library_name, photo_file):
    library_name = library_name.strip()
    if not library_name:
        return False, "Library name cannot be empty."
    try:
        _ensure_settings_row()
        photo_path = None
        if photo_file is not None:
            ext = os.path.splitext(photo_file.name)[1] or ".png"
            photo_path = os.path.join(ASSETS_DIR, f"library_photo{ext}")
            with open(photo_path, "wb") as f:
                f.write(photo_file.getbuffer())
        conn = get_db_connection()
        c = conn.cursor()
        if photo_path:
            c.execute(
                'UPDATE settings SET library_name = ?, library_photo = ?, last_updated = ? WHERE id = 1',
                (library_name, photo_path, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            )
        else:
            c.execute(
                'UPDATE settings SET library_name = ?, last_updated = ? WHERE id = 1',
                (library_name, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            )
        conn.commit()
        conn.close()
        sync_backup_csv()
        return True, "Library profile updated successfully."
    except sqlite3.Error as e:
        return False, f"Database error: {e}"


def send_message(student_id, sender, message):
    message = message.strip()
    if not message:
        return False, "Message cannot be empty."
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute(
            'INSERT INTO messages (student_id, sender, message, timestamp) VALUES (?, ?, ?, ?)',
            (student_id, sender, message, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        )
        conn.commit()
        conn.close()
        sync_backup_csv()
        return True, "Message sent."
    except sqlite3.Error as e:
        return False, f"Database error: {e}"


def get_messages_for_student(student_id):
    try:
        conn = get_db_connection()
        df = pd.read_sql_query(
            'SELECT * FROM messages WHERE student_id = ? ORDER BY timestamp ASC',
            conn, params=(student_id,)
        )
        conn.close()
        return df
    except sqlite3.Error as e:
        st.error(f"Database error while loading messages: {e}")
        return pd.DataFrame()


# ── SIDEBAR ──────────────────────────────────────────────────────────────────

sync_backup_csv()

_settings = get_settings_row()
library_display_name = _settings['library_name'] if _settings and _settings['library_name'] else "TOPPERS CORNER Library"
library_photo_path = _settings['library_photo'] if _settings else None

if library_photo_path and os.path.exists(library_photo_path):
    st.sidebar.image(library_photo_path, use_container_width=True)

st.sidebar.title(f"📚 {library_display_name}")
admin_mode = st.sidebar.checkbox("Admin Mode")

if admin_mode:
    admin_password = st.sidebar.text_input("Admin Password", type="password")
    if admin_password != ADMIN_PASSWORD:
        st.sidebar.error("Invalid password")
        admin_mode = False


# ── TABS ──────────────────────────────────────────────────────────────────────

if admin_mode:
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
        ["Register Student", "Fee Management", "Manage Status", "Messages", "Settings", "Dashboard"]
    )
else:
    tab1, tab2, tab3 = st.tabs(["View Student Info", "WiFi Status", "Messages"])


# ── ADMIN TABS ────────────────────────────────────────────────────────────────

if admin_mode:

    with tab1:
        st.header("Library Registration Form")
        col1, col2, col3 = st.columns(3)
        with col1:
            name = st.text_input("Student Name")
        with col2:
            parentage = st.text_input("Parentage (Father's / Guardian's Name)")
        with col3:
            gender = st.selectbox("Gender", ["Male", "Female"])

        col1, col2 = st.columns(2)
        with col1:
            student_aadhar = st.text_input("Student's Aadhar Number", max_chars=12)
        with col2:
            parent_aadhar = st.text_input("Parent's Aadhar Number", max_chars=12)

        col1, col2 = st.columns(2)
        with col1:
            phone = st.text_input("Student's Phone Number", max_chars=10)
        with col2:
            parent_phone = st.text_input("Parent's Phone Number", max_chars=10)

        col1, col2 = st.columns(2)
        with col1:
            exam_choice = st.selectbox("Exam Preparing For", EXAM_OPTIONS)
            exam_name = exam_choice
            if exam_choice == "Other":
                exam_name = st.text_input("Please specify the exam name")
        with col2:
            join_date_input = st.date_input("Joining Date", value=date.today())

        if st.button("Register Student", key="register_btn"):
            success, result = add_student(
                name, parentage, student_aadhar, parent_aadhar, phone, parent_phone,
                gender, exam_name, join_date_input.strftime('%Y-%m-%d')
            )
            if success:
                st.success(f"✅ Student registered! ID: {result}")
                st.rerun()
            else:
                st.error(f"❌ {result}")

        st.divider()
        st.subheader("All Students")
        students_df = get_all_students()
        if not students_df.empty:
            st.dataframe(mask_df_columns(students_df), use_container_width=True)

            st.subheader("Assign Seat")
            selected_student_id = st.selectbox("Select Student", students_df['id'].tolist(), key="assign_seat_select")
            seat_no = st.number_input("Seat Number", min_value=1, step=1)
            if st.button("Assign Seat"):
                success, message = assign_seat(selected_student_id, int(seat_no))
                if success:
                    st.success(f"✅ {message}")
                    st.rerun()
                else:
                    st.error(f"❌ {message}")

            st.divider()
            st.subheader("Update Joining Date")
            join_student_id = st.selectbox("Select Student", students_df['id'].tolist(), key="join_date_select")
            current_student = get_student_by_id(int(join_student_id))
            default_date = date.today()
            if current_student and current_student['join_date']:
                try:
                    default_date = datetime.strptime(current_student['join_date'], '%Y-%m-%d').date()
                except ValueError:
                    pass
            new_join_date = st.date_input("New Joining Date", value=default_date, key="new_join_date")
            if st.button("Update Joining Date"):
                success, message = update_join_date(int(join_student_id), new_join_date.strftime('%Y-%m-%d'))
                if success:
                    st.success(f"✅ {message}")
                    st.rerun()
                else:
                    st.error(f"❌ {message}")

            st.divider()
            st.subheader("Delete Student")
            st.caption("This permanently removes the student along with their fee records and messages.")
            delete_student_id = st.selectbox("Select Student", students_df['id'].tolist(), key="delete_select")
            confirm_delete = st.checkbox("I understand this action cannot be undone", key="confirm_delete")
            if st.button("Delete Student", type="primary", disabled=not confirm_delete):
                success, message = delete_student(int(delete_student_id))
                if success:
                    st.success(f"✅ {message}")
                    st.rerun()
                else:
                    st.error(f"❌ {message}")
        else:
            st.info("No students registered yet.")

    with tab2:
        st.header("Fee Management")
        students_df = get_all_students()
        if not students_df.empty:
            selected_student_id = st.selectbox("Select Student", students_df['id'].tolist(), key="fee_mgmt_select")
            student = get_student_by_id(selected_student_id)
            if student is None:
                st.error("Student record not found. Please reload the page.")
            else:
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Total Fee", f"₹{student['total_fee']:.2f}")
                with col2:
                    st.metric("Paid", f"₹{student['paid_fee']:.2f}")
                with col3:
                    st.metric("Pending", f"₹{student['pending_fee']:.2f}")

                st.divider()
                col1, col2 = st.columns(2)
                with col1:
                    amount = st.number_input("Amount (₹)", min_value=1, step=100)
                with col2:
                    fee_status = st.selectbox("Status", ["Paid", "Pending"])

                if st.button("Add Fee Record"):
                    success, message = add_fee(selected_student_id, amount, fee_status)
                    if success:
                        st.success(f"✅ {message}")
                        st.rerun()
                    else:
                        st.error(f"❌ {message}")

                st.divider()
                st.subheader("Payment History & Receipts")
                fees_df = get_fees_for_student(selected_student_id)
                if not fees_df.empty:
                    st.dataframe(fees_df, use_container_width=True)
                    library_row = get_settings_row()
                    receipt_library_name = (
                        library_row['library_name'] if library_row and library_row['library_name']
                        else "TOPPERS CORNER Library"
                    )
                    receipt_options = {
                        int(row['id']): f"Receipt #{int(row['id'])} — ₹{row['amount']:.2f} ({row['status']}, {row['date']})"
                        for _, row in fees_df.iterrows()
                    }
                    receipt_fee_id = st.selectbox(
                        "Select a transaction to generate a receipt for",
                        receipt_options.keys(), format_func=lambda x: receipt_options[x], key="receipt_select"
                    )
                    receipt_fee_row = fees_df[fees_df['id'] == receipt_fee_id].iloc[0]
                    receipt_html = generate_receipt_html(student, receipt_fee_row, receipt_library_name)
                    st.download_button(
                        "Download Receipt",
                        data=receipt_html,
                        file_name=f"receipt_{student['name'].replace(' ', '')}{int(receipt_fee_id)}.html",
                        mime="text/html",
                        key="download_receipt_btn"
                    )
                    st.caption("Open the downloaded file in a browser and use Print → Save as PDF.")
                else:
                    st.info("No fee transactions recorded yet for this student.")
        else:
            st.info("Please register a student first.")

    with tab3:
        st.header("Manage Student Status")
        students_df = get_all_students()
        if not students_df.empty:
            selected_student_id = st.selectbox("Select Student", students_df['id'].tolist(), key="status_select")
            status = st.selectbox("Update Status", ["Active", "Inactive", "Suspended", "Left"])
            if st.button("Update Status"):
                success, message = update_student_status(selected_student_id, status)
                if success:
                    st.success(f"✅ {message}")
                    st.rerun()
                else:
                    st.error(f"❌ {message}")
        else:
            st.info("Please register a student first.")

    with tab4:
        st.header("Messages")
        students_df = get_all_students()
        if not students_df.empty:
            options = {int(row['id']): f"{row['name']} (ID {int(row['id'])})" for _, row in students_df.iterrows()}
            msg_student_id = st.selectbox(
                "Select Student", options.keys(), format_func=lambda x: options[x], key="msg_admin_select"
            )
            messages_df = get_messages_for_student(msg_student_id)
            st.subheader(f"Conversation with {options[msg_student_id]}")
            if not messages_df.empty:
                for _, row in messages_df.iterrows():
                    label = "🛡️ Admin" if row['sender'] == 'admin' else "🎓 Student"
                    st.markdown(f"*{label}* — {row['timestamp']}")
                    st.write(row['message'])
                    st.divider()
            else:
                st.info("No messages yet with this student.")
            new_admin_message = st.text_area("Write a message to this student", key="admin_msg_text")
            if st.button("Send Message", key="admin_send_btn"):
                success, message = send_message(msg_student_id, 'admin', new_admin_message)
                if success:
                    st.success("✅ Message sent.")
                    st.rerun()
                else:
                    st.error(f"❌ {message}")
        else:
            st.info("Please register a student first.")

    with tab5:
        st.header("Library Settings")
        col1, col2 = st.columns(2)
        with col1:
            wifi_status = st.radio("WiFi Status", ["ON", "OFF"])
        with col2:
            if st.button("Update WiFi Status"):
                success, message = update_wifi_status(wifi_status)
                if success:
                    st.success(f"✅ {message}")
                    st.rerun()
                else:
                    st.error(f"❌ {message}")

        st.divider()
        st.subheader("Library Profile")
        col1, col2 = st.columns(2)
        with col1:
            new_library_name = st.text_input("Library Name", value=library_display_name)
        with col2:
            new_library_photo = st.file_uploader("Library Photo", type=["png", "jpg", "jpeg"], key="library_photo_upload")
        if st.button("Update Library Profile"):
            success, message = update_library_profile(new_library_name, new_library_photo)
            if success:
                st.success(f"✅ {message}")
                st.rerun()
            else:
                st.error(f"❌ {message}")

        st.divider()
        st.subheader("Library Timings & Fees")
        col1, col2 = st.columns(2)
        with col1:
            st.info("Day Shift: 8 AM – 8 PM")
        with col2:
            st.info("Night Shift: 8 PM – 8 PM")

        st.subheader("Break Times")
        col1, col2 = st.columns(2)
        with col1:
            st.text("Girls: 1 PM – 2 PM")
        with col2:
            st.text("Boys: THERE IS NO  RULE FOR BOYS (NON_CHALANT)")

        st.divider()
        st.subheader("💾 Data Backup")
        st.caption(
            "Every time you add, edit, or delete a record, this app automatically saves a copy "
            "of all your data into plain CSV files (readable in Excel) under the backups/ folder."
        )
        last_backup_file = os.path.join(BACKUP_DIR, "last_backup.txt")
        if os.path.exists(last_backup_file):
            with open(last_backup_file) as f:
                st.success(f"✅ {f.read().strip()}")
        else:
            st.info("No backup has been made yet. Click below to create one now.")
        if st.button("🔄 Backup Now"):
            if sync_backup_csv():
                st.success("✅ Backup completed successfully.")
                st.rerun()

        st.markdown("*Download a copy of your data:*")
        bcol1, bcol2, bcol3, bcol4 = st.columns(4)
        backup_cols = [
            (bcol1, "students", "Students"),
            (bcol2, "fees", "Fees"),
            (bcol3, "messages", "Messages"),
            (bcol4, "settings", "Settings"),
        ]
        for col, table, label in backup_cols:
            csv_path = os.path.join(BACKUP_DIR, f"{table}.csv")
            with col:
                if os.path.exists(csv_path):
                    with open(csv_path, "rb") as f:
                        st.download_button(
                            f"⬇️ {label}.csv",
                            data=f.read(),
                            file_name=f"{table}.csv",
                            mime="text/csv",
                            key=f"download_{table}_csv",
                        )
                else:
                    st.caption(f"{label}: no data yet")

    with tab6:
        st.header("Library Dashboard")
        students_df = get_all_students()
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Students", len(students_df))
        with col2:
            active = len(students_df[students_df['status'] == 'Active']) if not students_df.empty else 0
            st.metric("Active", active)
        with col3:
            total_pending = students_df['pending_fee'].sum() if not students_df.empty else 0
            st.metric("Total Pending Fees", f"₹{total_pending:.2f}")
        with col4:
            wifi = get_wifi_status()
            st.metric("WiFi Status", wifi)

        st.divider()
        st.subheader("⚠️ Pending Fee Reminders")
        pending_df = get_students_with_pending_fees()
        if not pending_df.empty:
            st.caption(f"{len(pending_df)} student(s) have outstanding fees.")
            masked_pending = mask_df_columns(pending_df)
            st.dataframe(
                masked_pending[['id', 'name', 'phone', 'parent_phone', 'seat_no', 'status', 'pending_fee']],
                use_container_width=True
            )
            reminder_options = {
                int(row['id']): f"{row['name']} (ID {int(row['id'])}) — ₹{row['pending_fee']:.2f} pending"
                for _, row in pending_df.iterrows()
            }
            reminder_student_id = st.selectbox(
                "Send a reminder to", reminder_options.keys(),
                format_func=lambda x: reminder_options[x], key="reminder_select"
            )
            reminder_amount = pending_df.loc[pending_df['id'] == reminder_student_id, 'pending_fee'].iloc[0]
            default_reminder_text = (
                f"Reminder: You have a pending fee of ₹{reminder_amount:.2f}. "
                f"Please clear it at the earliest. Thank you."
            )
            reminder_text = st.text_area("Reminder message", value=default_reminder_text, key="reminder_text")
            if st.button("Send Reminder", key="send_reminder_btn"):
                success, message = send_message(int(reminder_student_id), 'admin', reminder_text)
                if success:
                    st.success("✅ Reminder sent.")
                    st.rerun()
                else:
                    st.error(f"❌ {message}")
        else:
            st.success("No pending fees — everyone is up to date.")

        st.divider()
        st.subheader("Detailed Report")
        if not students_df.empty:
            st.dataframe(mask_df_columns(students_df), use_container_width=True)
        else:
            st.info("No student data available yet.")


# ── USER TABS ─────────────────────────────────────────────────────────────────

else:
    with tab1:
        st.header("📋 Student Information")
        st.caption("View-only. Only admin can register, edit, or update records.")
        student_id = st.number_input("Enter Your Student ID", min_value=1, step=1)
        if st.button("Search"):
            student = get_student_by_id(int(student_id))
            if student:
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("Name", student['name'])
                    st.metric("Parentage", student['parentage'] or "Not provided")
                    st.metric("Seat No.", student['seat_no'] if student['seat_no'] else "Not assigned")
                    st.metric("Status", student['status'])
                    st.metric("Exam", student['exam_name'] or "Not specified")
                with col2:
                    st.metric("Phone", mask_phone(student['phone']))
                    st.metric("Parent's Phone", mask_phone(student['parent_phone']))
                    st.metric("Joined", student['join_date'])
                    st.metric("Gender", student['gender'])

                st.divider()
                st.subheader("Fee Status")
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Total Fee", f"₹{student['total_fee']:.2f}")
                with col2:
                    st.metric("Paid", f"₹{student['paid_fee']:.2f}")
                with col3:
                    st.metric("Pending", f"₹{student['pending_fee']:.2f}")
            else:
                st.error("Student not found. Please check your ID.")

    with tab2:
        st.header("📡 WiFi Status")
        wifi = get_wifi_status()
        if wifi == "ON":
            st.success("✅ WiFi is ON")
        else:
            st.error("❌ WiFi is OFF")

    with tab3:
        st.header("💬 Messages")
        st.caption("Enter your Student ID to view and send messages with the library admin.")
        msg_student_id_input = st.number_input("Your Student ID", min_value=1, step=1, key="user_msg_id")
        if msg_student_id_input:
            student = get_student_by_id(int(msg_student_id_input))
            if student is None:
                st.info("Enter a valid Student ID to view your messages.")
            else:
                messages_df = get_messages_for_student(int(msg_student_id_input))
                if not messages_df.empty:
                    for _, row in messages_df.iterrows():
                        label = "🛡️ Admin" if row['sender'] == 'admin' else "🎓 You"
                        st.markdown(f"*{label}* — {row['timestamp']}")
                        st.write(row['message'])
                        st.divider()
                else:
                    st.info("No messages yet.")
                new_student_message = st.text_area("Send a message to the admin", key="student_msg_text")
                if st.button("Send Message", key="student_send_btn"):
                    success, message = send_message(int(msg_student_id_input), 'student', new_student_message)
                    if success:
                        st.success("✅ Message sent.")
                        st.rerun()
                    else:
                        st.error(f"❌ {message}")

st.sidebar.divider()
st.sidebar.caption("Library Management System v1.2")  