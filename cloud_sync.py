"""
模組名稱：cloud_sync.py
版本識別：20261109_2235
修改目的：
1. 透過 Streamlit Secrets 讀取服務帳戶憑證與 folder_id。
2. 建立 Google Drive 雲端檔案同步機制（下載歷史快取至本機、將更新後的快取上傳至雲端硬碟 NSF-tracker 資料夾）。
防呆防錯原因：
1. 缺少憑證或雲端連線失敗時採取降級處理（改用本機暫存），不阻斷主程式運行。
2. 使用 BytesIO 緩衝區串流傳輸，避免本機暫存檔殘留或鎖定衝突。
"""

MODULE_VERSION = "20261109_2235"

import io
import json
import os
import streamlit as st
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

SCOPES = ["https://www.googleapis.com/auth/drive"]

def get_drive_service():
    """取得 Google Drive API 服務實例"""
    if "gcp_service_account" not in st.secrets:
        return None, None
    try:
        service_account_info = dict(st.secrets["gcp_service_account"])
        folder_id = st.secrets.get("drive", {}).get("folder_id", None)
        creds = service_account.Credentials.from_service_account_info(
            service_account_info, scopes=SCOPES
        )
        service = build("drive", "v3", credentials=creds)
        return service, folder_id
    except Exception as e:
        print(f"[cloud_sync] 初始化 Drive 服務失敗: {e}")
        return None, None

def download_file_from_drive(filename: str, local_path: str) -> bool:
    """從雲端資料夾下載指定檔案至本機"""
    service, folder_id = get_drive_service()
    if not service or not folder_id:
        return False
    try:
        query = f"name = '{filename}' and '{folder_id}' in parents and trashed = false"
        results = service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
        files = results.get("files", [])
        if not files:
            return False
        
        file_id = files[0]["id"]
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        
        with open(local_path, "wb") as f:
            f.write(fh.getvalue())
        return True
    except Exception as e:
        print(f"[cloud_sync] 下載檔案失敗 ({filename}): {e}")
        return False

def upload_file_to_drive(local_path: str, filename: str) -> bool:
    """將本機檔案上傳／更新至雲端資料夾"""
    service, folder_id = get_drive_service()
    if not service or not folder_id or not os.path.exists(local_path):
        return False
    try:
        query = f"name = '{filename}' and '{folder_id}' in parents and trashed = false"
        results = service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
        files = results.get("files", [])

        with open(local_path, "rb") as f:
            file_bytes = io.BytesIO(f.read())
        media = MediaIoBaseUpload(file_bytes, mimetype="application/octet-stream", resumable=True)

        if files:
            file_id = files[0]["id"]
            service.files().update(fileId=file_id, media_body=media).execute()
        else:
            file_metadata = {"name": filename, "parents": [folder_id]}
            service.files().create(body=file_metadata, media_body=media, fields="id").execute()
        return True
    except Exception as e:
        print(f"[cloud_sync] 上傳檔案失敗 ({filename}): {e}")
        return False
