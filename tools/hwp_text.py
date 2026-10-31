# -*- coding: utf-8 -*-
"""한글(HWP 5) 파일에서 문단 텍스트만 꺼낸다 — 표준 라이브러리만 쓴다.

법무부 통계월보는 책자가 hwp 로만 나온다. 원본은 읽기만 하고 고치지 않는다.
표는 칸마다 한 문단으로 나오므로, 표를 읽는 쪽에서 줄을 묶어 행을 만든다.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

END = 0xFFFFFFFA                                   # 이 값 이상이면 체인 끝


def _ole_streams(b: bytes) -> dict[str, bytes]:
    """HWP 5 는 OLE(복합 문서) 파일이다. 스트림 이름 → 내용."""
    ssz = 1 << struct.unpack_from("<H", b, 30)[0]
    mssz = 1 << struct.unpack_from("<H", b, 32)[0]
    nfat, dir0, _, minicut, minifat0, nminifat, dif0, _ = struct.unpack_from("<8I", b, 44)

    def sec(i):
        return b[512 + i * ssz: 512 + (i + 1) * ssz]

    difat = list(struct.unpack_from("<109I", b, 76))
    d = dif0
    while d < END:
        v = struct.unpack_from(f"<{ssz // 4}I", sec(d))
        difat += v[:-1]
        d = v[-1]
    fat = []
    for f in difat[:nfat]:
        fat += struct.unpack_from(f"<{ssz // 4}I", sec(f))

    def read(st):
        out = []
        while st < END:
            out.append(sec(st))
            st = fat[st]
        return b"".join(out)

    dirs = read(dir0)
    ents = []
    for i in range(len(dirs) // 128):
        e = dirs[i * 128:(i + 1) * 128]
        nl = struct.unpack_from("<H", e, 64)[0]
        start, size = struct.unpack_from("<IQ", e, 116)
        ents.append((e[:max(nl - 2, 0)].decode("utf-16le"), e[66], start, size & 0xFFFFFFFF))

    ministream = read(ents[0][2])
    minifat = []
    if nminifat:
        mf = read(minifat0)
        minifat = struct.unpack_from(f"<{len(mf) // 4}I", mf)

    def read_mini(st, size):
        out = []
        while st < END:
            out.append(ministream[st * mssz:(st + 1) * mssz])
            st = minifat[st]
        return b"".join(out)[:size]

    return {name: read_mini(st, size) if size < minicut else read(st)[:size]
            for name, typ, st, size in ents[1:] if typ == 2}


# 글자 자리에 끼어 있는 조판 부호. 이 부호들은 부호 하나가 8글자(16바이트)를 차지한다
_WIDE = {1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23}
PARA_TEXT = 67


def _paragraphs(data: bytes):
    i = 0
    while i + 4 <= len(data):
        h = struct.unpack_from("<I", data, i)[0]
        i += 4
        tag, size = h & 0x3FF, h >> 20
        if size == 0xFFF:
            size = struct.unpack_from("<I", data, i)[0]
            i += 4
        if tag == PARA_TEXT:
            raw, out, j = data[i:i + size], [], 0
            while j < len(raw):
                c = struct.unpack_from("<H", raw, j)[0]
                if c < 32:
                    if c == 9:
                        out.append("\t")
                    j += 16 if c in _WIDE else 2
                    continue
                out.append(chr(c))
                j += 2
            yield "".join(out)
        i += size


def hwp_paragraphs(path: Path) -> list[str]:
    """본문 문단을 순서대로 돌려준다 (표의 칸도 한 칸이 한 문단)."""
    st = _ole_streams(Path(path).read_bytes())
    compressed = st["FileHeader"][36] & 1
    out = []
    for k in sorted((k for k in st if k.startswith("Section")), key=lambda k: int(k[7:])):
        data = zlib.decompress(st[k], -15) if compressed else st[k]
        out += _paragraphs(data)
    return out
