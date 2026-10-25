"""Generate disk-cached WebP backgrounds without changing the original image."""
import hashlib
import os
import tempfile
import threading
from pathlib import Path

from PIL import Image, ImageOps


class MediaCache:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def image(self, source, preview=False):
        source = Path(source)
        stat = source.stat()
        key = hashlib.sha256(f'{source}:{stat.st_size}:{stat.st_mtime_ns}:webp-v3:{preview}'.encode()).hexdigest()
        target = self.root / (key + '.webp')
        original_marker = self.root / (key + '.original')
        if original_marker.is_file():
            return source
        if target.is_file():
            return target
        with self.lock:
            if original_marker.is_file():
                return source
            if target.is_file():
                return target
            with Image.open(source) as original:
                image = ImageOps.exif_transpose(original).convert('RGB')
                if preview:
                    image.thumbnail((640, 480))
                fd, temporary = tempfile.mkstemp(dir=self.root, suffix='.webp')
                try:
                    with os.fdopen(fd, 'wb') as stream:
                        image.save(stream, format='WEBP', quality=60 if preview else 75, method=4)
                    if not preview and Path(temporary).stat().st_size >= stat.st_size:
                        original_marker.touch(mode=0o600)
                        return source
                    os.replace(temporary, target)
                finally:
                    Path(temporary).unlink(missing_ok=True)
            return target
