#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

AUDIO_EXTS = {".wav", ".aif", ".aiff", ".flac", ".ogg", ".mp3"}
IGNORE_EXTS = {".reapeaks", ".asd"}

NOTE_RE = re.compile(r"\b([A-Ga-g])\s*([#bB]?)(-?\d+)\b")  # e.g. G#3, Bb2, C-1

NOTE_TO_SEMI = {
    "C": 0, "C#": 1, "DB": 1,
    "D": 2, "D#": 3, "EB": 3,
    "E": 4,
    "F": 5, "F#": 6, "GB": 6,
    "G": 7, "G#": 8, "AB": 8,
    "A": 9, "A#": 10, "BB": 10,
    "B": 11,
}

@dataclass(frozen=True)
class SampleEntry:
    path: str           # absolute or source path
    root_midi: int      # 0..127
    vel_hi: Optional[int]  # 1..127 or None

def note_to_midi(note: str, middle_c: int = 4) -> Optional[int]:
    """
    Convert note like C4 to MIDI note number, where C{middle_c} == 60.
    Default middle_c=4 means standard C4=60, so C3=48.
    """
    m = re.match(r"^([A-Ga-g])([#bB]?)(-?\d+)$", note.strip())
    if not m:
        return None
    letter, acc, oct_s = m.groups()
    letter = letter.upper()
    acc = acc.upper()
    if acc == "B":  # allow 'b' => 'B'
        acc = "B"
    key = letter + acc
    if key not in NOTE_TO_SEMI:
        return None
    semis = NOTE_TO_SEMI[key]
    octave = int(oct_s)

    # If C{middle_c} == 60, then MIDI = 60 + 12*(octave-middle_c) + semis
    midi = 60 + 12 * (octave - middle_c) + semis
    if 0 <= midi <= 127:
        return midi
    return None

def build_regex_from_pattern(pattern: str) -> re.Pattern:
    # Escape regex special chars except our tokens
    # Support tokens: {note}, {vel}
    esc = re.escape(pattern)
    esc = esc.replace(r"\{note\}", r"(?P<note>[A-Ga-g][#bB]?-?\d+)")
    esc = esc.replace(r"\{vel\}", r"(?P<vel>\d+)")
    return re.compile(rf"^{esc}$")

def auto_detect(name_no_ext: str, middle_c: int) -> Tuple[Optional[int], Optional[int]]:
    """
    Heuristic (SAFE):
      - find first note token like G#3 / Bb2 / C4
      - detect velocity ONLY if explicitly tagged (vel127, vel_127, v100, v-100, etc.)
        Never use a trailing number heuristic (too ambiguous with note octaves like C1, C2, C3).
    """
    root = None
    vel_hi = None

    # Note
    nm = NOTE_RE.search(name_no_ext)
    if nm:
        letter, acc, oct_s = nm.groups()
        acc = acc.replace("b", "B").replace("B", "B")
        note_str = f"{letter}{acc}{oct_s}"
        root = note_to_midi(note_str, middle_c=middle_c)

    # Velocity candidates: ONLY explicit markers
    # Matches: vel127, vel_127, vel-127, v127, v_127, v-127 (case-insensitive)
    candidates: List[int] = []
    for m in re.finditer(r"(?:\bvel|\bv)[ _\-]?(\d{1,3})\b", name_no_ext, flags=re.IGNORECASE):
        v = int(m.group(1))
        if 1 <= v <= 127:
            candidates.append(v)

    if candidates:
        vel_hi = candidates[-1]

    return root, vel_hi

def list_samples_from_folder(folder: str) -> List[str]:
    out = []
    for fn in os.listdir(folder):
        p = os.path.join(folder, fn)
        if not os.path.isfile(p):
            continue
        ext = os.path.splitext(fn)[1].lower()
        if ext in IGNORE_EXTS:
            continue
        if ext in AUDIO_EXTS:
            out.append(p)
    return sorted(out)

def common_prefix_name(stems: List[str]) -> str:
    if not stems:
        return "Instrument"
    # Common prefix (character-based), then trim separators
    pref = os.path.commonprefix(stems).strip()
    pref = re.sub(r"[_\-\s]+$", "", pref)
    pref = pref.strip()
    return pref if pref else "Instrument"

def compute_key_ranges(sorted_roots: List[int],
                       low_spread: Optional[int] = None,
                       high_spread: Optional[int] = None) -> Dict[int, Tuple[int,int]]:
    """
    Compute chromatic key ranges.
    - Middle splits are midpoint-based.
    - Extremes can be limited by low_spread / high_spread (in semitones).
    """
    ranges = {}
    n = len(sorted_roots)

    min_root = sorted_roots[0]
    max_root = sorted_roots[-1]

    for i, r in enumerate(sorted_roots):
        # lower bound
        if i == 0:
            lo = 0
            if low_spread is not None:
                lo = max(0, min_root - max(0, low_spread))
        else:
            lo = (sorted_roots[i-1] + r) // 2 + 1

        # upper bound
        if i == n - 1:
            hi = 127
            if high_spread is not None:
                hi = min(127, max_root + max(0, high_spread))
        else:
            hi = (r + sorted_roots[i+1]) // 2

        ranges[r] = (lo, hi)

    return ranges


def compute_vel_ranges(vel_his: List[int]) -> List[Tuple[int,int,int]]:
    """
    vel_his sorted ascending.
    Return list of tuples (vel_hi, loVel, hiVel) where hiVel is exactly vel_hi from filename.
    loVel is prev_hi + 1, starting at 0.
    """
    vel_his = sorted(vel_his)
    out = []
    lo = 0
    for vhi in vel_his:
        hi = max(0, min(127, vhi))
        out.append((vhi, lo, hi))
        lo = hi + 1
        if lo > 127:
            break
    return out

def relpath_for_preset(sample_path: str, preset_dir: str) -> str:
    try:
        return os.path.relpath(sample_path, preset_dir).replace("\\", "/")
    except Exception:
        return os.path.basename(sample_path)

def make_dspreset(entries: List[SampleEntry], preset_path: str, copy_samples: bool, on_duplicate: str, low_spread: Optional[int] = None ,  high_spread: Optional[int] = None) -> None:
    preset_dir = os.path.dirname(os.path.abspath(preset_path))
    os.makedirs(preset_dir, exist_ok=True)

    # Optional: copy samples into preset_dir/Samples
    sample_out_dir = preset_dir
    if copy_samples:
        sample_out_dir = os.path.join(preset_dir, "Samples")
        os.makedirs(sample_out_dir, exist_ok=True)

    # Group by root note
    by_note: Dict[int, List[SampleEntry]] = {}
    for e in entries:
        by_note.setdefault(e.root_midi, []).append(e)

    roots = sorted(by_note.keys())
    key_ranges = compute_key_ranges(
        roots,
        low_spread=low_spread,
        high_spread=high_spread
    )


    # Build XML
    root = ET.Element("DecentSampler")
    groups = ET.SubElement(root, "groups")

    for r in roots:
        loNote, hiNote = key_ranges[r]
        group = ET.SubElement(groups, "group")

        # If vel is missing for all samples of this note => single full-range
        samples_for_note = by_note[r]
        have_vel = any(s.vel_hi is not None for s in samples_for_note)

        if not have_vel:
            # pick one sample (if multiple: duplicate policy)
            chosen = samples_for_note[-1] if on_duplicate == "keep-last" else samples_for_note[0]
            src = chosen.path
            if copy_samples:
                dst = os.path.join(sample_out_dir, os.path.basename(src))
                if os.path.abspath(src) != os.path.abspath(dst):
                    shutil.copy2(src, dst)
                sample_path = relpath_for_preset(dst, preset_dir)
            else:
                sample_path = relpath_for_preset(src, preset_dir)

            ET.SubElement(group, "sample", {
                "path": sample_path,
                "rootNote": str(r),
                "loNote": str(loNote),
                "hiNote": str(hiNote),
                "loVel": "0",
                "hiVel": "127",
            })
            continue

        # Velocity layered note
        # Map vel_hi -> sample (handle duplicates)
        vel_map: Dict[int, SampleEntry] = {}
        for s in samples_for_note:
            if s.vel_hi is None:
                continue
            v = int(s.vel_hi)
            if v in vel_map:
                if on_duplicate == "error":
                    raise ValueError(f"Duplicate vel_hi {v} for root {r}")
                if on_duplicate == "keep-last":
                    vel_map[v] = s
                # keep-first => do nothing
            else:
                vel_map[v] = s

        vel_his = sorted(vel_map.keys())
        vel_ranges = compute_vel_ranges(vel_his)

        for vhi, loVel, hiVel in vel_ranges:
            s = vel_map.get(vhi)
            if not s:
                continue
            src = s.path
            if copy_samples:
                dst = os.path.join(sample_out_dir, os.path.basename(src))
                if os.path.abspath(src) != os.path.abspath(dst):
                    shutil.copy2(src, dst)
                sample_path = relpath_for_preset(dst, preset_dir)
            else:
                sample_path = relpath_for_preset(src, preset_dir)

            ET.SubElement(group, "sample", {
                "path": sample_path,
                "rootNote": str(r),
                "loNote": str(loNote),
                "hiNote": str(hiNote),
                "loVel": str(loVel),
                "hiVel": str(hiVel),
            })

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ", level=0)
    tree.write(preset_path, encoding="utf-8", xml_declaration=True)

def derive_output_path(out_arg: Optional[str], sample_paths: List[str], preset_name_hint: Optional[str]) -> str:
    # Default: in folder containing samples
    base_folder = os.path.dirname(os.path.abspath(sample_paths[0])) if sample_paths else os.getcwd()

    if not out_arg:
        name = preset_name_hint or os.path.basename(base_folder) or "Instrument"
        return os.path.join(base_folder, f"{name}.dspreset")

    out_arg = os.path.expanduser(out_arg)
    if out_arg.lower().endswith(".dspreset"):
        return out_arg

    # out is a directory
    os.makedirs(out_arg, exist_ok=True)
    name = preset_name_hint or os.path.basename(base_folder) or "Instrument"
    return os.path.join(out_arg, f"{name}.dspreset")

def main():
    ap = argparse.ArgumentParser(description="Generate a Decent Sampler .dspreset from multisamples.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--folder", help="Folder containing samples")
    src.add_argument("--samples", nargs="+", help="List of sample files")

    ap.add_argument("--out", help="Output .dspreset path OR output directory. Default: sample folder.")
    ap.add_argument("--pattern", help="Explicit pattern, e.g. 'piano_{note}_vel{vel}' (no extension).")
    ap.add_argument("--middle-c", type=int, default=3, help="Define C{N} = 60. Default: 4 (C4=60).")
    ap.add_argument("--copy-samples", action="store_true", help="Copy samples next to preset under Samples/ for portability.")
    ap.add_argument("--on-duplicate", choices=["error", "keep-first", "keep-last"], default="keep-last")
    ap.add_argument("--low-spread", type=int, default=12,
                help="Limit extension below lowest root (in semitones).")
    ap.add_argument("--high-spread", type=int, default=12,
                help="Limit extension above highest root (in semitones).")


    args = ap.parse_args()

    if args.folder:
        folder = os.path.expanduser(args.folder)
        sample_paths = list_samples_from_folder(folder)
    else:
        sample_paths = [os.path.expanduser(p) for p in args.samples]

    sample_paths = [p for p in sample_paths if os.path.isfile(p) and os.path.splitext(p)[1].lower() in AUDIO_EXTS]
    if not sample_paths:
        print("No valid sample files found.", file=sys.stderr)
        sys.exit(2)

    # Parse
    rx = build_regex_from_pattern(args.pattern) if args.pattern else None
    entries: List[SampleEntry] = []
    stems: List[str] = []

    for p in sample_paths:
        fn = os.path.basename(p)
        stem, _ext = os.path.splitext(fn)
        stems.append(stem)

        root_midi = None
        vel_hi = None

        if rx:
            m = rx.match(stem)
            if not m:
                continue
            note = m.groupdict().get("note")
            vel = m.groupdict().get("vel")
            root_midi = note_to_midi(note, middle_c=args.middle_c) if note else None
            vel_hi = int(vel) if vel is not None else None
        else:
            root_midi, vel_hi = auto_detect(stem, middle_c=args.middle_c)

        if root_midi is None:
            continue
        if vel_hi is not None and not (1 <= vel_hi <= 127):
            vel_hi = None

        entries.append(SampleEntry(path=os.path.abspath(p), root_midi=root_midi, vel_hi=vel_hi))

    if not entries:
        print("No samples matched (note not detected). Provide --pattern for strict parsing.", file=sys.stderr)
        sys.exit(3)

    # Derive preset name from common prefix (helpful when --out is a directory or None)
    preset_name_hint = common_prefix_name(stems)

    preset_path = derive_output_path(args.out, sample_paths, preset_name_hint)

    make_dspreset(entries, preset_path, copy_samples=args.copy_samples, on_duplicate=args.on_duplicate,low_spread=args.low_spread, high_spread=args.high_spread)
    print(preset_path)

if __name__ == "__main__":
    main()
