import time
from typing import BinaryIO


class UploadProgressReader:
    def __init__(self, file_obj: BinaryIO, total_size: int):
        self._f = file_obj
        self.total_size = int(total_size) if total_size is not None else 0
        self.bytes_read = 0
        self.start_time = time.monotonic()

    def read(self, size: int = -1):
        data = self._f.read(size)
        if data:
            self.bytes_read += len(data)
        return data

    def seek(self, offset: int, whence: int = 0):
        return self._f.seek(offset, whence)

    def tell(self) -> int:
        return self._f.tell()

    def close(self):
        return self._f.close()

    def __getattr__(self, name):
        return getattr(self._f, name)
