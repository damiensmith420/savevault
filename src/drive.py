"""
Google Drive API wrapper for SaveVault.

All file operations are scoped to files created by this app
(drive.file scope).  The folder hierarchy used is:

    My Drive/
    └── Save Games/
        ├── <Game Name>/
        │   ├── save1.dat
        │   └── save2.dat
        └── <Another Game>/
            └── ...
"""

from __future__ import annotations

import io
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from googleapiclient.discovery import build, Resource
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google.oauth2.credentials import Credentials

ROOT_FOLDER_NAME = "Save Games"
MIME_FOLDER = "application/vnd.google-apps.folder"

# Retry parameters for rate-limit (429) responses
_MAX_RETRIES = 5
_RETRY_BASE_DELAY = 2.0  # seconds


@dataclass
class DriveFile:
    """Metadata for a single file in Google Drive."""

    file_id: str
    name: str
    modified_time: str   # RFC 3339 string, e.g. "2024-01-01T12:00:00.000Z"
    size: int            # bytes (0 for folders)
    mime_type: str


def _build_service(credentials: Credentials) -> Resource:
    """Build and return an authenticated Drive v3 service."""
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _retry(func, *args, **kwargs):
    """
    Call func(*args, **kwargs), retrying on 429/500/503 with exponential back-off.

    Raises the final HttpError if all retries are exhausted.
    """
    delay = _RETRY_BASE_DELAY
    for attempt in range(_MAX_RETRIES):
        try:
            return func(*args, **kwargs)
        except HttpError as exc:
            if exc.resp.status in (429, 500, 503) and attempt < _MAX_RETRIES - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise


class DriveClient:
    """
    High-level wrapper around the Google Drive v3 API.

    All methods raise ``googleapiclient.errors.HttpError`` on API failures
    after exhausting retries.
    """

    def __init__(self, credentials: Credentials) -> None:
        """
        Initialise the client with OAuth credentials.

        Args:
            credentials: A valid google.oauth2.credentials.Credentials object.
        """
        self._service: Resource = _build_service(credentials)
        self._root_folder_id: Optional[str] = None

    # ------------------------------------------------------------------ #
    # Folder management                                                    #
    # ------------------------------------------------------------------ #

    def get_or_create_root_folder(self) -> str:
        """
        Find or create the top-level ``Save Games`` folder in Drive root.

        Returns:
            The Google Drive folder ID.
        """
        if self._root_folder_id:
            return self._root_folder_id

        folder_id = self._find_folder(ROOT_FOLDER_NAME, parent_id=None)
        if folder_id is None:
            folder_id = self._create_folder(ROOT_FOLDER_NAME, parent_id=None)

        self._root_folder_id = folder_id
        return folder_id

    def get_or_create_game_folder(self, game_name: str) -> str:
        """
        Find or create a subfolder under ``Save Games`` for the given game.

        Args:
            game_name: Human-readable game name used as the folder name.

        Returns:
            The Google Drive folder ID for that game.
        """
        root_id = self.get_or_create_root_folder()
        folder_id = self._find_folder(game_name, parent_id=root_id)
        if folder_id is None:
            folder_id = self._create_folder(game_name, parent_id=root_id)
        return folder_id

    def get_or_create_subfolder(self, name: str, parent_id: str) -> str:
        """
        Find or create a named subfolder inside any Drive folder.

        Used to mirror local subdirectory structure inside a game's
        Drive folder during recursive sync.

        Args:
            name:      The subfolder name to find or create.
            parent_id: Drive folder ID of the parent.

        Returns:
            The Drive folder ID of the found or created subfolder.
        """
        folder_id = self._find_folder(name, parent_id=parent_id)
        if folder_id is None:
            folder_id = self._create_folder(name, parent_id=parent_id)
        return folder_id

    def list_game_folders(self) -> list[DriveFile]:
        """
        List all immediate subfolders of the ``Save Games`` root folder.

        Returns:
            A list of DriveFile objects (mime_type will be MIME_FOLDER).
            Returns an empty list if the root folder doesn't exist yet.
        """
        root_id = self._find_folder(ROOT_FOLDER_NAME, parent_id=None)
        if root_id is None:
            return []
        return self.list_files_in_folder(root_id, folders_only=True)

    # ------------------------------------------------------------------ #
    # File operations                                                      #
    # ------------------------------------------------------------------ #

    def list_files_in_folder(
        self, folder_id: str, folders_only: bool = False
    ) -> list[DriveFile]:
        """
        List all non-trashed files (or only folders) inside a Drive folder.

        Args:
            folder_id:    The Drive folder ID to list.
            folders_only: If True, return only folder items.

        Returns:
            A list of DriveFile dataclass instances.
        """
        mime_filter = f" and mimeType = '{MIME_FOLDER}'" if folders_only else ""
        query = f"'{folder_id}' in parents and trashed = false{mime_filter}"
        fields = "nextPageToken, files(id, name, modifiedTime, size, mimeType)"

        results: list[DriveFile] = []
        page_token: Optional[str] = None

        while True:
            params: dict = {
                "q": query,
                "fields": fields,
                "pageSize": 1000,
            }
            if page_token:
                params["pageToken"] = page_token

            response = _retry(
                self._service.files().list(**params).execute
            )
            for item in response.get("files", []):
                results.append(
                    DriveFile(
                        file_id=item["id"],
                        name=item["name"],
                        modified_time=item.get("modifiedTime", ""),
                        size=int(item.get("size", 0)),
                        mime_type=item.get("mimeType", ""),
                    )
                )
            page_token = response.get("nextPageToken")
            if not page_token:
                break

        return results

    def upload_file(
        self,
        local_path: Path,
        folder_id: str,
        existing_file_id: Optional[str] = None,
        progress_callback=None,
    ) -> str:
        """
        Upload a local file to a Drive folder (create or update).

        Args:
            local_path:       Path to the local file.
            folder_id:        Drive folder ID to upload into.
            existing_file_id: If provided, the existing Drive file is updated
                              (PATCH); otherwise a new file is created (POST).
            progress_callback: Optional callable(bytes_sent, total_bytes) for
                               progress reporting from the calling thread.

        Returns:
            The Drive file ID of the created/updated file.
        """
        mime_type = "application/octet-stream"
        media = MediaFileUpload(
            str(local_path),
            mimetype=mime_type,
            resumable=True,
            chunksize=1024 * 1024,  # 1 MiB
        )

        if existing_file_id:
            request = self._service.files().update(
                fileId=existing_file_id,
                media_body=media,
                fields="id",
            )
        else:
            metadata = {
                "name": local_path.name,
                "parents": [folder_id],
            }
            request = self._service.files().create(
                body=metadata,
                media_body=media,
                fields="id",
            )

        response = None
        while response is None:
            status, response = _retry(request.next_chunk)
            if status and progress_callback:
                progress_callback(status.resumable_progress, status.total_size)

        return response["id"]

    def download_file(
        self,
        file_id: str,
        local_path: Path,
        progress_callback=None,
    ) -> None:
        """
        Download a Drive file to a local path.

        Creates parent directories as needed. The download is streamed in
        1 MiB chunks to keep memory use low for large saves.

        Args:
            file_id:          Drive file ID to download.
            local_path:       Destination path on the local filesystem.
            progress_callback: Optional callable(bytes_recv, total_bytes).
        """
        local_path.parent.mkdir(parents=True, exist_ok=True)

        request = self._service.files().get_media(fileId=file_id)
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request, chunksize=1024 * 1024)

        done = False
        while not done:
            status, done = _retry(downloader.next_chunk)
            if status and progress_callback:
                progress_callback(status.resumable_progress, status.total_size)

        local_path.write_bytes(buf.getvalue())

    def delete_file(self, file_id: str) -> None:
        """
        Move a Drive file to the trash (soft-delete).

        Args:
            file_id: The Drive file ID to trash.
        """
        _retry(
            self._service.files()
            .update(fileId=file_id, body={"trashed": True})
            .execute
        )

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _find_folder(self, name: str, parent_id: Optional[str]) -> Optional[str]:
        """Return the ID of a folder with the given name, or None if absent."""
        if parent_id:
            query = (
                f"name = '{name}' and mimeType = '{MIME_FOLDER}' "
                f"and '{parent_id}' in parents and trashed = false"
            )
        else:
            query = (
                f"name = '{name}' and mimeType = '{MIME_FOLDER}' "
                f"and trashed = false"
            )

        response = _retry(
            self._service.files()
            .list(q=query, fields="files(id)", pageSize=1)
            .execute
        )
        files = response.get("files", [])
        return files[0]["id"] if files else None

    def _create_folder(self, name: str, parent_id: Optional[str]) -> str:
        """Create a new folder and return its ID."""
        metadata: dict = {"name": name, "mimeType": MIME_FOLDER}
        if parent_id:
            metadata["parents"] = [parent_id]

        response = _retry(
            self._service.files()
            .create(body=metadata, fields="id")
            .execute
        )
        return response["id"]
