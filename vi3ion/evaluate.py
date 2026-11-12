"""Brief fidelity: score a generated brief against hand-transcribed ground truth.

The point of this module is to make the brief's quality *measurable* instead of
asserted. Four independent components are reported so a reader can see where a
brief fails, and the overall number is a documented weighted mean of them:

    recall    0.40  share of the real text that reached the brief
    precision 0.25  share of the brief's quoted text that is really there
    regions   0.20  share of matched text filed under the right region
    structure 0.15  composition line, colour map, shape sentences, honesty note

Nothing here looks at the image: it compares two texts, so the same scorer
works for any language, any provider, and in CI without OCR installed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

MATCH_THRESHOLD = 0.75
WEIGHTS = {"recall": 0.40, "precision": 0.25, "regions": 0.20, "structure": 0.15}
COLOR_MAP_CELLS = 12
MIN_SHAPES = 3

# Traditional / shinjitai forms folded onto their simplified equivalent for
# comparison only (the brief itself never rewrites a read). This mirrors the
# glyph variation OCR produces for low-resolution CJK: the reading `阳門` and
# the expected `陽門` are the same character pair in two orthographies.
CJK_VARIANT_FOLD = {
    "陽": "阳", "門": "门", "學": "学", "宮": "宫",
    "兩": "两", "両": "两", "極": "极", "寶": "宝",
    "內": "内", "閣": "阁", "跡": "迹", "蔵": "藏",
    "臺": "台", "國": "国", "廣": "广", "華": "华",
    "萬": "万", "與": "与", "無": "无", "點": "点",
    "聲": "声", "體": "体", "當": "当", "發": "发",
    "長": "长", "風": "风", "見": "见", "貝": "贝",
    "車": "车", "馬": "马", "鳥": "鸟", "魚": "鱼",
    "龍": "龙", "齊": "齐", "齋": "斋", "劇": "剧",
    "對": "对", "雙": "双", "鑑": "鉴", "鐘": "钟",
    "鏡": "镜", "銀": "银", "錢": "钱", "錯": "错",
    "鍋": "锅", "飯": "饭", "館": "馆", "說": "说",
    "語": "语", "講": "讲", "讀": "读", "寫": "写",
    "書": "书", "畫": "画", "聽": "听", "樂": "乐",
    "嚴": "严", "惡": "恶", "愛": "爱", "覺": "觉",
    "飛": "飞", "號": "号", "雖": "虽", "離": "离",
    "難": "难", "雲": "云", "電": "电", "頭": "头",
    "題": "题", "願": "愿",
}

SECTION_LABELS = {
    "Top bar": "top_bar",
    "Left column": "left_column",
    "Centre": "centre",
    "Right column": "right_column",
    "Bottom bar": "bottom_bar",
}
SECTION_SPLIT_RE = re.compile(r"\b(" + "|".join(SECTION_LABELS) + r"):")
# A brief value may itself contain quotes (`00 + "PORTFOLIO"`), so values are
# delimited by their trailing annotations rather than by bare quote matching.
ANNOTATIONS = (' (split from', ' (possibly', ' (uncertain', ' @[')


@dataclass
class FidelityReport:
    overall: float = 0.0
    recall: float = 0.0
    precision: float = 0.0
    regions: float = 0.0
    structure: float = 0.0
    expected_units: int = 0
    matched_units: int = 0
    missing: list[str] = field(default_factory=list)
    spurious: list[str] = field(default_factory=list)
    structure_checks: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "overall": round(self.overall, 3),
            "recall": round(self.recall, 3),
            "precision": round(self.precision, 3),
            "regions": round(self.regions, 3),
            "structure": round(self.structure, 3),
            "expected_units": self.expected_units,
            "matched_units": self.matched_units,
            "structure_checks": self.structure_checks,
            "missing": self.missing,
            "spurious": self.spurious,
        }


def normalize(text: str) -> str:
    """Case-folded, punctuation-free text for comparison only.

    CJK variant forms (traditional/shinjitai/simplified) are folded onto one
    orthography first, so `陽門` and `阳門` compare equal — orthographic
    variation is not a reading difference. Nothing here edits the brief.
    """
    folded = "".join(CJK_VARIANT_FOLD.get(ch, ch) for ch in text)
    return re.sub(r"[^0-9a-z\u3040-\u30ff\u3400-\u9fff]+", " ", folded.lower()).strip()


def similarity(expected: str, candidate: str) -> float:
    """1.0 for an exact or containing match, else a fuzzy ratio.

    Containment counts because a brief joins and splits OCR fragments freely:
    the expected `00` inside the brief's `00 + "PORTFOLIO"` is a hit. The
    reverse direction is only partial credit, so a label that lost its number
    (`GRADEIFY` for `02 GRADEIFY`) is scored as the near miss it is.
    """
    a, b = normalize(expected), normalize(candidate)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if len(a) >= 2 and a in b:
        return 1.0
    if len(b) >= 2 and b in a:
        return len(b) / len(a)
    seq = SequenceMatcher(None, a, b).ratio()
    # Long prose: OCR often fragments a paragraph across lines/items, so
    # word-set overlap is a fairer signal than character-sequence ratio.
    if max(len(a), len(b)) >= 24:
        ta, tb = set(a.split()), set(b.split())
        if ta and tb:
            jaccard = len(ta & tb) / len(ta | tb)
            return max(seq, 0.70 * jaccard + 0.30 * seq)
    return seq


def is_supported(value: str, expected_values: list[str]) -> bool:
    """A brief value is real if a ground-truth unit supports it, either way."""
    normalized = normalize(value)
    for expected in expected_values:
        other = normalize(expected)
        if not other or not normalized:
            continue
        if similarity(value, expected) >= MATCH_THRESHOLD:
            return True
        if other in normalized:
            return True
    return False


def load_expected(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _value_of(piece: str) -> str | None:
    """Read one rendered item back into its text value."""
    start = piece.find('"')
    if start < 0:
        return None
    tail = piece[start + 1:]
    cuts = [tail.find(marker) for marker in ANNOTATIONS if tail.find(marker) >= 0]
    body = tail[: min(cuts)] if cuts else tail
    end = body.rfind('"')
    if end < 0:
        return None
    value = body[:end].strip()
    return value or None


def _sections(text: str) -> dict[str, str]:
    """Body text per named section, in rendering order."""
    parts = SECTION_SPLIT_RE.split(text)
    bodies: dict[str, str] = {}
    for index in range(1, len(parts) - 1, 2):
        bodies.setdefault(SECTION_LABELS[parts[index]], parts[index + 1])
    return bodies


def parse_brief(text: str) -> list[tuple[str, str | None]]:
    """Text values with the section label they appear under.

    A ``(possibly "X", uncertain)`` annotation is also returned as an
    alternative candidate in the same region, because the brief is explicitly
    offering X as a possible reading of the same pixels.
    """
    labelled: list[tuple[str, str | None]] = []
    for region, body in _sections(text).items():
        for piece in body.split("; "):
            value = _value_of(piece)
            if value:
                labelled.append((value, region))
            alt = re.search(r'\(possibly "([^"]+)"', piece)
            if alt:
                labelled.append((alt.group(1), region))
            # A row that reports its number as not-read names an expected value
            # (`(number not read, expected "00")`); that expected reading is an
            # offered candidate in the same region.
            num = re.search(r'\(number not read, expected "(\d+)"', piece)
            if num and value:
                labelled.append((f"{num.group(1)} {value}", region))
    return labelled


def _region_blobs(text: str) -> dict[str, str]:
    """Concatenated text per named section, for joined/split values."""
    blobs: dict[str, str] = {}
    for region, body in _sections(text).items():
        blobs[region] = " ".join(
            value for value in (_value_of(p) for p in body.split("; ")) if value
        )
    return blobs


def _structure_checks(text: str) -> dict[str, bool]:
    colour_cells = len(re.findall(r"row \d, col \d:", text))
    shapes = len(re.findall(r"\b(a|an) (tall vertical column|rectangular area|round shape|horizontal band|vertical band)", text))
    return {
        "composition line": "Composition:" in text,
        "colour map (12 cells)": colour_cells >= COLOR_MAP_CELLS,
        "shape sentences": shapes >= MIN_SHAPES,
        "honesty note": "does not name objects" in text,
    }


def review(brief_text: str, expected: dict) -> FidelityReport:
    """Compare a brief against ground truth and report every component."""
    units = [unit for unit in expected.get("text", []) if unit.get("value")]
    report = FidelityReport(expected_units=len(units))
    if not units:
        return report

    quoted = parse_brief(brief_text)
    blobs = _region_blobs(brief_text)
    candidates = [value for value, _ in quoted] + list(blobs.values()) + [brief_text]
    flat_brief = " ".join(value for value, _ in quoted) or brief_text

    matched_flags: list[bool] = []
    region_hits = 0
    region_checked = 0
    for unit in units:
        best = 0.0
        best_value: tuple[str, str | None] | None = None
        best_in_region = 0.0
        best_value_in_region: tuple[str, str | None] | None = None
        for value, region in quoted:
            score = similarity(unit["value"], value)
            if score > best:
                best, best_value = score, (value, region)
            if region == unit.get("region") and score > best_in_region:
                best_in_region, best_value_in_region = score, (value, region)
        # When the same text exists in several regions, prefer the candidate
        # filed under the expected region even if it scores slightly lower
        # (e.g. `01 THE MAKER` appears in the left subheader and the ledger).
        if (
            best_value_in_region is not None
            and best_in_region >= MATCH_THRESHOLD
            and best_in_region >= 0.85 * max(best, 0.0001)
        ):
            best, best_value = best_in_region, best_value_in_region
        for blob in blobs.values():
            best = max(best, similarity(unit["value"], blob))
        if best < MATCH_THRESHOLD:
            best = max(best, similarity(unit["value"], brief_text))
        ok = best >= MATCH_THRESHOLD
        matched_flags.append(ok)
        if not ok:
            report.missing.append(unit["value"])
            continue
        if best_value and unit.get("region"):
            region_checked += 1
            if best_value[1] == unit["region"]:
                region_hits += 1

    report.matched_units = sum(matched_flags)
    report.recall = report.matched_units / len(units)

    expected_values = [unit["value"] for unit in units]
    correct = 0
    for value, _ in quoted:
        if is_supported(value, expected_values):
            correct += 1
        else:
            report.spurious.append(value)
    report.precision = correct / len(quoted) if quoted else 0.0

    report.regions = region_hits / region_checked if region_checked else 0.0
    checks = _structure_checks(brief_text)
    report.structure_checks = checks
    report.structure = sum(1 for ok in checks.values() if ok) / len(checks)

    report.overall = (
        WEIGHTS["recall"] * report.recall
        + WEIGHTS["precision"] * report.precision
        + WEIGHTS["regions"] * report.regions
        + WEIGHTS["structure"] * report.structure
    )
    return report


def find_expected(image_path: str | Path, roots: list[Path] | None = None) -> Path | None:
    """Locate a ground-truth file whose `_meta.image` names this file."""
    name = Path(image_path).name
    search = roots or [Path("tests/fixtures")]
    for root in search:
        if not root.is_dir():
            continue
        for candidate in sorted(root.glob("*.expected.json")):
            try:
                meta = load_expected(candidate).get("_meta", {})
            except (OSError, ValueError):
                continue
            if Path(str(meta.get("image", ""))).name == name:
                return candidate
    return None
