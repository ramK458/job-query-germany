"""Google Drive API client for the AFA job scraper Cloud Function."""

import json
import logging
import os
from io import BytesIO

import google.auth
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class DriveClient:
    """Thin wrapper around Google Drive API v3."""

    def __init__(self, credentials: Credentials | None = None):
        if credentials is None:
            credentials = self._load_credentials()
        self.service = build("drive", "v3", credentials=credentials)

    def file_exists(self, folder_id: str, filename: str) -> str | None:
        """Return file_id if *filename* exists in *folder_id*, else None."""
        query = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
        results = self.service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
        files = results.get("files", [])
        if files:
            logger.info("Found '%s' (id=%s)", filename, files[0]["id"])
            return files[0]["id"]
        logger.info("File '%s' not found in folder %s", filename, folder_id)
        return None

    def download_file(self, file_id: str) -> bytes:
        """Download file content as bytes."""
        content = self.service.files().get_media(fileId=file_id).execute()
        logger.info("Downloaded id=%s (%d bytes)", file_id, len(content))
        return content

    def create_file(
        self,
        folder_id: str,
        filename: str,
        content: bytes,
        app_properties: dict[str, str] | None = None,
    ) -> str:
        """Upload a new file to *folder_id* and return its ID."""
        meta = {"name": filename, "parents": [folder_id]}
        if app_properties:
            meta["appProperties"] = app_properties
        media = MediaIoBaseUpload(BytesIO(content), mimetype=MIME, resumable=True)
        fid = self.service.files().create(body=meta, media_body=media, fields="id").execute().get("id")
        logger.info("Created '%s' (id=%s)", filename, fid)
        return fid

    def update_file(
        self,
        file_id: str,
        content: bytes,
        app_properties: dict[str, str] | None = None,
    ) -> None:
        """Overwrite a file and update metadata in the same Drive request."""
        media = MediaIoBaseUpload(BytesIO(content), mimetype=MIME, resumable=True)
        body = {"appProperties": app_properties} if app_properties else None
        self.service.files().update(fileId=file_id, body=body, media_body=media).execute()
        logger.info("Updated id=%s (%d bytes)", file_id, len(content))

    def get_app_property(self, file_id: str, key: str) -> str | None:
        """Return one private application property from a Drive file."""
        meta = self.service.files().get(fileId=file_id, fields="appProperties").execute()
        return (meta.get("appProperties") or {}).get(key)

    def update_app_properties(self, file_id: str, properties: dict[str, str]) -> None:
        """Update private application metadata without changing file content."""
        self.service.files().update(fileId=file_id, body={"appProperties": properties}).execute()
        logger.info("Updated app properties for id=%s", file_id)

    @staticmethod
    def _load_credentials() -> Credentials:
        """Load SA from SERVICE_ACCOUNT_JSON env var, or fall back to ADC."""
        sa_json = os.environ.get("SERVICE_ACCOUNT_JSON")
        if sa_json:
            try:
                return Credentials.from_service_account_info(json.loads(sa_json), scopes=SCOPES)
            except (json.JSONDecodeError, ValueError):
                logger.warning("Invalid SERVICE_ACCOUNT_JSON, falling back to ADC")
        creds, project_id = google.auth.default(scopes=SCOPES)
        logger.info("Using ADC (project=%s)", project_id)
        return creds
