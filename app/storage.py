import logging
import os

from flask import current_app

logger = logging.getLogger(__name__)


class LocalStorage:
    """Stores files on local disk. Same interface an S3/R2 class will have in Phase 14."""

    def __init__(self, root, url_prefix):
        self.root = os.path.abspath(root)
        self.url_prefix = url_prefix.rstrip("/")

    def _path(self, key):
        path = os.path.abspath(os.path.join(self.root, key))
        if os.path.commonpath([self.root, path]) != self.root:
            raise ValueError("Invalid storage key.")
        return path

    def save(self, key, data):
        path = self._path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)
        return f"{self.url_prefix}/{key}"

    def delete_url(self, url):
        """Best-effort delete; a leftover file must never break a request."""
        prefix = self.url_prefix + "/"
        if not url or not url.startswith(prefix):
            return
        try:
            os.remove(self._path(url[len(prefix):]))
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            logger.warning("Could not delete stored file for %s", url, exc_info=True)


def get_storage():
    return LocalStorage(current_app.config["UPLOAD_DIR"], current_app.config["MEDIA_URL"])