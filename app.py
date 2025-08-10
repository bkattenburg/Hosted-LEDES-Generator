
import io
import os
import re
import zipfile
import random
import datetime
from dataclasses import dataclass
from typing import List, Tuple, Dict, Any

import smtplib, ssl
from email.message import EmailMessage

import streamlit as st
import pandas as pd
from faker import Faker

# Image/PIL for .ico -> PNG conversion
from PIL import Image as PILImage, ImageDraw, ImageFont

# Optional deps for XML + PDF (guarded)
try:
    from lxml import etree  # type: ignore
    HAS_LXML = True
except Exception:
    HAS_LXML = False

try:
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from reportlab.lib.utils import ImageReader
    HAS_REPORTLAB = True
except Exception:
    HAS_REPORTLAB = False


# ------------------------
# Constants / Defaults
# ------------------------
EXPENSE_CODES = {
    "Copying": "E101",
    "Outside printing": "E102",
    "Word processing": "E103",
    "Facsimile": "E104",
    "Telephone": "E105",
    "Online research": "E106",
    "Delivery services/messengers": "E107",
    "Postage": "E108",
    "Local travel": "E109",
    "Out-of-town travel": "E110",
    "Meals": "E111",
    "Court fees": "E112",
    "Subpoena fees": "E113",
    "Witness fees": "E114",
    "Deposition transcripts": "E115",
    "Trial transcripts": "E116",
    "Trial exhibits": "E117",
    "Litigation support vendors": "E118",
    "Experts": "E119",
    "Private investigators": "E120",
    "Arbitrators/mediators": "E121",
    "Local counsel": "E122",
    "Other professionals": "E123",
    "Other": "E124",
}
EXPENSE_DESCRIPTIONS = list(EXPENSE_CODES.keys())
OTHER_EXPENSE_DESCRIPTIONS = [d for d in EXPENSE_DESCRIPTIONS if EXPENSE_CODES[d] != "E101"]

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

TIMEKEEPER_REQUIRED_COLS = ["TIMEKEEPER_NAME", "TIMEKEEPER_CLASSIFICATION", "TIMEKEEPER_ID", "RATE"]
CUSTOM_REQUIRED_COLS = ["TASK_CODE", "ACTIVITY_CODE", "DESCRIPTION"]

fake = Faker()




# ------------------------
# Helpers: Icon bundling
# ------------------------

def _generate_default_nm_icon(size: int = 128) -> bytes:
    """Generate a simple 'NM' square icon PNG for Nelson & Murdock when no asset is present."""
    img = PILImage.new("RGBA", (size, size), (25, 25, 25, 255))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", int(size * 0.45))
    except Exception:
        font = ImageFont.load_default()
    text = "NM"
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
    except Exception:
        # Fallback if textbbox not supported for this font
        tw, th = draw.textsize(text, font=font)
    draw.text(((size - tw) / 2, (size - th) / 2), text, fill=(255, 255, 255, 255), font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()



def get_nm_icon_png_bytes() -> bytes:
    """Return PNG bytes for the Nelson & Murdock icon, converting from ICO if needed, or generate a default."""
    ico_path = os.path.join(os.getcwd(), "assets", "nelson_murdock.ico")
    png_path = os.path.join(os.getcwd(), "assets", "nelson_murdock.png")

    if os.path.exists(ico_path):
        try:
            with PILImage.open(ico_path) as im:
                if hasattr(im, "n_frames"):
                    best = 0
                    best_size = 0
                    for i in range(getattr(im, "n_frames", 1)):
                        im.seek(i)
                        w, h = im.size
                        if w * h > best_size:
                            best = i
                            best_size = w * h
                    im.seek(best)
                buf = io.BytesIO()
                im.save(buf, format="PNG")
                return buf.getvalue()
        except Exception:
            pass

    if os.path.exists(png_path):
        try:
            with open(png_path, "rb") as f:
                return f.read()
        except Exception:
            pass

    return _generate_default_nm_icon(size=128)

# ------------------------
# Utility / Core functions
# ------------------------
def load_timekeepers(file) -> List[Dict[str, Any]]:
    df = pd.read_csv(file)
    if not all(c in df.columns for c in TIMEKEEPER_REQUIRED_COLS):
        raise ValueError(f"Timekeeper CSV must contain: {', '.join(TIMEKEEPER_REQUIRED_COLS)}")
    return df.to_dict(orient="records")


def load_custom_tasks(file) -> List[Tuple[str, str, str]]:
    df = pd.read_csv(file)
    if not all(c in df.columns for c in CUSTOM_REQUIRED_COLS):
        raise ValueError(f"Custom Task/Activity CSV must contain: {', '.join(CUSTOM_REQUIRED_COLS)}")
    if df.empty:
        raise ValueError("Custom Task/Activity CSV is empty.")
    out = []
    for _, r in df.iterrows():
        out.append((str(r["TASK_CODE"]), str(r["ACTIVITY_CODE"]), str(r["DESCRIPTION"])))
    return out


def replace_description_dates(desc: str) -> str:
    pattern = r"\\b(\\d{2}/\\d{2}/\\d{4})\\b"
    if re.search(pattern, desc):
        days_ago = random.randint(15, 90)
        new_date = (datetime.date.today() - datetime.timedelta(days=days_ago)).strftime("%m/%d/%Y")
        return re.sub(pattern, new_date, desc)
    return desc


def replace_name_placeholder(desc: str) -> str:
    return desc.replace("{NAME_PLACEHOLDER}", fake.name())


def generate_invoice_rows(
    fee_count: int,
    expense_count: int,
    timekeepers: List[Dict[str, Any]],
    client_id: str,
    law_firm_id: str,
    invoice_desc: str,
    billing_start_date: datetime.date,
    billing_end_date: datetime.date,
    task_activity_desc: List[Tuple[str, str, str]],
    major_task_codes: set,
    include_block_billed: bool,
    max_hours_per_tk_per_day: int = 16,
) -> Tuple[List[Dict[str, Any]], float]:
    rows = []
    delta_days = (billing_end_date - billing_start_date).days + 1
    major_items = [t for t in task_activity_desc if t[0] in major_task_codes]
    other_items = [t for t in task_activity_desc if t[0] not in major_task_codes]

    current_invoice_total = 0.0
    daily_hours_tracker: Dict[Tuple[str, str], float] = {}

    # Fees
    for _ in range(fee_count):
        if not task_activity_desc:
            break
        tk_row = random.choice(timekeepers)
        timekeeper_id = tk_row["TIMEKEEPER_ID"]

        if major_items and random.random() < 0.7:
            task_code, activity_code, description = random.choice(major_items)
        elif other_items:
            task_code, activity_code, description = random.choice(other_items)
        else:
            continue

        offset = random.randint(0, delta_days - 1)
        line_date = billing_start_date + datetime.timedelta(days=offset)
        line_date_str = line_date.strftime("%Y-%m-%d")

        current_hours = daily_hours_tracker.get((line_date_str, timekeeper_id), 0.0)
        remaining = max_hours_per_tk_per_day - current_hours
        if remaining <= 0:
            continue

        hours_to_bill = round(random.uniform(0.5, min(8.0, remaining)), 1)
        if hours_to_bill <= 0:
            continue

        rate = float(tk_row["RATE"])
        line_total = round(hours_to_bill * rate, 2)
        current_invoice_total += line_total
        daily_hours_tracker[(line_date_str, timekeeper_id)] = current_hours + hours_to_bill

        description = replace_description_dates(description)
        description = replace_name_placeholder(description)

        rows.append({
            "INVOICE_DESCRIPTION": invoice_desc,
            "CLIENT_ID": client_id,
            "LAW_FIRM_ID": law_firm_id,
            "LINE_ITEM_DATE": line_date_str,
            "TIMEKEEPER_NAME": tk_row["TIMEKEEPER_NAME"],
            "TIMEKEEPER_CLASSIFICATION": tk_row["TIMEKEEPER_CLASSIFICATION"],
            "TIMEKEEPER_ID": timekeeper_id,
            "TASK_CODE": task_code,
            "ACTIVITY_CODE": activity_code,
            "EXPENSE_CODE": "",
            "DESCRIPTION": description,
            "HOURS": hours_to_bill,
            "RATE": rate,
            "LINE_ITEM_TOTAL": line_total
        })

    # Expenses: ensure 1-3 E101
    e101_count = random.randint(1, min(3, expense_count))
    for _ in range(e101_count):
        description = "Copying"
        expense_code = "E101"
        units = random.randint(1, 200)
        rate = round(random.uniform(0.14, 0.25), 2)
        offset = random.randint(0, delta_days - 1)
        line_date = billing_start_date + datetime.timedelta(days=offset)
        line_total = round(units * rate, 2)
        current_invoice_total += line_total
        rows.append({
            "INVOICE_DESCRIPTION": invoice_desc,
            "CLIENT_ID": client_id,
            "LAW_FIRM_ID": law_firm_id,
            "LINE_ITEM_DATE": line_date.strftime("%Y-%m-%d"),
            "TIMEKEEPER_NAME": "",
            "TIMEKEEPER_CLASSIFICATION": "",
            "TIMEKEEPER_ID": "",
            "TASK_CODE": "",
            "ACTIVITY_CODE": "",
            "EXPENSE_CODE": expense_code,
            "DESCRIPTION": description,
            "HOURS": units,
            "RATE": rate,
            "LINE_ITEM_TOTAL": line_total
        })

    remaining = expense_count - e101_count
    for _ in range(max(0, remaining)):
        if not OTHER_EXPENSE_DESCRIPTIONS:
            break
        description = random.choice(OTHER_EXPENSE_DESCRIPTIONS)
        expense_code = EXPENSE_CODES[description]
        units = 1
        rate = round(random.uniform(25, 200), 2)
        offset = random.randint(0, delta_days - 1)
        line_date = billing_start_date + datetime.timedelta(days=offset)
        line_total = round(units * rate, 2)
        current_invoice_total += line_total
        description = replace_description_dates(description)
        description = replace_name_placeholder(description)
        rows.append({
            "INVOICE_DESCRIPTION": invoice_desc,
            "CLIENT_ID": client_id,
            "LAW_FIRM_ID": law_firm_id,
            "LINE_ITEM_DATE": line_date.strftime("%Y-%m-%d"),
            "TIMEKEEPER_NAME": "",
            "TIMEKEEPER_CLASSIFICATION": "",
            "TIMEKEEPER_ID": "",
            "TASK_CODE": "",
            "ACTIVITY_CODE": "",
            "EXPENSE_CODE": expense_code,
            "DESCRIPTION": description,
            "HOURS": units,
            "RATE": rate,
            "LINE_ITEM_TOTAL": line_total
        })

    # Block-billing toggle: if disabled, strip rows with '; '
    if not include_block_billed:
        rows = [r for r in rows if '; ' not in r["DESCRIPTION"]]

    return rows, current_invoice_total


def create_ledes_line_1998b(row: Dict[str, Any],
                             line_no: int,
                             inv_total: float,
                             bill_start: datetime.date,
                             bill_end: datetime.date,
                             invoice_number: str,
                             matter_number: str) -> List[str]:
    date_obj = datetime.datetime.strptime(row["LINE_ITEM_DATE"], "%Y-%m-%d").date()
    hours = float(row["HOURS"])
    rate = float(row["RATE"])
    line_total = float(row["LINE_ITEM_TOTAL"])

    is_expense = bool(row["EXPENSE_CODE"])
    adj_type = "E" if is_expense else "F"
    task_code = "" if is_expense else row.get("TASK_CODE", "")
    activity_code = "" if is_expense else row.get("ACTIVITY_CODE", "")
    expense_code = row.get("EXPENSE_CODE", "") if is_expense else ""
    timekeeper_id = "" if is_expense and not row.get("TIMEKEEPER_ID") else row.get("TIMEKEEPER_ID", "")
    timekeeper_class = "" if is_expense and not row.get("TIMEKEEPER_CLASSIFICATION") else row.get("TIMEKEEPER_CLASSIFICATION", "")
    timekeeper_name = "" if is_expense and not row.get("TIMEKEEPER_NAME") else row.get("TIMEKEEPER_NAME", "")

    return [
        bill_end.strftime("%Y%m%d"),
        invoice_number,
        str(row.get("CLIENT_ID", "")),
        matter_number,
        f"{inv_total:.2f}",
        bill_start.strftime("%Y%m%d"),
        bill_end.strftime("%Y%m%d"),
        str(row.get("INVOICE_DESCRIPTION", "")),
        str(line_no),
        adj_type,
        f"{hours:.1f}" if adj_type == "F" else f"{int(hours)}",
        "0.00",
        f"{line_total:.2f}",
        date_obj.strftime("%Y%m%d"),
        task_code,
        expense_code,
        activity_code,
        timekeeper_id,
        str(row.get("DESCRIPTION", "")),
        str(row.get("LAW_FIRM_ID", "")),
        f"{rate:.2f}",
        timekeeper_name,
        timekeeper_class,
        matter_number
    ]


def create_ledes_1998b_content(rows: List[Dict[str, Any]], inv_total: float,
                               bill_start: datetime.date, bill_end: datetime.date,
                               invoice_number: str, matter_number: str) -> str:
    header = "LEDES1998B[]"
    fields = ("INVOICE_DATE|INVOICE_NUMBER|CLIENT_ID|LAW_FIRM_MATTER_ID|INVOICE_TOTAL|BILLING_START_DATE|"
              "BILLING_END_DATE|INVOICE_DESCRIPTION|LINE_ITEM_NUMBER|EXP/FEE/INV_ADJ_TYPE|"
              "LINE_ITEM_NUMBER_OF_UNITS|LINE_ITEM_ADJUSTMENT_AMOUNT|LINE_ITEM_TOTAL|LINE_ITEM_DATE|"
              "LINE_ITEM_TASK_CODE|LINE_ITEM_EXPENSE_CODE|LINE_ITEM_ACTIVITY_CODE|TIMEKEEPER_ID|"
              "LINE_ITEM_DESCRIPTION|LAW_FIRM_ID|LINE_ITEM_UNIT_COST|TIMEKEEPER_NAME|"
              "TIMEKEEPER_CLASSIFICATION|CLIENT_MATTER_ID[]")
    lines = [header, fields]
    for i, r in enumerate(rows, start=1):
        line = create_ledes_line_1998b(r, i, inv_total, bill_start, bill_end, invoice_number, matter_number)
        lines.append("|".join(map(str, line)) + "[]")
    return "\n".join(lines)


def create_ledes_xml21_content(rows: List[Dict[str, Any]], inv_total: float,
                               bill_start: datetime.date, bill_end: datetime.date,
                               invoice_number: str, matter_number: str,
                               xsd_bytes: bytes | None = None) -> str:
    if not HAS_LXML:
        raise RuntimeError("lxml is not installed. Add 'lxml' to requirements.")

    NSMAP = {None: "http://www.ledes.org/LEDES214", "xsi": "http://www.w3.org/2001/XMLSchema-instance"}
    ledes_root = etree.Element("LEDES", nsmap=NSMAP, attrib={"version": "2.1",
        "{http://www.w3.org/2001/XMLSchema-instance}schemaLocation":"http://www.ledes.org/LEDES214 LEDES214.xsd"})

    invoice_seg = etree.SubElement(ledes_root, "invoice")
    etree.SubElement(invoice_seg, "inv_number").text = str(invoice_number)
    etree.SubElement(invoice_seg, "client_id").text = str(rows[0].get("CLIENT_ID", "")) if rows else ""
    etree.SubElement(invoice_seg, "matter_id").text = str(matter_number)
    etree.SubElement(invoice_seg, "inv_total").text = f"{inv_total:.2f}"
    etree.SubElement(invoice_seg, "bill_start_date").text = bill_start.strftime("%Y-%m-%d")
    etree.SubElement(invoice_seg, "bill_end_date").text = bill_end.strftime("%Y-%m-%d")
    etree.SubElement(invoice_seg, "inv_date").text = bill_end.strftime("%Y-%m-%d")
    etree.SubElement(invoice_seg, "inv_desc").text = str(rows[0].get("INVOICE_DESCRIPTION", "")) if rows else ""

    fees_seg = etree.SubElement(invoice_seg, "fees")
    expenses_seg = etree.SubElement(invoice_seg, "expenses")

    fee_counter = 1
    expense_counter = 1
    for row in rows:
        is_expense = bool(row.get("EXPENSE_CODE"))
        if is_expense:
            exp_item = etree.SubElement(expenses_seg, "expense", id=f"E{expense_counter}")
            expense_counter += 1
            etree.SubElement(exp_item, "date").text = row.get("LINE_ITEM_DATE", "")
            etree.SubElement(exp_item, "exp_code", id=row.get("EXPENSE_CODE", ""))
            etree.SubElement(exp_item, "desc").text = row.get("DESCRIPTION", "")
            etree.SubElement(exp_item, "quant").text = str(row.get("HOURS", ""))
            etree.SubElement(exp_item, "rate").text = f"{row.get('RATE', 0):.2f}"
            etree.SubElement(exp_item, "cost").text = f"{row.get('LINE_ITEM_TOTAL', 0):.2f}"
        else:
            fee_item = etree.SubElement(fees_seg, "fee", id=f"F{fee_counter}")
            fee_counter += 1
            etree.SubElement(fee_item, "date").text = row.get("LINE_ITEM_DATE", "")
            tk_item = etree.SubElement(fee_item, "tk", id=row.get("TIMEKEEPER_ID", ""))
            etree.SubElement(tk_item, "name").text = row.get("TIMEKEEPER_NAME", "")
            etree.SubElement(tk_item, "level").text = row.get("TIMEKEEPER_CLASSIFICATION", "")
            etree.SubElement(fee_item, "task", id=row.get("TASK_CODE", ""))
            etree.SubElement(fee_item, "activity", id=row.get("ACTIVITY_CODE", ""))
            etree.SubElement(fee_item, "desc").text = row.get("DESCRIPTION", "")
            etree.SubElement(fee_item, "quant").text = f"{row.get('HOURS', 0):.1f}"
            etree.SubElement(fee_item, "rate").text = f"{row.get('RATE', 0):.2f}"
            etree.SubElement(fee_item, "cost").text = f"{row.get('LINE_ITEM_TOTAL', 0):.2f}"

    xml_bytes = etree.tostring(ledes_root, pretty_print=True, xml_declaration=True, encoding="UTF-8")

    # Optional validation if XSD provided
    if xsd_bytes:
        try:
            xsd_doc = etree.fromstring(xsd_bytes)
            xsd = etree.XMLSchema(xsd_doc)
            xml_doc = etree.fromstring(xml_bytes)
            xsd.assertValid(xml_doc)
        except Exception as e:
            st.warning(f"XML validation failed (file will still be generated): {e}")

    return xml_bytes.decode("utf-8")


def create_pdf(invoice_rows: List[Dict[str, Any]], invoice_number: str,
               invoice_date: datetime.date, billing_start_date: datetime.date,
               billing_end_date: datetime.date,
               client_id: str, law_firm_id: str) -> bytes:
    if not HAS_REPORTLAB:
        raise RuntimeError("reportlab is not installed. Add 'reportlab' to requirements.")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter,
                            leftMargin=1.0*inch, rightMargin=1.0*inch,
                            topMargin=1.0*inch, bottomMargin=1.0*inch)
    styles = getSampleStyleSheet()
    available_width = doc.width
    elements = []

    # Law firm + client
    if law_firm_id.strip() == "02-1234567":
        law_firm_info = f"<b>Nelson and Murdock</b><br/>{law_firm_id}<br/>One Park Avenue<br/>Manhattan, NY 10003"
    else:
        law_firm_info = f"<b>Your Law Firm Name</b><br/>{law_firm_id}<br/>1001 Main Street, Big City, CA 90000"

    if client_id.strip() == "02-4388252":
        client_info = f"<b>A Onit Inc.</b><br/>{client_id}<br/>1360 Post Oak Blvd<br/>Houston, TX 77056"
    else:
        client_info = f"<b>Your Company Name</b><br/>{client_id}<br/>1000 Main Street, Big City, CA 90000"

    left_style = ParagraphStyle(name="Left", parent=styles["Normal"], alignment=TA_LEFT, leading=12)
    right_style = ParagraphStyle(name="Right", parent=styles["Normal"], alignment=TA_RIGHT)

    header_data = [[Paragraph(law_firm_info, left_style), Paragraph(client_info, left_style)]]
    header_table = Table(header_data, colWidths=[available_width/2, available_width/2])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOX', (0,0), (0,0), 1, colors.black),
        ('BOX', (1,0), (1,0), 1, colors.black),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ('ALIGN', (0,0), (0,0), 'LEFT'),
        ('ALIGN', (1,0), (1,0), 'LEFT'),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 0.10*inch))

    details_text = (f"<b>Invoice #:</b> {invoice_number}<br/>"
                    f"<b>Invoice Date:</b> {invoice_date.strftime('%Y-%m-%d')}<br/>"
                    f"<b>Billing Period:</b> {billing_start_date.strftime('%Y-%m-%d')} to {billing_end_date.strftime('%Y-%m-%d')}")
    details_para = Paragraph(details_text, right_style)
    details_table = Table([['', details_para]], colWidths=[available_width/2, available_width/2])
    details_table.setStyle(TableStyle([('ALIGN', (1, 0), (1, 0), 'RIGHT'),
                                       ('VALIGN', (0,0), (-1,-1), 'TOP'),
                                       ('LEFTPADDING', (1,0), (1,0), 6)]))
    elements.append(details_table)
    elements.append(Spacer(1, 0.18*inch))

    # Line items
    table_data = [["Date", "Timekeeper", "Description", "Task\nCode", "Hrs", "Rate", "Total"]]
    total_fees = 0.0
    total_expenses = 0.0
    for r in invoice_rows:
        is_expense = bool(r["EXPENSE_CODE"])
        line_total = float(r["LINE_ITEM_TOTAL"])
        if is_expense:
            total_expenses += line_total
            code = r['EXPENSE_CODE']
            hrs = f"{int(r['HOURS'])}"
            rate = f"${r['RATE']:.2f}"
        else:
            total_fees += line_total
            code = r['TASK_CODE']
            hrs = f"{r['HOURS']:.1f}"
            rate = f"${r['RATE']:.2f}"
        date_str = datetime.datetime.strptime(r['LINE_ITEM_DATE'], '%Y-%m-%d').strftime('%m/%d/%Y')
        table_data.append([date_str, r['TIMEKEEPER_NAME'], Paragraph(r['DESCRIPTION'], styles['Normal']), code, hrs, rate, f"${line_total:,.2f}"])

    line_item_table = Table(table_data, colWidths=[60, 100, 240, 50, 30, 60, 60])
    line_item_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (4, 1), (-1, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    elements.append(line_item_table)
    elements.append(Spacer(1, 0.25*inch))

    invoice_total = total_fees + total_expenses
    total_right_style = ParagraphStyle(name="TotalRight", parent=styles["Normal"], alignment=TA_RIGHT)
    summary_data = [
        ['Total Fees:', f"${total_fees:,.2f}"],
        ['Total Expenses:', f"${total_expenses:,.2f}"],
        ['Invoice Total:', Paragraph(f"<b>${invoice_total:,.2f}</b>", total_right_style)]
    ]
    summary_table = Table(summary_data, colWidths=[2.5*inch, 1.5*inch], hAlign='RIGHT')
    summary_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, -1), (1, -1), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('LINEBELOW', (0, -2), (1, -2), 1, colors.grey),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    elements.append(summary_table)
    doc.build(elements)
    return buffer.getvalue()


# ------------------------
# Streamlit UI
# ------------------------
st.set_page_config(page_title="LEDES Invoice Generator (Web)", layout="wide")
st.title("LEDES Invoice Generator (Web)")

with st.sidebar:
    st.header("Inputs")
    fee_count = st.number_input("# of Fee Line Items", min_value=1, value=10, step=1)
    expense_count = st.number_input("# of Expense Line Items", min_value=1, value=5, step=1)
    max_hours = st.slider("Max Daily Hours per Timekeeper", 1, 24, 16)
    include_block = st.checkbox("Include Block-Billed Lines", value=True)

    st.markdown("---")
    st.subheader("Timekeepers CSV")
    tk_csv = st.file_uploader("Upload timekeeper CSV", type=["csv"])

    st.subheader("Custom Task/Activity CSV (optional)")
    custom_csv = st.file_uploader("Upload custom_details.csv", type=["csv"])

    st.markdown("---")
    st.subheader("Invoice & Matter")
    client_id = st.text_input("Client ID", value=DEFAULT_CLIENT_ID)
    law_firm_id = st.text_input("Law Firm ID", value=DEFAULT_LAW_FIRM_ID)
    invoice_desc = st.text_input("Invoice Description", value=DEFAULT_INVOICE_DESCRIPTION)
    matter_number = st.text_input("Matter Number (Base)", value="2025-XXXXXX")
    invoice_number = st.text_input("Invoice Number (Base)", value="2025MMM-XXXXXX")

    st.markdown("---")
    st.subheader("Billing Dates")
    today = datetime.date.today()
    first_day_current = today.replace(day=1)
    last_day_prior = first_day_current - datetime.timedelta(days=1)
    first_day_prior = last_day_prior.replace(day=1)
    billing_start = st.date_input("Billing Start Date", value=first_day_prior)
    billing_end = st.date_input("Billing End Date", value=last_day_prior)

    st.markdown("---")
    st.subheader("Output Options")
    gen_pdf = st.checkbox("Also generate PDF invoice(s)", value=True)
    ledes_version = st.selectbox("LEDES Version", ["1998B", "XML 2.1"])
    xsd_file = None
    if ledes_version == "XML 2.1":
        xsd_file = st.file_uploader("Optional: LEDES214 XSD (for validation)", type=["xsd"])

st.markdown("### Generate")
go = st.button("Generate Invoice Files")

if go:
    if not tk_csv:
        st.error("Please upload the timekeeper CSV.")
        st.stop()

    try:
        tk_data = load_timekeepers(tk_csv)
    except Exception as e:
        st.error(f"Error loading timekeepers: {e}")
        st.stop()

    task_activity_desc = list(DEFAULT_TASK_ACTIVITY_DESC)
    major_codes = set(MAJOR_TASK_CODES)

    if custom_csv is not None:
        try:
            task_activity_desc = load_custom_tasks(custom_csv)
            major_codes = {t[0] for t in task_activity_desc if str(t[0]).startswith('L')}
        except Exception as e:
            st.warning(f"Custom tasks file problem; using defaults. Details: {e}")
            task_activity_desc = list(DEFAULT_TASK_ACTIVITY_DESC)
            major_codes = set(MAJOR_TASK_CODES)

    if billing_start > billing_end:
        st.error("Billing Start Date cannot be after Billing End Date.")
        st.stop()

    # Generate rows
    rows, inv_total = generate_invoice_rows(
        fee_count, expense_count, tk_data, client_id, law_firm_id, invoice_desc,
        billing_start, billing_end, task_activity_desc, major_codes, include_block, max_hours
    )

    # Build outputs
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    outputs: List[Tuple[str, bytes]] = []

    # LEDES
    if ledes_version == "1998B":
        ledes_str = create_ledes_1998b_content(rows, inv_total, billing_start, billing_end, invoice_number, matter_number)
        outputs.append((f"LEDES98B_{invoice_number}_{timestamp}.txt", (ledes_str + "\\n").encode("ascii", errors="ignore")))
    else:
        try:
            xsd_bytes = xsd_file.read() if xsd_file is not None else None
            xml_str = create_ledes_xml21_content(rows, inv_total, billing_start, billing_end, invoice_number, matter_number, xsd_bytes=xsd_bytes)
            outputs.append((f"LEDES_XML21_{invoice_number}_{timestamp}.xml", xml_str.encode("utf-8")))
        except Exception as e:
            st.error(f"XML generation failed: {e}")
            st.stop()

    # PDF
    if gen_pdf:
        try:
            pdf_bytes = create_pdf(rows, invoice_number, billing_end, billing_start, billing_end, client_id, law_firm_id)
            outputs.append((f"Invoice_{invoice_number}_{timestamp}.pdf", pdf_bytes))
        except Exception as e:
            st.warning(f"PDF generation skipped (ReportLab missing or error): {e}")

    # Zip for download
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as z:
        for fname, data in outputs:
            z.writestr(fname, data)
    zip_buf.seek(0)

    st.success(f"Generated {len(outputs)} file(s).")
    st.download_button("Download files as ZIP", data=zip_buf, file_name=f"invoices_{timestamp}.zip", mime="application/zip")

    # Show quick summary table
    fee_line_count = sum(1 for r in rows if not r["EXPENSE_CODE"])
    expense_line_count = sum(1 for r in rows if r["EXPENSE_CODE"])
    st.write(f"**Summary:** ${inv_total:,.2f} total across {fee_line_count} fee lines and {expense_line_count} expense lines.")

    # ------------------------
    # Email sending (expander)
    # ------------------------
    with st.expander("Email these files"):
        st.caption("SMTP credentials are read from Streamlit secrets or environment variables.")

        send_email = st.checkbox("Send email now", value=False)
        to_addr = st.text_input("To", placeholder="recipient@example.com")
        subject = st.text_input("Subject", value=f"LEDES Invoice {invoice_number}")
        body = st.text_area("Message", value=f"Attached are the generated invoice files for {invoice_number}.")

        # Prefer secrets; fall back to env
        smtp_server = st.secrets.get("SMTP_SERVER", os.getenv("SMTP_SERVER", "smtp.gmail.com"))
        smtp_port_raw = st.secrets.get("SMTP_PORT", os.getenv("SMTP_PORT", "465"))
        try:
            smtp_port = int(smtp_port_raw)
        except Exception:
            smtp_port = 465

        email_from = st.secrets.get("EMAIL_FROM", os.getenv("EMAIL_FROM", ""))
        email_password = st.secrets.get("EMAIL_PASSWORD", os.getenv("EMAIL_PASSWORD", ""))

        # Optional: control TLS vs SSL via secrets
        smtp_use_tls_raw = str(st.secrets.get("SMTP_USE_TLS", os.getenv("SMTP_USE_TLS", "false"))).strip().lower()
        smtp_use_tls = smtp_use_tls_raw in ("1", "true", "yes", "on")

        col_a, col_b, col_c = st.columns(3)
        with col_a:
            st.text_input("SMTP server", value=smtp_server, disabled=True)
        with col_b:
            st.text_input("SMTP port", value=str(smtp_port), disabled=True)
        with col_c:
            st.text_input("TLS mode", value=("STARTTLS" if smtp_use_tls else "SSL (implicit)"), disabled=True)

        def _send_email_with_attachments(recipient: str, attachments=None):
            if attachments is None:
                attachments = []

            if not (recipient and email_from and email_password):
                raise RuntimeError("Missing To/From or SMTP credentials. Set EMAIL_FROM/EMAIL_PASSWORD via Secrets or environment.")

            msg = EmailMessage()
            msg["From"] = email_from
            msg["To"] = recipient
            msg["Subject"] = subject
            msg.set_content(body)

            for fname, data in attachments:
                msg.add_attachment(
                    data,
                    maintype="application",
                    subtype="octet-stream",
                    filename=fname
                )

            last_err = None
            if smtp_use_tls:
                try:
                    context = ssl.create_default_context()
                    with smtplib.SMTP(smtp_server, smtp_port, timeout=20) as server:
                        server.ehlo(); server.starttls(context=context); server.ehlo()
                        server.login(email_from, email_password)
                        server.send_message(msg)
                    return "STARTTLS"
                except Exception as e:
                    last_err = e
            else:
                try:
                    context = ssl.create_default_context()
                    with smtplib.SMTP_SSL(smtp_server, smtp_port, context=context, timeout=20) as server:
                        server.login(email_from, email_password)
                        server.send_message(msg)
                    return "SSL"
                except Exception as e:
                    last_err = e

            try:
                if smtp_use_tls:
                    context = ssl.create_default_context()
                    with smtplib.SMTP_SSL(smtp_server, 465, context=context, timeout=20) as server:
                        server.login(email_from, email_password)
                        server.send_message(msg)
                    return "SSL (fallback 465)"
                else:
                    context = ssl.create_default_context()
                    with smtplib.SMTP(smtp_server, 587, timeout=20) as server:
                        server.ehlo(); server.starttls(context=context); server.ehlo()
                        server.login(email_from, email_password)
                        server.send_message(msg)
                    return "STARTTLS (fallback 587)"
            except Exception as e2:
                raise RuntimeError(f"SMTP send failed. First error: {last_err!r}; Fallback error: {e2!r}")

        # Diagnostic buttons
        diag_col1, diag_col2 = st.columns(2)
        with diag_col1:
            if st.button("Test SMTP (no send)"):
                try:
                    if smtp_use_tls:
                        context = ssl.create_default_context()
                        with smtplib.SMTP(smtp_server, smtp_port, timeout=15) as server:
                            server.ehlo(); server.starttls(context=context); server.ehlo()
                            server.login(email_from, email_password)
                    else:
                        context = ssl.create_default_context()
                        with smtplib.SMTP_SSL(smtp_server, smtp_port, context=context, timeout=15) as server:
                            server.login(email_from, email_password)
                    st.success("SMTP connection & login OK.")
                except Exception as e:
                    st.error(f"SMTP test failed: {e!r}")
                    st.caption("Tips: For Gmail, use an App Password and ensure EMAIL_FROM matches the authenticated account.")

        with diag_col2:
            if st.button("Send test to myself"):
                try:
                    mode = _send_email_with_attachments(email_from, attachments=[])
                    st.success(f"Test email sent to {email_from} using {mode}. Check your inbox and spam folder.")
                except Exception as e:
                    st.error(f"Test send failed: {e!r}")

        if send_email and st.button("Send Email Now"):
            try:
                mode = _send_email_with_attachments(to_addr, attachments=outputs)
                st.success(f"Email sent to {to_addr} using {mode}")
            except Exception as e:
                st.error(f"Email failed: {e!r}")
                st.caption("Common fixes: set SMTP_USE_TLS=true + SMTP_PORT=587 (STARTTLS) or use SSL on 465. For Gmail, use an App Password.")
