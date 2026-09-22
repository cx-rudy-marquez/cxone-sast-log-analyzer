import json
import os
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv
from flask import (Flask, make_response, redirect, render_template, request,
                   url_for)

from report_renderer import build_model, render_html

# ---------- Config ----------
load_dotenv()

CX_TENANT   = os.getenv("CX_TENANT", "").strip()
CX_AST_BASE = os.getenv("CX_AST_BASE", "").rstrip("/")
CX_API_KEY  = os.getenv("CX_API_KEY", "").strip()  # refresh token

IAM_TOKEN_URL = f"https://deu.iam.checkmarx.net/auth/realms/{CX_TENANT}/protocol/openid-connect/token"

app = Flask(__name__)

# ---------- Helpers ----------

def exchange_refresh_for_access_token(refresh_token: str) -> str:
    data = {
        "grant_type": "refresh_token",
        "client_id": "ast-app",
        "refresh_token": refresh_token,
    }
    r = requests.post(IAM_TOKEN_URL, data=data, timeout=30)
    r.raise_for_status()
    tok = r.json().get("access_token", "")
    if not tok:
        raise RuntimeError("Token exchange returned no access_token")
    return tok

def fetch_log_text(scan_id: str, bearer: str) -> str:
    url = f"{CX_AST_BASE}/api/logs/{scan_id}/sast"
    headers = {
        "Authorization": f"Bearer {bearer}",
        "Accept": "text/plain, application/json",
    }
    r = requests.get(url, headers=headers, timeout=90)
    r.raise_for_status()
    try:
        return r.text if r.text else json.dumps(r.json())
    except ValueError:
        return r.text

def fetch_scan_meta(scan_id: str, bearer: str) -> dict:
    """GET /api/scans/{scan_id} → projectName, branch, and SAST statusDetails (start/end/loc)."""
    url = f"{CX_AST_BASE}/api/scans/{scan_id}"
    headers = {
        "Authorization": f"Bearer {bearer}",
        "Accept": "application/json",
    }
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    j = r.json()
    # pull SAST block if present
    sast = {}
    for sd in j.get("statusDetails", []) or []:
        if (sd.get("name") or "").lower() == "sast":
            sast = sd
            break
    return {
        "projectName": j.get("projectName"),
        "branch": j.get("branch"),
        "createdAt": j.get("createdAt"),
        "sastStart": sast.get("startDate"),
        "sastEnd":   sast.get("endDate"),
        "sastLOC":   sast.get("loc"),
    }

# ---------- Routes ----------

@app.get("/")
def index():
    env_ok = all([CX_TENANT, CX_AST_BASE, CX_API_KEY])
    return render_template(
        "index.html",
        env_ok=env_ok,
        tenant=CX_TENANT,
        ast_base=CX_AST_BASE,
    )

@app.post("/report")
def report_post():
    scan_id = (request.form.get("scan_id") or "").strip()
    if not scan_id:
        return render_template("error.html", title="Missing scan_id", message="Please enter a scan_id."), 400
    return redirect(url_for("report_get", scan_id=scan_id))

@app.get("/report/<scan_id>")
def report_get(scan_id: str):
    try:
        token = exchange_refresh_for_access_token(CX_API_KEY)

        # 1) scan metadata (project/branch + SAST start/end/loc)
        meta_from_scan = fetch_scan_meta(scan_id, token)

        # 2) raw SAST log text
        raw_text = fetch_log_text(scan_id, token)

        # merge into renderer meta
        meta = {
            "notice": "Generated per log.",
            "scanId": scan_id,
            "projectName": meta_from_scan.get("projectName") or "",
            "branch": meta_from_scan.get("branch") or "",
            "createdAt": meta_from_scan.get("createdAt") or "",
            "sastStart": meta_from_scan.get("sastStart") or "",
            "sastEnd":   meta_from_scan.get("sastEnd") or "",
            "sastLOC":   meta_from_scan.get("sastLOC"),
        }

        model = build_model(raw_text, meta_from_event=meta)
        html_doc = render_html(meta, model)
        resp = make_response(html_doc)
        resp.headers["Content-Type"] = "text/html; charset=utf-8"
        return resp

    except requests.HTTPError as e:
        body = e.response.text[:2000] if e.response is not None else ""
        return render_template("error.html", title="HTTP Error", message=f"{e}", details=body), (
            e.response.status_code if e.response is not None else 502
        )
    except Exception as e:
        return render_template("error.html", title="Unexpected Error", message=str(e), details=""), 500



@app.get("/download/<scan_id>")
def download_report(scan_id: str):
    try:
        token = exchange_refresh_for_access_token(CX_API_KEY)
        meta_from_scan = fetch_scan_meta(scan_id, token)
        raw_text = fetch_log_text(scan_id, token)
        meta = {
            "notice": "Generated per log.",
            "scanId": scan_id,
            "projectName": meta_from_scan.get("projectName") or "",
            "branch": meta_from_scan.get("branch") or "",
            "createdAt": meta_from_scan.get("createdAt") or "",
            "sastStart": meta_from_scan.get("sastStart") or "",
            "sastEnd":   meta_from_scan.get("sastEnd") or "",
            "sastLOC":   meta_from_scan.get("sastLOC"),
        }
        html_doc = render_html(meta, build_model(raw_text, meta_from_event=meta))
        resp = make_response(html_doc)
        resp.headers["Content-Type"] = "text/html; charset=utf-8"
        resp.headers["Content-Disposition"] = f'attachment; filename="cxone_sast_log_{scan_id}.html"'
        return resp
    except Exception as e:
        return render_template("error.html", title="Download failed", message=str(e)), 500

@app.get("/healthz")
def healthz():
    return {"ok": True}, 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8500")), debug=True)
