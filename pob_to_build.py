#!/usr/bin/env python3
"""PoB2 -> PoE2 .build converter.

Drop PoB2 share codes into pob_raw/ as *.pob files, then run this script.
One .build file is written to build_output/ per input, named after the input file.
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path


POB_INPUT_DIR = Path("pob_raw")
FALLBACK_OUTPUT_DIR = Path("build_output")
TREE_DATA_PATH = Path("ggg_data/data.json")
INPUT_SUFFIXES = (".pob", ".raw")
ENV_FILE = Path(".env")
OUTPUT_DIR_ENV_VAR = "POE2_BUILD_DIR"


def load_env_file(path: Path = ENV_FILE) -> None:
    """Minimal .env loader: KEY=VALUE per line, # comments, optional quotes.
    Existing environment variables take precedence."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip().strip('"').strip("'")
        os.environ.setdefault(k.strip(), v)


# --- decode --------------------------------------------------------------

def decode_share_code(code: str) -> str:
    code = code.strip()
    pad = (-len(code)) % 4
    raw = base64.urlsafe_b64decode(code + "=" * pad)
    return zlib.decompress(raw).decode("utf-8")


def load_xml_from_file(path: Path) -> str:
    content = path.read_text(encoding="utf-8").strip()
    return content if content.startswith("<") else decode_share_code(content)


# --- passive tree lookup -------------------------------------------------

def load_tree_data(path: Path) -> dict[int, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[int, str] = {}
    for k, node in data.get("nodes", {}).items():
        if k == "root":
            continue
        skill, nid = node.get("skill"), node.get("id")
        if skill is not None and nid:
            out[int(skill)] = nid
    return out


# --- xml -> .build -------------------------------------------------------

COLOR_CODE_RE = re.compile(r"\^(x[0-9A-Fa-f]{6}|\d)")


def strip_color_codes(s: str) -> str:
    return COLOR_CODE_RE.sub("", s)


def normalize_gem_id(gem_id: str) -> str:
    """PoB writes 'Metadata/Items/Gem/...'; .build docs use 'Metadata/Items/Gems/...'."""
    return gem_id.replace("/Items/Gem/", "/Items/Gems/", 1)


def get_active_spec(tree_el: ET.Element) -> ET.Element | None:
    specs = tree_el.findall("Spec")
    if not specs:
        return None
    try:
        idx = int(tree_el.get("activeSpec", "1")) - 1
    except ValueError:
        idx = 0
    return specs[idx] if 0 <= idx < len(specs) else specs[0]


def get_active_skillset(skills_el: ET.Element) -> ET.Element | None:
    sets = skills_el.findall("SkillSet")
    if not sets:
        return None
    active_id = skills_el.get("activeSkillSet")
    for ss in sets:
        if ss.get("id") == active_id:
            return ss
    return sets[0]


# 10 standard equipment slots. Maps PoB <Slot name=...> -> .build inventory_id.
ITEM_SLOT_MAP = {
    "Weapon 1": "Weapon1",
    "Weapon 2": "Weapon2",
    "Helmet": "Helm1",
    "Body Armour": "BodyArmour1",
    "Gloves": "Gloves1",
    "Boots": "Boots1",
    "Belt": "Belt1",
    "Ring 1": "Ring1",
    "Ring 2": "Ring2",
    "Amulet": "Amulet1",
}

# Item-text lines we drop from additional_text (internal metadata, not stats).
ITEM_META_PREFIXES = (
    "Rarity:", "Unique ID:", "Item Level:", "Quality:",
    "LevelReq:", "Implicits:", "Sockets:", "Rune:",
)

# PoB embeds {enchant} / {rune} / {crafted} / {fractured} etc. tags at the start
# of mod lines to indicate the mod source. Strip them for display.
ITEM_TAG_RE = re.compile(r"^(?:\{[a-zA-Z]+\})+")


def parse_item(text: str) -> dict:
    """Parse a PoB <Item> text block into rarity / name / base / stat lines."""
    lines = text.strip().splitlines()
    rarity = name = base = ""
    if lines and lines[0].startswith("Rarity:"):
        rarity = lines[0].split(":", 1)[1].strip().upper()
    if len(lines) > 1:
        name = lines[1].strip()
    # For RARE/UNIQUE, line 3 is the base type; for NORMAL/MAGIC, line 2 is the base.
    skip_idxs = {0, 1}
    if rarity in ("RARE", "UNIQUE") and len(lines) > 2:
        base = lines[2].strip()
        skip_idxs.add(2)
    body: list[str] = []
    for i, ln in enumerate(lines):
        if i in skip_idxs:
            continue
        s = ln.strip()
        if not s or s.startswith(ITEM_META_PREFIXES):
            continue
        body.append(ITEM_TAG_RE.sub("", s))
    return {"rarity": rarity, "name": name, "base": base, "body": body}


def get_active_itemset(items_el: ET.Element) -> ET.Element | None:
    sets = items_el.findall("ItemSet")
    if not sets:
        return None
    active_id = items_el.get("activeItemSet")
    for s in sets:
        if s.get("id") == active_id:
            return s
    return sets[0]


def build_inventory_slots(items_el: ET.Element | None) -> list[dict]:
    """Active ItemSet's mapped slots → list of BuildInventorySlot dicts."""
    if items_el is None:
        return []
    item_by_id = {it.get("id"): (it.text or "") for it in items_el.findall("Item")}
    active = get_active_itemset(items_el)
    if active is None:
        return []
    out: list[dict] = []
    for slot in active.findall("Slot"):
        pob_name = slot.get("name", "")
        item_id = slot.get("itemId", "0")
        if item_id == "0" or pob_name not in ITEM_SLOT_MAP:
            continue
        text = item_by_id.get(item_id)
        if not text:
            continue
        parsed = parse_item(text)
        entry: dict = {"inventory_id": ITEM_SLOT_MAP[pob_name]}
        if parsed["rarity"] == "UNIQUE" and parsed["name"]:
            entry["unique_name"] = parsed["name"]
        else:
            parts = [parsed["name"]]
            if parsed["base"]:
                parts.append(parsed["base"])
            if parsed["body"]:
                parts.append("")
                parts.extend(parsed["body"])
            additional = "\n".join(p for p in parts if p).strip()
            if additional:
                entry["additional_text"] = additional
        out.append(entry)
    return out


def classify_gem(gem_id: str) -> str:
    """Return 'skill', 'support', 'meta', or 'unknown'."""
    lower = gem_id.lower()
    if "supportgem" in lower:
        return "support"
    if "metagem" in lower:
        return "meta"
    if "skillgem" in lower:
        return "skill"
    return "unknown"


def transform(xml_root: ET.Element, hash_to_id: dict[int, str], name: str) -> dict:
    build_el = xml_root.find("Build")
    tree_el = xml_root.find("Tree")
    skills_el = xml_root.find("Skills")
    notes_el = xml_root.find("Notes")

    active_spec = get_active_spec(tree_el) if tree_el is not None else None

    # ascendancy: active spec's internal id, fallback to <Build ascendClassName>.
    # .build format wants the internal id verbatim (e.g. "Warrior1", "Mercenary2").
    ascendancy = active_spec.get("ascendancyInternalId", "") if active_spec is not None else ""
    if not ascendancy and build_el is not None:
        ascendancy = build_el.get("ascendClassName", "")
    if ascendancy in ("", "None"):
        ascendancy = None

    passives: list[str] = []
    if active_spec is not None:
        for h in active_spec.get("nodes", "").split(","):
            h = h.strip()
            if not h:
                continue
            try:
                hi = int(h)
            except ValueError:
                continue
            pid = hash_to_id.get(hi)
            if pid is None:
                print(f"  warning: unmapped passive hash {hi}", file=sys.stderr)
                continue
            passives.append(pid)

    skill_groups: list[dict] = []
    if skills_el is not None:
        ss = get_active_skillset(skills_el)
        if ss is not None:
            for group in ss.findall("Skill"):
                main_id: str | None = None
                supports: list[str] = []
                for g in group.findall("Gem"):
                    gid = g.get("gemId", "")
                    if not gid:
                        continue  # empty placeholder slot
                    kind = classify_gem(gid)
                    if kind == "meta":
                        print(f"  warning: skipping meta gem {gid}", file=sys.stderr)
                    elif kind == "skill" and main_id is None:
                        main_id = normalize_gem_id(gid)
                    elif kind == "support":
                        supports.append(normalize_gem_id(gid))
                    elif kind == "unknown":
                        print(f"  warning: unknown gem type {gid}", file=sys.stderr)
                if main_id is not None:
                    entry: dict = {"id": main_id}
                    if supports:
                        entry["support_skills"] = supports
                    skill_groups.append(entry)

    description = ""
    if notes_el is not None and notes_el.text:
        description = strip_color_codes(notes_el.text).strip()

    out: dict = {"name": name}
    if description:
        out["description"] = description
    if ascendancy:
        out["ascendancy"] = ascendancy
    if passives:
        out["passives"] = passives
    if skill_groups:
        out["skills"] = skill_groups
    inv_slots = build_inventory_slots(xml_root.find("Items"))
    if inv_slots:
        out["inventory_slots"] = inv_slots
    return out


# --- entry point ---------------------------------------------------------

def safe_filename(s: str) -> str:
    return re.sub(r"[^\w.-]", "_", s) or "build"


def resolve_output_dir() -> Path:
    """Use POE2_BUILD_DIR if set (via env or .env), else fall back locally."""
    load_env_file()
    configured = os.environ.get(OUTPUT_DIR_ENV_VAR, "").strip()
    if configured:
        return Path(configured)
    print(
        f"note: {OUTPUT_DIR_ENV_VAR} not set; writing to ./{FALLBACK_OUTPUT_DIR}/. "
        f"Copy .env.example to .env and set it to the in-game BuildPlanner folder.",
        file=sys.stderr,
    )
    return FALLBACK_OUTPUT_DIR


def main() -> int:
    if not TREE_DATA_PATH.exists():
        print(f"error: {TREE_DATA_PATH} not found", file=sys.stderr)
        return 1
    if not POB_INPUT_DIR.is_dir():
        print(f"error: {POB_INPUT_DIR}/ directory not found", file=sys.stderr)
        return 1

    files = sorted(
        p for p in POB_INPUT_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in INPUT_SUFFIXES
    )
    if not files:
        print(f"no {' or '.join(INPUT_SUFFIXES)} files in {POB_INPUT_DIR}/", file=sys.stderr)
        return 1

    output_dir = resolve_output_dir()
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"error: cannot create output dir {output_dir}: {e}", file=sys.stderr)
        return 1

    hash_to_id = load_tree_data(TREE_DATA_PATH)

    failures = 0
    for f in files:
        print(f"{f.name}:", file=sys.stderr)
        try:
            xml = load_xml_from_file(f)
            root = ET.fromstring(xml)
            payload = transform(root, hash_to_id, name=f.stem)
            out_path = output_dir / f"{safe_filename(f.stem)}.build"
            out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            print(
                f"  -> {out_path} "
                f"({len(payload.get('passives', []))} passives, "
                f"{len(payload.get('skills', []))} skill groups)",
                file=sys.stderr,
            )
        except Exception as e:
            print(f"  error: {e}", file=sys.stderr)
            failures += 1

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
