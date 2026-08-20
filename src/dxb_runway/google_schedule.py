from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import secrets
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any


SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
SHEETS_ORIGIN = "https://sheets.googleapis.com"
PUBLIC_SHEETS_ORIGIN = "https://docs.google.com"
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
KEYCHAIN_SERVICE = "com.dxb-runway-intelligence.google-schedule-readonly"


class GoogleScheduleError(RuntimeError):
    pass


class _TokenStore:
    def __init__(self, account: str): self.account=account
    def load(self)->dict[str,Any]:
        result=subprocess.run(["/usr/bin/security","find-generic-password","-s",KEYCHAIN_SERVICE,"-a",self.account,"-w"],capture_output=True,text=True)
        if result.returncode:return {}
        try:return json.loads(result.stdout)
        except json.JSONDecodeError:return {}
    def save(self,value:dict[str,Any])->None:
        result=subprocess.run(["/usr/bin/security","add-generic-password","-U","-s",KEYCHAIN_SERVICE,"-a",self.account,"-w",json.dumps(value)],capture_output=True,text=True)
        if result.returncode:raise GoogleScheduleError("macOS Keychain could not securely save Google access.")
    def delete(self)->None:
        subprocess.run(["/usr/bin/security","delete-generic-password","-s",KEYCHAIN_SERVICE,"-a",self.account],capture_output=True,text=True)


class GoogleSheetsReadOnlyClient:
    """Capability-limited client: the Sheets API transport can only issue GET requests."""
    def __init__(self):
        self.client_id=os.environ.get("DXB_GOOGLE_OAUTH_CLIENT_ID","").strip()
        self.client_secret=os.environ.get("DXB_GOOGLE_OAUTH_CLIENT_SECRET","").strip()
        self.tokens=_TokenStore(self.client_id) if self.client_id else None

    def connected(self)->bool:return True

    def connection_mode(self)->str:
        return "oauth" if self.tokens and self.tokens.load().get("refresh_token") else "public_readonly"

    def disconnect(self)->None:
        if self.tokens:self.tokens.delete()

    def authorize(self)->None:
        if not self.client_id:raise GoogleScheduleError("OAuth is optional because this rota already provides a public read-only feed. Set DXB_GOOGLE_OAUTH_CLIENT_ID only if management later disables that feed.")
        verifier=secrets.token_urlsafe(64);challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=");state=secrets.token_urlsafe(24);result:dict[str,str]={}
        class Handler(BaseHTTPRequestHandler):
            def do_GET(handler):
                query=urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query);result["code"]=(query.get("code") or [""])[0];result["state"]=(query.get("state") or [""])[0];result["error"]=(query.get("error") or [""])[0]
                body=b"DXB Runway Google Schedule connected read-only. You may close this window.";handler.send_response(200);handler.send_header("Content-Type","text/plain");handler.send_header("Content-Length",str(len(body)));handler.end_headers();handler.wfile.write(body)
            def log_message(self,*args):pass
        server=HTTPServer(("127.0.0.1",0),Handler);server.timeout=180;redirect=f"http://127.0.0.1:{server.server_port}/callback"
        params={"client_id":self.client_id,"redirect_uri":redirect,"response_type":"code","scope":SCOPE,"access_type":"offline","prompt":"consent","state":state,"code_challenge":challenge,"code_challenge_method":"S256"}
        webbrowser.open(f"{AUTH_URL}?{urllib.parse.urlencode(params)}");server.handle_request();server.server_close()
        if result.get("error"):raise GoogleScheduleError(f"Google access was not granted: {result['error']}")
        if not result.get("code") or result.get("state")!=state:raise GoogleScheduleError("Google authentication expired or returned an invalid response.")
        token=self._oauth_post({"client_id":self.client_id,"client_secret":self.client_secret,"code":result["code"],"code_verifier":verifier,"grant_type":"authorization_code","redirect_uri":redirect})
        if token.get("scope") and set(str(token["scope"]).split())!={SCOPE}:raise GoogleScheduleError("Google returned an unexpected permission scope. Connection rejected.")
        token["expires_at"]=time.time()+float(token.get("expires_in",3600))-60;self.tokens.save(token)

    def _oauth_post(self,data:dict[str,str])->dict[str,Any]:
        request=urllib.request.Request(TOKEN_URL,data=urllib.parse.urlencode({k:v for k,v in data.items() if v}).encode(),headers={"Content-Type":"application/x-www-form-urlencoded"},method="POST")
        try:
            with urllib.request.urlopen(request,timeout=30) as response:return json.loads(response.read())
        except (urllib.error.URLError,urllib.error.HTTPError,json.JSONDecodeError):raise GoogleScheduleError("Google authentication failed or expired.") from None

    def _access_token(self)->str:
        if not self.tokens:raise GoogleScheduleError("Google OAuth is not configured.")
        token=self.tokens.load()
        if token.get("access_token") and float(token.get("expires_at",0))>time.time():return str(token["access_token"])
        if not token.get("refresh_token"):raise GoogleScheduleError("Google Schedule is not connected or access has expired.")
        refreshed=self._oauth_post({"client_id":self.client_id,"client_secret":self.client_secret,"refresh_token":str(token["refresh_token"]),"grant_type":"refresh_token"})
        token.update(refreshed);token["expires_at"]=time.time()+float(refreshed.get("expires_in",3600))-60;self.tokens.save(token);return str(token["access_token"])

    def _sheets_get(self,url:str)->dict[str,Any]:
        if not url.startswith(SHEETS_ORIGIN+"/"):raise GoogleScheduleError("Blocked non-Sheets API destination.")
        request=urllib.request.Request(url,headers={"Authorization":f"Bearer {self._access_token()}","Accept":"application/json"},method="GET")
        if request.get_method()!="GET":raise GoogleScheduleError("Blocked: Google Sheets integration is strictly read-only.")
        try:
            with urllib.request.urlopen(request,timeout=30) as response:return json.loads(response.read())
        except urllib.error.HTTPError as error:
            if error.code in {401,403}:raise GoogleScheduleError("Google access expired or this account no longer has permission. Using the last cached rota.") from None
            if error.code==404:raise GoogleScheduleError("The management spreadsheet or SCHEDULE 2026 tab is unavailable. Using the last cached rota.") from None
            raise GoogleScheduleError(f"Google Sheets could not be read (HTTP {error.code}). Using cached rota.") from None
        except (urllib.error.URLError,json.JSONDecodeError):raise GoogleScheduleError("Google Sheets is temporarily unavailable. Using the last cached rota.") from None

    def get_spreadsheet_values(self,spreadsheet_id:str,sheet_name:str)->list[list[str]]:
        if self.connection_mode()=="oauth":
            range_name=urllib.parse.quote(f"'{sheet_name}'",safe="");url=f"{SHEETS_ORIGIN}/v4/spreadsheets/{urllib.parse.quote(spreadsheet_id,safe='')}/values/{range_name}?majorDimension=ROWS&valueRenderOption=FORMATTED_VALUE"
            return self._sheets_get(url).get("values") or []
        return self._public_csv_get(spreadsheet_id,sheet_name)

    def _public_csv_get(self,spreadsheet_id:str,sheet_name:str)->list[list[str]]:
        url=f"{PUBLIC_SHEETS_ORIGIN}/spreadsheets/d/{urllib.parse.quote(spreadsheet_id,safe='')}/gviz/tq?{urllib.parse.urlencode({'tqx':'out:csv','sheet':sheet_name})}"
        if not url.startswith(PUBLIC_SHEETS_ORIGIN+"/spreadsheets/d/"):raise GoogleScheduleError("Blocked non-Google spreadsheet destination.")
        request=urllib.request.Request(url,headers={"Accept":"text/csv"},method="GET")
        if request.get_method()!="GET":raise GoogleScheduleError("Blocked: Google Schedule integration is strictly read-only.")
        try:
            with urllib.request.urlopen(request,timeout=30) as response:return list(csv.reader(io.StringIO(response.read().decode("utf-8-sig"))))
        except urllib.error.HTTPError as error:
            if error.code in {401,403}:raise GoogleScheduleError("The rota's read-only feed is no longer available. Using the last cached rota.") from None
            raise GoogleScheduleError(f"Google Schedule could not be read (HTTP {error.code}). Using cached rota.") from None
        except (urllib.error.URLError,UnicodeDecodeError,csv.Error):raise GoogleScheduleError("Google Schedule is temporarily unavailable. Using the last cached rota.") from None
