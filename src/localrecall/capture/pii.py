"""Offline PII & Secret Redaction Shield (credit cards, API keys, JWTs, IBAN, SSN, TCKN, OTP)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

from PIL import Image, ImageDraw, ImageFilter

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


_API_KEY_PATTERNS: tuple[re.Pattern[str], ...] = (
    # OpenAI / Anthropic / Stripe secret keys
    re.compile(r"\b(?:sk-(?:proj-|live-|test-)?[A-Za-z0-9_-]{20,})\b"),
    # GitHub personal access tokens
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b"),
    # AWS access key IDs
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    # Google API keys
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    # Slack tokens
    re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b"),
    # JWTs
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
)

_CARD_CANDIDATE_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){3,7}(?:[ ]?[A-Z0-9]{1,4})?\b")
_SSN_RE = re.compile(r"\b(?!000|666|9\d\d)(\d{3})-(?!00)(\d{2})-(?!0000)(\d{4})\b")
_TCKN_CTX_RE = re.compile(
    r"(?:tc(?:kn)?|kimlik|t\.c\.|id\s*no)[\s:#=-]{0,8}(\d{11})\b",
    re.IGNORECASE,
)
_OTP_CTX_RE = re.compile(
    r"(?:otp|2fa|mfa|verification(?:\s+code)?|security\s+code|doğrulama(?:\s+kodu)?|onay\s+kodu|tek\s+kullanımlık|passcode)[\s:#=-]{0,12}(\d{6})\b",
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

        # 1. API Keys & JWTs
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

        # 2. IBAN (TR26 / EU IBANs, min 15 chars without spaces)
        for m in _IBAN_RE.finditer(text):
            compact = m.group(0).replace(" ", "")
            if 15 <= len(compact) <= 34:
                raw.append(
                    PIIDetection(
                        category="iban",
                        matched_text=m.group(0),
                        start=m.start(),
                        end=m.end(),
                        replacement="[REDACTED:IBAN]",
                    )
                )

        # 3. Credit Cards (Luhn validated)
        for m in _CARD_CANDIDATE_RE.finditer(text):
            matched = m.group(0).strip()
            digits = re.sub(r"[ -]", "", matched)
            if luhn_valid(digits):
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

        # 6. 6-digit OTP / 2FA codes
        for m in _OTP_CTX_RE.finditer(text):
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
        Redacts OCRBox items containing PII.
        Returns (sanitized_boxes, blur_boxes, all_detections).
        """
        if not self.is_enabled or not boxes:
            return list(boxes), [], []

        sanitized = []
        blur_boxes = []
        all_dets: list[PIIDetection] = []

        for box in boxes:
            clean_txt, dets = self.redact_text(box.text)
            if dets:
                all_dets.extend(dets)
                blur_boxes.append(box)
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
            else:
                sanitized.append(box)

        return sanitized, blur_boxes, all_dets

    @staticmethod
    def blur_image_regions(image: Image.Image, boxes: Iterable) -> Image.Image:
        """Applies heavy blur + dark privacy veil over sensitive bounding boxes on an image."""
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
            crop = out.crop((x0, y0, x1, y1)).filter(ImageFilter.GaussianBlur(radius=16))
            out.paste(crop, (x0, y0))
            draw.rounded_rectangle(
                [x0, y0, x1, y1],
                radius=4,
                fill=(17, 17, 20, 185),
                outline=(16, 185, 129, 220),
                width=2,
            )

        return out
