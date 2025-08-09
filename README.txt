
# LEDES Invoice Generator (Web)

This is a Streamlit version of your Tkinter-based LEDES invoice generator. It runs in a browser, so you can host it on a server/VM and access it remotely from your Windows laptop.

## Run locally
```bash
pip install -r requirements.txt
streamlit run app.py --server.port 8501
```
Then open http://localhost:8501

## Host in the cloud (easy ways)
- **Any VM** (Windows or Linux): run the two commands above. Access at `http://<server-ip>:8501` (prefer tunneling with **Tailscale** or **Cloudflare Tunnel** instead of opening ports).
- **Streamlit Community Cloud**: create a repo with these files and deploy. (No SSH/RDP needed.)

## Features
- Upload `timekeeper` CSV and optional custom task/activity CSV
- Generate **LEDES 1998B** or **LEDES XML 2.1** (optional XSD validation if you upload LEDES214.xsd)
- Optional **PDF** invoice (ReportLab)
- Download all generated files as a single ZIP

## Notes
- Email sending is not included in this web version; it’s best done by your MTA or a background job.
- If LEDES XML is selected without `lxml`, install it (it's in `requirements.txt`).
- If PDF generation errors, ensure `reportlab` is installed (also in `requirements.txt`).

