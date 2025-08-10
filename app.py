import streamlit as st
import pandas as pd
import random
import datetime
import io
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from faker import Faker
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT, TA_RIGHT

# --- Constants for Invoice Generator ---
EXPENSE_CODES = {
    "Copying": "E101", "Outside printing": "E102", "Word processing": "E103",
    "Facsimile": "E104", "Telephone": "E105", "Online research": "E106",
    "Delivery services/messengers": "E107", "Postage": "E108", "Local travel": "E109",
    "Out-of-town travel": "E110", "Meals": "E111", "Court fees": "E112",
    "Subpoena fees": "E113", "Witness fees": "E114", "Deposition transcripts": "E115",
    "Trial transcripts": "E116", "Trial exhibits": "E117",
    "Litigation support vendors": "E118", "Experts": "E119",
    "Private investigators": "E120", "Arbitrators/mediators": "E121",
    "Local counsel": "E122", "Other professionals": "E123", "Other": "E124",
}
EXPENSE_DESCRIPTIONS = list(EXPENSE_CODES.keys())
OTHER_EXPENSE_DESCRIPTIONS = [desc for desc in EXPENSE_DESCRIPTIONS if EXPENSE_CODES[desc] != "E101"]

DEFAULT_TASK_ACTIVITY_DESC = [
    ("L100", "A101", "Legal Research: Analyze legal precedents"),
    ("L110", "A101", "Legal Research: Review statutes and regulations"),
    ("L120", "A101", "Legal Research: Draft research memorandum"),
    ("L130", "A102", "Case Assessment: Initial case evaluation"),
    ("L140", "A102", "Case Assessment: Develop case strategy"),
    ("L150", "A102", "Case Assessment: Identify key legal issues"),
    ("L160", "A103", "Fact Investigation: Interview witnesses"),
    ("L190", "A104", "Pleadings: Draft complaint/petition"),
    ("L200", "A104", "Pleadings: Prepare answer/response"),
    ("L210", "A104", "Pleadings: File motion to dismiss"),
    ("L220", "A105", "Discovery: Draft interrogatories"),
    ("L230", "A105", "Discovery: Prepare requests for production"),
    ("L240", "A105", "Discovery: Review opposing party's discovery responses"),
    ("L250", "A106", "Depositions: Prepare for deposition"),
    ("L260", "A106", "Depositions: Attend deposition"),
    ("L300", "A107", "Motions: Argue motion in court"),
    ("L310", "A108", "Settlement/Mediation: Prepare for mediation"),
    ("L320", "A108", "Settlement/Mediation: Attend mediation"),
    ("L330", "A108", "Settlement/Mediation: Draft settlement agreement"),
    ("L340", "A109", "Trial Preparation: Prepare witness for trial"),
    ("L350", "A109", "Trial Preparation: Organize trial exhibits"),
    ("L390", "A110", "Trial: Present closing argument"),
    ("L400", "A111", "Appeals: Research appellate issues"),
    ("L410", "A111", "Appeals: Draft appellate brief"),
    ("L420", "A111", "Appeals: Argue before appellate court"),
    ("L430", "A112", "Client Communication: Client meeting"),
    ("L440", "A112", "Client Communication: Phone call with client"),
    ("L450", "A112", "Client Communication: Email correspondence with client"),
]

MAJOR_TASK_CODES = {"L110", "L120", "L130", "L140", "L150", "L160", "L170", "L180", "L190"}
DEFAULT_CLIENT_ID = "02-4388252"
DEFAULT_LAW_FIRM_ID = "02-1234567"
DEFAULT_INVOICE_DESCRIPTION = "Monthly Legal Services"

# --- Functions from Original Script, adapted for Streamlit ---
def _replace_name_placeholder(description, faker_instance):
    return description.replace("{NAME_PLACEHOLDER}", faker_instance.name())

def _replace_description_dates(description):
    pattern = r"\b(\d{2}/\d{2}/\d{4})\b"
    if re.search(pattern, description):
        days_ago = random.randint(15, 90)
        new_date = (datetime.date.today() - datetime.timedelta(days=days_ago)).strftime("%m/%d/%Y")
        return re.sub(pattern, new_date, description)
    return description

def _load_timekeepers(uploaded_file):
    if uploaded_file is None:
        return None
    try:
        df = pd.read_csv(uploaded_file)
        required_cols = ["TIMEKEEPER_NAME", "TIMEKEEPER_CLASSIFICATION", "TIMEKEEPER_ID", "RATE"]
        if not all(col in df.columns for col in required_cols):
            st.error(f"Timekeeper CSV must contain the following columns: {', '.join(required_cols)}")
            return None
        return df.to_dict(orient='records')
    except Exception as e:
        st.error(f"Error loading timekeeper file: {e}")
        return None

def _load_custom_task_activity_data(uploaded_file):
    if uploaded_file is None:
        return None
    try:
        df = pd.read_csv(uploaded_file)
        required_cols = ["TASK_CODE", "ACTIVITY_CODE", "DESCRIPTION"]
        if not all(col in df.columns for col in required_cols):
            st.error(f"Custom Task/Activity CSV must contain the following columns: {', '.join(required_cols)}")
            return None
        if df.empty:
            st.warning("Custom Task/Activity CSV file is empty.")
            return []
        custom_tasks = []
        for _, row in df.iterrows():
            custom_tasks.append((str(row["TASK_CODE"]), str(row["ACTIVITY_CODE"]), str(row["DESCRIPTION"])))
        return custom_tasks
    except Exception as e:
        st.error(f"Error loading custom tasks file: {e}")
        return None

def _generate_invoice_data(fee_count, expense_count, timekeeper_data, client_id, law_firm_id, invoice_desc, billing_start_date, billing_end_date, task_activity_desc, major_task_codes, max_hours_per_tk_per_day, include_block_billed, faker_instance):
    # This is a port of the original function.
    # It generates a list of dictionaries for a single conceptual invoice.
    rows = []
    delta = billing_end_date - billing_start_date
    num_days = delta.days + 1
    major_items = [item for item in task_activity_desc if item[0] in major_task_codes]
    other_items = [item for item in task_activity_desc if item[0] not in major_task_codes]
    current_invoice_total = 0.0
    daily_hours_tracker = {}
    MAX_DAILY_HOURS = max_hours_per_tk_per_day

    # Fee records
    for _ in range(fee_count):
        if not task_activity_desc: break
        tk_row = random.choice(timekeeper_data)
        timekeeper_id = tk_row["TIMEKEEPER_ID"]
        if major_items and random.random() < 0.7:
            task_code, activity_code, description = random.choice(major_items)
        elif other_items:
            task_code, activity_code, description = random.choice(other_items)
        else: continue
        random_day_offset = random.randint(0, num_days - 1)
        line_item_date = billing_start_date + datetime.timedelta(days=random_day_offset)
        line_item_date_str = line_item_date.strftime("%Y-%m-%d")
        current_billed_hours = daily_hours_tracker.get((line_item_date_str, timekeeper_id), 0)
        remaining_hours_capacity = MAX_DAILY_HOURS - current_billed_hours
        if remaining_hours_capacity <= 0: continue
        hours_to_bill = round(random.uniform(0.5, min(8.0, remaining_hours_capacity)), 1)
        if hours_to_bill == 0: continue
        hourly_rate = tk_row["RATE"]
        line_item_total = round(hours_to_bill * hourly_rate, 2)
        current_invoice_total += line_item_total
        daily_hours_tracker[(line_item_date_str, timekeeper_id)] = current_billed_hours + hours_to_bill
        description = _replace_description_dates(description)
        description = _replace_name_placeholder(description, faker_instance)
        row = {
            "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
            "LINE_ITEM_DATE": line_item_date_str, "TIMEKEEPER_NAME": tk_row["TIMEKEEPER_NAME"],
            "TIMEKEEPER_CLASSIFICATION": tk_row["TIMEKEEPER_CLASSIFICATION"],
            "TIMEKEEPER_ID": timekeeper_id, "TASK_CODE": task_code,
            "ACTIVITY_CODE": activity_code, "EXPENSE_CODE": "", "DESCRIPTION": description,
            "HOURS": hours_to_bill, "RATE": hourly_rate, "LINE_ITEM_TOTAL": line_item_total
        }
        rows.append(row)

    # Expense records (E101 and others)
    e101_actual_count = random.randint(1, min(3, expense_count))
    for _ in range(e101_actual_count):
        description = "Copying"
        expense_code = "E101"
        hours = random.randint(1, 200)
        rate = round(random.uniform(0.14, 0.25), 2)
        random_day_offset = random.randint(0, num_days - 1)
        line_item_date = billing_start_date + datetime.timedelta(days=random_day_offset)
        line_item_total = round(hours * rate, 2)
        current_invoice_total += line_item_total
        row = {
            "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
            "LINE_ITEM_DATE": line_item_date.strftime("%Y-%m-%d"), "TIMEKEEPER_NAME": "",
            "TIMEKEEPER_CLASSIFICATION": "", "TIMEKEEPER_ID": "", "TASK_CODE": "",
            "ACTIVITY_CODE": "", "EXPENSE_CODE": expense_code, "DESCRIPTION": description,
            "HOURS": hours, "RATE": rate, "LINE_ITEM_TOTAL": line_item_total
        }
        rows.append(row)

    remaining_expense_count = expense_count - e101_actual_count
    if remaining_expense_count > 0:
        if not OTHER_EXPENSE_DESCRIPTIONS:
            pass
        else:
            for _ in range(remaining_expense_count):
                description = random.choice(OTHER_EXPENSE_DESCRIPTIONS)
                expense_code = EXPENSE_CODES[description]
                hours = 1
                rate = round(random.uniform(25, 200), 2)
                random_day_offset = random.randint(0, num_days - 1)
                line_item_date = billing_start_date + datetime.timedelta(days=random_day_offset)
                line_item_total = round(hours * rate, 2)
                current_invoice_total += line_item_total
                row = {
                    "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id,
                    "LAW_FIRM_ID": law_firm_id, "LINE_ITEM_DATE": line_item_date.strftime("%Y-%m-%d"),
                    "TIMEKEEPER_NAME": "", "TIMEKEEPER_CLASSIFICATION": "",
                    "TIMEKEEPER_ID": "", "TASK_CODE": "", "ACTIVITY_CODE": "",
                    "EXPENSE_CODE": expense_code, "DESCRIPTION": description,
                    "HOURS": hours, "RATE": rate, "LINE_ITEM_TOTAL": line_item_total
                }
                rows.append(row)

    # Block Billing
    if not include_block_billed:
        rows = [row for row in rows if not ("; " in row["DESCRIPTION"])]
    elif include_block_billed:
        if not any('; ' in row['DESCRIPTION'] for row in rows):
            for _, _, desc in task_activity_desc:
                if '; ' in desc and len(rows) > 0:
                    extra = rows[0].copy()
                    extra['DESCRIPTION'] = desc
                    rows.insert(0, extra)
                    break
    return rows, current_invoice_total


def _create_pdf_invoice(df, total_amount, invoice_number, start_date, end_date):
    """
    Generates a PDF invoice as a BytesIO object.
    Includes an image at the top of the document.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    
    # Header and image
    try:
        # Assuming the image files are in the same directory as the script.
        # You can change these paths.
        image_path = "icon.png"
        img = Image(image_path, width=0.75 * inch, height=0.75 * inch)
        
        # Style for firm name
        firm_style = ParagraphStyle('FirmNameStyle', parent=getSampleStyleSheet()['Normal'],
                                    fontName='Helvetica-Bold', fontSize=18, alignment=TA_RIGHT)
        
        # We need to use a table or flowable for multi-part headers.
        header_table_data = [[img, Paragraph("<b>Legal Billing Services</b>", firm_style)]]
        header_table = Table(header_table_data, colWidths=[1.5*inch, None])
        header_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12)
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 0.25 * inch))
    except FileNotFoundError:
        st.warning("Image files (icon.ico, icon.png) not found. PDF will be generated without images.")
        firm_style = ParagraphStyle('FirmNameStyle', parent=getSampleStyleSheet()['Normal'],
                                    fontName='Helvetica-Bold', fontSize=18, alignment=TA_RIGHT)
        elements.append(Paragraph("<b>Legal Billing Services</b>", firm_style))
        elements.append(Spacer(1, 0.5 * inch))
        
    # Invoice details
    styles = getSampleStyleSheet()
    normal_style = styles['Normal']
    elements.append(Paragraph(f"<b>Invoice Number:</b> {invoice_number}", normal_style))
    elements.append(Paragraph(f"<b>Billing Period:</b> {start_date.strftime('%B %d, %Y')} - {end_date.strftime('%B %d, %Y')}", normal_style))
    elements.append(Spacer(1, 0.2 * inch))

    # Table data
    data = [['Date', 'Timekeeper', 'Task Code', 'Activity Code', 'Description', 'Hours/Units', 'Rate', 'Total']]
    for _, row in df.iterrows():
        # Choose the correct column based on whether it's a fee or expense
        date = row['LINE_ITEM_DATE']
        timekeeper = row['TIMEKEEPER_NAME'] if row['TIMEKEEPER_NAME'] else 'N/A'
        task_code = row['TASK_CODE'] if row['TASK_CODE'] else 'N/A'
        activity_code = row['ACTIVITY_CODE'] if row['ACTIVITY_CODE'] else 'N/A'
        description = row['DESCRIPTION']
        hours = row['HOURS']
        rate = row['RATE']
        total = row['LINE_ITEM_TOTAL']
        data.append([date, timekeeper, task_code, activity_code, description, f"{hours:.2f}", f"${rate:.2f}", f"${total:.2f}"])

    # Table styling
    table = Table(data, colWidths=[1 * inch, 1.25 * inch, 0.75 * inch, 0.75 * inch, 2.25 * inch, 0.75 * inch, 0.75 * inch, 0.75 * inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('BOX', (0, 0), (-1, -1), 1, colors.black),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('FONTSIZE', (0, 1), (-1, -1), 7),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 0.25 * inch))

    # Total section
    total_style = ParagraphStyle('TotalStyle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, alignment=TA_RIGHT)
    total_paragraph = Paragraph(f"Total Amount Due: <b>${total_amount:.2f}</b>", total_style)
    elements.append(total_paragraph)

    doc.build(elements)
    buffer.seek(0)
    return buffer

def _send_email_with_attachment(recipient_email, subject, body, attachment_data, attachment_filename):
    """
    Sends an email with a file attachment.
    Gets credentials from Streamlit Secrets.
    """
    try:
        sender_email = st.secrets.email.email_from
        password = st.secrets.email.email_password
    except AttributeError:
        st.error("Email secrets not found. Please check your .streamlit/secrets.toml file.")
        return

    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = recipient_email
    msg['Subject'] = subject

    msg.attach(MIMEText(body, 'plain'))
    
    if attachment_data:
        part = MIMEApplication(attachment_data.read(), Name=attachment_filename)
        part['Content-Disposition'] = f'attachment; filename="{attachment_filename}"'
        msg.attach(part)
    
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, password)
            server.send_message(msg)
        st.success(f"Email sent successfully to {recipient_email}!")
    except Exception as e:
        st.error(f"Error sending email: {e}")

# --- Streamlit App UI ---
st.title("LEDES Invoice Generator")
st.write("Generate and optionally email LEDES and PDF invoices.")

# --- Sidebar for user inputs ---
with st.sidebar:
    st.header("Invoice Generation Options")
    faker = Faker()

    # Timekeeper Info
    st.subheader("Timekeeper & Task Data")
    uploaded_timekeeper_file = st.file_uploader("Upload Timekeeper CSV (tk_info.csv)", type="csv")
    timekeeper_data = _load_timekeepers(uploaded_timekeeper_file)

    use_custom_tasks = st.checkbox("Use Custom Line Item Details?", value=False)
    uploaded_custom_tasks_file = None
    if use_custom_tasks:
        uploaded_custom_tasks_file = st.file_uploader("Upload Custom Line Items CSV (custom_details.csv)", type="csv")
    
    # Task/Activity logic
    task_activity_desc = DEFAULT_TASK_ACTIVITY_DESC
    if use_custom_tasks and uploaded_custom_tasks_file:
        custom_tasks_data = _load_custom_task_activity_data(uploaded_custom_tasks_file)
        if custom_tasks_data:
            task_activity_desc = custom_tasks_data

    # Main parameters
    st.subheader("Invoice Parameters")
    fees = st.number_input("# of Fee Line Items:", min_value=1, value=10, step=1)
    expenses = st.number_input("# of Expense Line Items:", min_value=1, value=5, step=1)
    max_daily_hours = st.number_input("Max Daily Timekeeper Hours:", min_value=1, max_value=24, value=16, step=1)
    
    billing_start_date = st.date_input("Billing Start Date", datetime.date.today() - datetime.timedelta(days=30))
    billing_end_date = st.date_input("Billing End Date", datetime.date.today() - datetime.timedelta(days=1))
    
    client_id = st.text_input("Client ID:", DEFAULT_CLIENT_ID)
    law_firm_id = st.text_input("Law Firm ID:", DEFAULT_LAW_FIRM_ID)
    invoice_desc = st.text_input("Invoice Description:", DEFAULT_INVOICE_DESCRIPTION)
    matter_number_base = st.text_input("Matter Number (Base):", "2025-XXXXXX")
    invoice_number_base = st.text_input("Invoice Number (Base):", "2025MMM-XXXXXX")
    ledes_version = st.selectbox("LEDES Version:", ["1998B", "XML 2.1"])
    
    include_block_billed = st.checkbox("Include Block Billed Line Items", value=True)

    # Output Options
    st.subheader("Output & Email Options")
    generate_multiple = st.checkbox("Generate Multiple Invoices")
    num_invoices = 1
    if generate_multiple:
        num_invoices = st.number_input("Number of Invoices to Create:", min_value=1, value=1, step=1)
        multiple_periods = st.checkbox("Multiple Billing Periods")
        if multiple_periods:
            num_periods = st.number_input("How Many Billing Periods:", min_value=2, max_value=6, value=2, step=1)
            num_invoices = num_periods # To simplify, this will override the number of invoices if multiple periods are selected
    
    send_email = st.checkbox("Send LEDES File Via Email")
    recipient_email = None
    include_pdf = False
    if send_email:
        recipient_email = st.text_input("Recipient Email Address:")
        include_pdf = st.checkbox("Include PDF Invoice")
        st.caption(f"Sender Email will be from: {st.secrets.get('email', {}).get('username', 'N/A')}")
        
    st.markdown("---")
    generate_button = st.button("Generate Invoice(s)")

# --- Main app logic ---
if generate_button:
    if timekeeper_data is None:
        st.warning("Please upload a valid timekeeper CSV file.")
    elif send_email and not recipient_email:
        st.warning("Please provide a recipient email address to send the invoice.")
    else:
        progress_bar = st.progress(0)
        num_generated = 0
        
        # Loop for multiple invoices
        for i in range(num_invoices):
            # Update progress bar
            progress_bar.progress((i + 1) / num_invoices)
            
            # Generate invoice data
            invoice_data, total_amount = _generate_invoice_data(
                fees, expenses, timekeeper_data, client_id, law_firm_id,
                invoice_desc, billing_start_date, billing_end_date,
                task_activity_desc, MAJOR_TASK_CODES, max_daily_hours, include_block_billed, faker
            )
            df_invoice = pd.DataFrame(invoice_data)
            
            # Filenames
            current_invoice_number = f"{invoice_number_base}-{i+1}"
            current_matter_number = f"{matter_number_base}-{i+1}"
            file_name = f"{current_invoice_number}_{current_matter_number}.txt"

            # Create LEDES 1998B content (simplified for this example)
            ledes_content = f"INVOICE|{current_invoice_number}|{client_id}|{current_matter_number}|{total_amount:.2f}|{billing_start_date.strftime('%Y%m%d')}|{billing_end_date.strftime('%Y%m%d')}\n"
            for _, row in df_invoice.iterrows():
                ledes_content += "|".join(map(str, [
                    row['CLIENT_ID'], row['LAW_FIRM_ID'], current_invoice_number,
                    current_matter_number, row['INVOICE_DESCRIPTION'],
                    row['LINE_ITEM_DATE'], row['TIMEKEEPER_ID'], row['TIMEKEEPER_CLASSIFICATION'],
                    row['TASK_CODE'], row['ACTIVITY_CODE'], row['EXPENSE_CODE'],
                    f"{row['HOURS']:.2f}", f"{row['RATE']:.2f}", f"{row['LINE_ITEM_TOTAL']:.2f}",
                    row['DESCRIPTION'].replace('|', ';')
                ])) + "\n"

            # Handle output
            if send_email:
                attachments = {'ledes': (file_name, ledes_content.encode('utf-8'))}
                
                pdf_buffer = None
                if include_pdf:
                    pdf_buffer = _create_pdf_invoice(df_invoice, total_amount, current_invoice_number, billing_start_date, billing_end_date)
                    attachments['pdf'] = (f"{current_invoice_number}_{current_matter_number}.pdf", pdf_buffer.read())
                    pdf_buffer.seek(0)
                
                _send_email_with_attachment(
                    recipient_email,
                    f"LEDES and PDF Invoice for {current_matter_number}",
                    f"Please find the attached LEDES and PDF invoice for matter {current_matter_number}.",
                    pdf_buffer,
                    f"{current_invoice_number}_{current_matter_number}.pdf"
                )
                
            else:
                st.subheader(f"Generated Invoice {i + 1}")
                st.text_area("LEDES 1998B Content", ledes_content, height=200)
                
                col1, col2 = st.columns(2)
                with col1:
                    st.download_button(
                        label="Download LEDES File",
                        data=ledes_content.encode('utf-8'),
                        file_name=file_name,
                        mime="text/plain",
                        key=f"download_ledes_{i}"
                    )
                with col2:
                    if include_pdf:
                        pdf_buffer = _create_pdf_invoice(df_invoice, total_amount, current_invoice_number, billing_start_date, billing_end_date)
                        st.download_button(
                            label="Download PDF Invoice",
                            data=pdf_buffer,
                            file_name=f"{current_invoice_number}_{current_matter_number}.pdf",
                            mime="application/pdf",
                            key=f"download_pdf_{i}"
                        )
                    
            if multiple_periods:
                # Move to the previous month for the next invoice
                end_of_current_period = billing_start_date - datetime.timedelta(days=1)
                start_of_current_period = end_of_current_period.replace(day=1)
                billing_start_date = start_of_current_period
                billing_end_date = end_of_current_period
        
        st.success("Invoice generation complete!")