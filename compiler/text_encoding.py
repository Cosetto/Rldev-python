from __future__ import annotations

import codecs

from . import app
from .ketypes import Location, nowhere, error


def set_output_encoding(enc: str | None) -> None:
    app.output_encoding = normalize_encoding(enc or "cp932")


def normalize_encoding(enc: str) -> str:
    enc = enc.strip()
    if not enc:
        return "cp932"
    aliases = {
        "none": "cp932",
        "default": "cp932",
        "shift_jis": "cp932",
        "shift-jis": "cp932",
        "sjis": "cp932",
        "chinese": "cp936",
        "zh": "cp936",
        "cn": "cp936",
        "gb2312": "cp936",
        "gbk": "cp936",
        "western": "cp1252",
        "english": "cp1252",
        "en": "cp1252",
        "korean": "cp949",
        "ko": "cp949",
        "kr": "cp949",
        "ksc": "cp949",
        "ksc5601": "cp949",
        "ksx1001": "cp949",
        "hangul": "cp949",
    }
    enc = aliases.get(enc.lower(), enc)
    try:
        return codecs.lookup(enc).name
    except LookupError:
        error(nowhere, f"unknown output encoding '{enc}'")
        return "cp932"


def metadata_transform_name() -> str:
    name = normalize_encoding(app.output_encoding).lower().replace("_", "-")
    if name in ("gbk", "gb2312", "cp936", "936"):
        return "CHINESE"
    if name in ("cp1252", "windows-1252", "1252"):
        return "WESTERN"
    if name in ("cp949", "949", "ks-c-5601", "ks-x-1001"):
        return "KOREAN"
    return "NONE"


def encode_text(text: str, loc: Location = nowhere, context: str = "text") -> bytes:
    enc = app.output_encoding or "cp932"
    try:
        return text.encode(enc)
    except UnicodeEncodeError as exc:
        if app.force_transform:
            out = bytearray()
            for ch in text:
                try:
                    out.extend(ch.encode(enc))
                except UnicodeEncodeError:
                    out.append(0x20)
            return bytes(out)
        error(loc, f"unable to encode U+{ord(exc.object[exc.start]):04x} in {context} with {enc}")
        return b""


def text_to_byte_string(text: str, loc: Location = nowhere, context: str = "text") -> str:
    return "".join(chr(b) for b in encode_text(text, loc, context))
