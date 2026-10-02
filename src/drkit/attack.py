"""The ransomware's attempts on the off-site tier with the stolen backup key, and what survived them."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from functools import partial

from drkit.offsite import Offsite, Refused, Version

RANSOM = b"Your backups are encrypted. Pay to recover them.\n"


@dataclass(frozen=True)
class Attempt:
    action: str
    key: str
    version_id: str
    refused: bool
    detail: str


def _try(action: str, v: Version, call: Callable[[], object]) -> Attempt:
    try:
        call()
    except Refused as exc:
        return Attempt(action, v.key, v.version_id, True, str(exc))
    return Attempt(action, v.key, v.version_id, False, "accepted")


def attack(offsite: Offsite, now: datetime) -> list[Attempt]:
    originals = [v for v in offsite.versions("") if not v.is_delete_marker]
    attempts: list[Attempt] = []
    for v in originals:
        attempts.append(_try("shorten-retention", v, partial(offsite.shorten_retention, v.key, v.version_id, now)))
        attempts.append(_try("delete-version", v, partial(offsite.delete_version, v.key, v.version_id)))
    for key in sorted({v.key for v in originals}):
        first = next(v for v in originals if v.key == key)
        attempts.append(_try("overwrite", first, partial(offsite.put, key, RANSOM, None)))
        attempts.append(_try("delete", first, partial(offsite.delete, key)))
    return attempts


def survival(before: Sequence[Version], after: Sequence[Version]) -> list[Version]:
    present = {(v.key, v.version_id) for v in after if not v.is_delete_marker}
    return [v for v in before if not v.is_delete_marker and (v.key, v.version_id) not in present]
