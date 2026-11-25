"""Offline PII & Secret Redaction Shield (credit cards, API keys, JWTs, IBAN, SSN, TCKN, OTP)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

from PIL import Image, ImageDraw

PII_MODE_REDACT_AND_BLUR = "redact_and_blur"
PII_MODE_REDACT_TEXT = "redact_text"
PII_MODE_SKIP = "skip_capture"
PII_MODE_OFF = "off"

VALID_PII_MODES = (
    PII_MODE_REDACT_AND_BLUR,
    PII_MODE_REDACT_TEXT,
    PII_MODE_SKIP,
    PII_MODE_OFF,
)


@dataclass(slots=True)
class PIIDetection:
    """Single detected sensitive credential or PII match."""

    category: str
    matched_text: str
    start: int
    end: int
    replacement: str


def luhn_valid(digits: str) -> bool:
    """Validates a payment card number with the Luhn checksum algorithm."""
    if not digits.isdigit() or not (13 <= len(digits) <= 19):
        return False
    if len(set(digits)) == 1:
        return False
    total = 0
    reverse = digits[::-1]
    for idx, ch in enumerate(reverse):
        val = int(ch)
        if idx % 2 == 1:
            val *= 2
            if val > 9:
                val -= 9
        total += val
    return total % 10 == 0


def tckn_valid(digits: str) -> bool:
    """Validates a Turkish National ID (TCKN) using its official 10th/11th digit checksum."""
    if not digits.isdigit() or len(digits) != 11 or digits[0] == "0":
        return False
    nums = [int(c) for c in digits]
    d10 = ((sum(nums[0:9:2]) * 7) - sum(nums[1:8:2])) % 10
    if d10 != nums[9]:
        return False
    d11 = sum(nums[:10]) % 10
    return d11 == nums[10]


def iban_valid(iban: str) -> bool:
    """Validates an IBAN using the ISO 7064 mod-97-10 checksum algorithm."""
    compact = re.sub(r"\s+", "", iban or "").upper()
    if not (15 <= len(compact) <= 34):
        return False
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", compact):
        return False
    rearranged = compact[4:] + compact[:4]
    remainder = 0
    for ch in rearranged:
        if ch.isdigit():
            remainder = (remainder * 10 + (ord(ch) - 48)) % 97
        else:
            val = ord(ch) - 55  # 'A' -> 10 .. 'Z' -> 35
            remainder = (remainder * 100 + val) % 97
    return remainder == 1


def _has_card_bin_prefix(digits: str) -> bool:
    """Validates payment card BIN/IIN prefix & length to exclude timestamps and generic IDs."""
    if not digits:
        return False
    n = len(digits)
    d0 = digits[0]
    if d0 == "4":
        return n in (13, 16, 19)
    if d0 == "5":
        return 16 <= n <= 19
    if d0 == "3":
        return n in (14, 15, 16) and digits[:2] in ("30", "34", "35", "36", "37", "38", "39")
    if d0 == "6":
        return 16 <= n <= 19 and digits[:2] in ("60", "62", "64", "65")
    if digits.startswith("9792"):
        return n == 16
    if n == 16 and digits[:4].isdigit() and 2221 <= int(digits[:4]) <= 2720:
        return True
    return False


_API_KEY_PATTERNS: tuple[re.Pattern[str], ...] = (
    # OpenAI / Anthropic secret keys
    re.compile(r"\b(?:sk-(?:proj-|ant-|live-|test-)?[A-Za-z0-9_-]{20,})\b"),
    # Stripe secret & restricted underscore keys
    re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b"),
    # GitHub personal access tokens
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b"),
    # GitLab / HuggingFace / npm / SendGrid tokens
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bhf_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bnpm_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\b"),
    # AWS access key IDs
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    # Google API keys
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    # Slack tokens
    re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b"),
    # JWTs
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
)

_PEM_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]{0,32}PRIVATE KEY-----(?:[\s\S]{0,8192}?-----END [A-Z0-9 ]{0,32}PRIVATE KEY-----)?"
)
_DB_URI_RE = re.compile(
    r"\b(?:postgres|postgresql|mysql|mongodb(?:\+srv)?|redis|amqp)://[^:\s/]+:[^@\s]+@[^\s'\"<>]*",
    re.IGNORECASE,
)
_BEARER_TOKEN_RE = re.compile(
    r"\bBearer\s+([A-Za-z0-9._~+/=-]{16,})(?=\s|$|[\"',;)\]}])",
    re.IGNORECASE,
)

_CARD_CANDIDATE_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,4})?\b")
_SSN_RE = re.compile(r"\b(?!000|666|9\d\d)(\d{3})-(?!00)(\d{2})-(?!0000)(\d{4})\b")
_TCKN_CTX_RE = re.compile(
    r"\b(?:t\.?\s*c\.?\s*(?:k[iİıI]ml[iİıI]k)?(?:\s*(?:no|numaras[ıiİI]|num))?|"
    r"tckn|"
    r"k[iİıI]ml[iİıI]k(?:\s*(?:no|numaras[ıiİI]|num))?|"
    r"id\s*(?:no|number))[\s.:#=-]{0,12}(\d{11})\b",
    re.IGNORECASE,
)
_OTP_FWD_RE = re.compile(
    r"\b(?:otp|2fa|mfa|verification(?:\s+code)?|security\s+code|login\s+code|"
    r"auth(?:entication)?\s+code|one[- ]time\s+(?:code|password|passcode)|"
    r"do[ğg]rulama(?:\s+kodu)?|onay\s+kodu|"
    r"tek\s+kullan[ıiİI]ml[ıiİI]k(?:\s+(?:[şs][iİıI]fre|kod(?:u)?))?|passcode)"
    r"(?:\s+is)?[\s:#=-]{0,16}(?<!\d)(\d{3}[ -]?\d{3})(?!\d)",
    re.IGNORECASE,
)
_OTP_REV_RE = re.compile(
    r"(?<!\d)(\d{3}[ -]?\d{3})(?!\d)[\s,-]{1,6}(?:is\s+(?:your\s+)?(?:one[- ]time\s+)?)?"
    r"(?:otp|2fa|mfa|verification(?:\s+code)?|security\s+code|login\s+code|"
    r"auth(?:entication)?\s+code|one[- ]time\s+(?:code|password|passcode)|passcode|"
    r"do[ğg]rulama\s+kod\w*|onay\s+kod\w*|tek\s+kullan[ıiİI]ml[ıiİI]k)\b",
    re.IGNORECASE,
)


class PIIRedactor:
    """100% offline regex + checksum PII & secret redaction engine."""

    def __init__(self, mode: str = PII_MODE_REDACT_AND_BLUR) -> None:
        self.mode = mode if mode in VALID_PII_MODES else PII_MODE_REDACT_AND_BLUR

    def set_mode(self, mode: str) -> None:
        if mode in VALID_PII_MODES:
            self.mode = mode

    @property
    def is_enabled(self) -> bool:
        return self.mode != PII_MODE_OFF

    def detect(self, text: str) -> list[PIIDetection]:
        """Scans text and returns non-overlapping sensitive detections sorted by position."""
        if not text:
            return []

        raw: list[PIIDetection] = []

        # 1. API Keys, JWTs, PEM Private Keys, DB URIs, Bearer tokens
        for pat in _API_KEY_PATTERNS:
            for m in pat.finditer(text):
                raw.append(
                    PIIDetection(
                        category="api_key",
                        matched_text=m.group(0),
                        start=m.start(),
                        end=m.end(),
                        replacement="[REDACTED:API_KEY]",
                    )
                )

        for m in _PEM_PRIVATE_KEY_RE.finditer(text):
            raw.append(
                PIIDetection(
                    category="private_key",
                    matched_text=m.group(0),
                    start=m.start(),
                    end=m.end(),
                    replacement="[REDACTED:PRIVATE_KEY]",
                )
            )

        for m in _DB_URI_RE.finditer(text):
            raw.append(
                PIIDetection(
                    category="db_uri",
                    matched_text=m.group(0),
                    start=m.start(),
                    end=m.end(),
                    replacement="[REDACTED:DB_URI]",
                )
            )

        for m in _BEARER_TOKEN_RE.finditer(text):
            raw.append(
                PIIDetection(
                    category="api_key",
                    matched_text=m.group(1),
                    start=m.start(1),
                    end=m.end(1),
                    replacement="[REDACTED:API_KEY]",
                )
            )

        # 2. IBAN (ISO 7064 mod-97 validated, 15..34 chars without spaces)
        for m in _IBAN_RE.finditer(text):
            if iban_valid(m.group(0)):
                raw.append(
                    PIIDetection(
                        category="iban",
                        matched_text=m.group(0),
                        start=m.start(),
                        end=m.end(),
                        replacement="[REDACTED:IBAN]",
                    )
                )

        # 3. Credit Cards (Luhn + BIN prefix validated; rejects Unix ms timestamps)
        for m in _CARD_CANDIDATE_RE.finditer(text):
            matched = m.group(0).strip()
            digits = re.sub(r"[ -]", "", matched)
            if luhn_valid(digits) and _has_card_bin_prefix(digits):
                start_offset = m.start() + m.group(0).find(matched)
                raw.append(
                    PIIDetection(
                        category="card",
                        matched_text=matched,
                        start=start_offset,
                        end=start_offset + len(matched),
                        replacement="[REDACTED:CARD]",
                    )
                )

        # 4. US SSN
        for m in _SSN_RE.finditer(text):
            raw.append(
                PIIDetection(
                    category="ssn",
                    matched_text=m.group(0),
                    start=m.start(),
                    end=m.end(),
                    replacement="[REDACTED:SSN]",
                )
            )

        # 5. Turkish TCKN (contextual + checksum validated)
        for m in _TCKN_CTX_RE.finditer(text):
            digits = m.group(1)
            if tckn_valid(digits):
                raw.append(
                    PIIDetection(
                        category="tckn",
                        matched_text=digits,
                        start=m.start(1),
                        end=m.end(1),
                        replacement="[REDACTED:TCKN]",
                    )
                )

        # 6. 6-digit OTP / 2FA codes (forward, reverse, and space/hyphen separated)
        for otp_pat in (_OTP_FWD_RE, _OTP_REV_RE):
            for m in otp_pat.finditer(text):
                code = m.group(1)
                raw.append(
                    PIIDetection(
                        category="otp",
                        matched_text=code,
                        start=m.start(1),
                        end=m.end(1),
                        replacement="[REDACTED:OTP]",
                    )
                )

        # Deduplicate overlapping spans (prefer longer/earlier match)
        raw.sort(key=lambda d: (d.start, -(d.end - d.start)))
        deduped: list[PIIDetection] = []
        last_end = -1
        for det in raw:
            if det.start >= last_end:
                deduped.append(det)
                last_end = det.end
        return deduped

    def redact_text(self, text: str) -> tuple[str, list[PIIDetection]]:
        """Redacts detected secrets/PII from text and returns (sanitized_text, detections)."""
        if not self.is_enabled or not text:
            return text, []
        detections = self.detect(text)
        if not detections:
            return text, []

        parts: list[str] = []
        cursor = 0
        for det in detections:
            parts.append(text[cursor : det.start])
            parts.append(det.replacement)
            cursor = det.end
        parts.append(text[cursor:])
        return "".join(parts), detections

    def redact_ocr_boxes(self, boxes: Sequence) -> tuple[list, list, list[PIIDetection]]:
        """
        Redacts OCRBox items containing PII, mapping character offsets across the
        newline-joined box sequence so secrets split across adjacent OCR boxes
        (e.g. 'Verification code:' + '849201') are redacted in JSON and blurred on WebP.
        Returns (sanitized_boxes, blur_boxes, all_detections).
        """
        if not self.is_enabled or not boxes:
            return list(boxes), [], []

        spans: list[tuple[int, int]] = []
        joined_parts: list[str] = []
        cursor = 0
        for idx, box in enumerate(boxes):
            if idx > 0:
                joined_parts.append("\n")
                cursor += 1
            txt = box.text or ""
            start = cursor
            end = start + len(txt)
            spans.append((start, end))
            joined_parts.append(txt)
            cursor = end

        joined = "".join(joined_parts)
        detections = self.detect(joined)
        if not detections:
            return list(boxes), [], []

        sanitized = []
        blur_boxes = []
        for box, (b_start, b_end) in zip(boxes, spans):
            overlaps = [d for d in detections if d.start < b_end and d.end > b_start]
            if not overlaps:
                sanitized.append(box)
                continue

            blur_boxes.append(box)
            txt = box.text or ""
            local_parts: list[str] = []
            local_cursor = 0
            for det in overlaps:
                l_start = max(det.start, b_start) - b_start
                l_end = min(det.end, b_end) - b_start
                if l_start < local_cursor:
                    l_start = local_cursor
                if l_end <= l_start:
                    continue
                local_parts.append(txt[local_cursor:l_start])
                local_parts.append(det.replacement)
                local_cursor = l_end
            local_parts.append(txt[local_cursor:])
            clean_txt = "".join(local_parts)

            cls = type(box)
            sanitized.append(
                cls(
                    text=clean_txt,
                    x=box.x,
                    y=box.y,
                    w=box.w,
                    h=box.h,
                    score=box.score,
                )
            )

        return sanitized, blur_boxes, detections

    @staticmethod
    def blur_image_regions(image: Image.Image, boxes: Iterable) -> Image.Image:
        """Applies irreversible opaque solid redaction fill (alpha 255) over sensitive bounding boxes."""
        box_list = list(boxes)
        if not box_list:
            return image

        out = image.convert("RGB").copy()
        w, h = out.size
        draw = ImageDraw.Draw(out, "RGBA")

        for box in box_list:
            pad_x = max(4, int(w * 0.004))
            pad_y = max(3, int(h * 0.004))
            x0 = max(0, int(box.x * w) - pad_x)
            y0 = max(0, int(box.y * h) - pad_y)
            x1 = min(w, int((box.x + box.w) * w) + pad_x)
            y1 = min(h, int((box.y + box.h) * h) + pad_y)
            if x1 <= x0 or y1 <= y0:
                continue
            # Solid opaque fill destroys 100% of underlying pixels (immune to blur deconvolution)
            draw.rectangle([x0, y0, x1, y1], fill=(17, 17, 20, 255))
            draw.rounded_rectangle(
                [x0, y0, x1, y1],
                radius=4,
                fill=(17, 17, 20, 255),
                outline=(16, 185, 129, 255),
                width=2,
            )

        return out
