"""Managed temporary storage for uploaded image/media files."""

from __future__ import annotations

import base64
import binascii
import re
import shutil
import threading
import uuid
from pathlib import Path

# Attachment keys that Wan2GP recognises as file-path fields.
# Mirrors wgp.ATTACHMENT_KEYS so we can detect them without importing wgp.
ATTACHMENT_KEYS = frozenset({
    "image_start", "image_end", "image_refs", "image_guide", "image_mask",
    "video_guide", "video_mask", "video_source",
    "audio_guide", "audio_guide2", "audio_source", "custom_guide",
})

# data-URI pattern:  data:image/png;base64,iVBOR...
_DATA_URI_RE = re.compile(
    r"^data:(?P<mime>[a-zA-Z0-9_/+.-]+);base64,(?P<data>.+)$",
    re.DOTALL,
)

# mime -> preferred extension (common media types)
_MIME_EXT: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "audio/wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
}


class UploadManager:
    """Save, track, and clean up uploaded media files.

    Files are stored under ``<base_dir>/<group_id>/`` so that an entire
    group's uploads can be removed in one ``shutil.rmtree`` call.

    A *job* may reference files from one or more upload groups (from
    ``POST /uploads``) as well as inline base64 data-URIs (decoded under
    the job's own id).  ``register_groups_for_job`` records these
    associations so that ``cleanup_job`` removes everything.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        if base_dir is None:
            base_dir = Path(__file__).resolve().parent / "_uploads"
        self._base_dir = base_dir
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # job_id -> set of group_ids whose directories should also be cleaned
        self._job_groups: dict[str, set[str]] = {}

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    # --- public: file operations ---

    def save_file(self, group_id: str, filename: str, data: bytes) -> str:
        """Persist *data* to disk and return the absolute path (str).

        If *filename* already exists in the group directory a unique
        suffix is appended to prevent silent overwrites.
        """
        job_dir = self._base_dir / group_id
        job_dir.mkdir(parents=True, exist_ok=True)
        safe_name = self._safe_filename(filename)
        dest = job_dir / safe_name
        # Avoid overwriting an existing file with the same name
        if dest.exists():
            stem = dest.stem
            ext = dest.suffix
            dest = job_dir / f"{stem}_{uuid.uuid4().hex[:6]}{ext}"
        dest.write_bytes(data)
        return str(dest)

    def cleanup_job(self, job_id: str) -> None:
        """Remove uploaded files for *job_id* and all associated upload groups."""
        with self._lock:
            group_ids = self._job_groups.pop(job_id, set())
        # Always try to remove the job_id directory (data-URI decoded files)
        ids_to_remove = {job_id} | group_ids
        for gid in ids_to_remove:
            d = self._base_dir / gid
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)

    def register_groups_for_job(self, job_id: str, group_ids: set[str]) -> None:
        """Associate upload *group_ids* with a *job_id* for later cleanup."""
        if not group_ids:
            return
        with self._lock:
            self._job_groups.setdefault(job_id, set()).update(group_ids)

    # --- public: base64 data-URI resolution ---

    def resolve_data_uris(self, settings: dict, job_id: str) -> dict:
        """Walk *settings* and decode any base64 data-URI values for
        recognised attachment keys, replacing them with on-disk paths.

        Non-attachment keys and non-data-URI values are left untouched.

        Also scans path values for upload-group directory references so
        that ``register_groups_for_job`` can be called automatically.

        Raises ``ValueError`` if a data-URI contains invalid base64.
        """
        referenced_groups: set[str] = set()
        for key in ATTACHMENT_KEYS:
            if key not in settings:
                continue
            value = settings[key]
            if isinstance(value, list):
                settings[key] = [
                    self._maybe_decode(item, key, job_id) for item in value
                ]
                for v in settings[key]:
                    self._collect_group(v, referenced_groups)
            else:
                settings[key] = self._maybe_decode(value, key, job_id)
                self._collect_group(settings[key], referenced_groups)
        # Auto-register any upload groups referenced by file paths
        self.register_groups_for_job(job_id, referenced_groups)
        return settings

    # --- internal helpers ---

    def _collect_group(self, value, groups: set[str]) -> None:
        """If *value* is a path under our base_dir, record its group id."""
        if not isinstance(value, str):
            return
        try:
            p = Path(value)
            if p.is_relative_to(self._base_dir) and p.parent != self._base_dir:
                groups.add(p.parent.name)
        except (ValueError, TypeError):
            pass

    def _maybe_decode(self, value, key: str, job_id: str) -> str:
        """If *value* is a data-URI string, decode & save; else pass through."""
        if not isinstance(value, str):
            return value
        m = _DATA_URI_RE.match(value)
        if m is None:
            return value  # plain path or other string
        mime = m.group("mime")
        try:
            raw = base64.b64decode(m.group("data"), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(f"Invalid base64 in data-URI for '{key}': {exc}") from exc
        ext = _MIME_EXT.get(mime, ".bin")
        filename = f"{key}_{uuid.uuid4().hex[:8]}{ext}"
        return self.save_file(job_id, filename, raw)

    @staticmethod
    def _safe_filename(name: str) -> str:
        """Sanitise filename — keep extension, replace unsafe chars."""
        name = Path(name).name
        if not name or name.startswith("."):
            name = f"_{name}" if name else f"{uuid.uuid4().hex[:12]}.bin"
        return name
