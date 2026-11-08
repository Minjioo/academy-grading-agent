"""파일 입력 공통 처리: 경로(str/Path)와 file-like 객체(Streamlit UploadedFile, BytesIO)를 똑같이 다룬다."""
from __future__ import annotations

from pathlib import Path
from typing import BinaryIO, Union

FileInput = Union[str, Path, BinaryIO]


def read_bytes(file: FileInput) -> bytes:
    """전체 바이트를 읽는다. file-like 객체는 처음부터 읽고 위치를 0으로 되돌린다."""
    if isinstance(file, (str, Path)):
        return Path(file).read_bytes()
    if hasattr(file, "seek"):
        file.seek(0)
    data = file.read()
    if hasattr(file, "seek"):
        file.seek(0)
    return data


def file_name(file: FileInput) -> str:
    """경로 또는 UploadedFile.name에서 파일 이름을 얻는다 (없으면 빈 문자열)."""
    if isinstance(file, (str, Path)):
        return Path(file).name
    return getattr(file, "name", "") or ""
