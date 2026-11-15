#!/usr/bin/env python3
"""Verify the three bilingual LTX-2 story packages without network or model calls.

Run from any directory: python3 /path/to/repo/tools/verify_short_stories.py
Use --json for CI-readable output, or --data-dir to inspect another package.

source_lock.json is an intentionally maintained trust baseline, not a generated
cache. Do not refresh its hashes automatically after a failure. An intentional
translation/prompt change requires review and an explicit manifest update;
an English-source change also requires renewed full source/partition review.
This command never rewrites the manifest or any content file.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_COUNTS = {
    "the-gift-of-the-magi": 30,
    "the-open-window": 24,
    "the-selfish-giant": 30,
}
EXPECTED_TOTAL = 84
CREATOR_FIELDS = {"scene_id", "chapter", "scene_number", "scene_text", "video_script"}
KOREAN_FIELDS = {"Chapter", "Scene number", "Content", "Content_kor"}
AUDIO_FIELDS = {"mode", "speaker", "text_en", "text_ko"}
MUTING = re.compile(
    r"\b(?:silent\s+(?:video|footage|clip|film)|complete\s+silence|"
    r"no\s+(?:dialogue|audio|narration|ambient\s+audio)|"
    r"mute(?:d)?\s+(?:audio|video)|without\s+(?:any\s+)?(?:dialogue|narration|audio|sound))\b",
    re.I,
)
CONTINUOUS_SHOT = re.compile(r"one continuous|single continuous|one unbroken|single.*shot|one.*shot", re.I)


class VerificationError(Exception):
    """An actionable content or schema mismatch, without printing raw content."""


def require(condition: bool, message: str) -> None:
    # Explicit checks remain active under python -O; this is a production CLI.
    if not condition:
        raise VerificationError(message)


def no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise VerificationError(f"Duplicate JSON object key: {key}")
        result[key] = value
    return result


def parse_json(text: str, label: str):
    try:
        return json.loads(text, object_pairs_hook=no_duplicate_keys)
    except (json.JSONDecodeError, VerificationError) as exc:
        raise VerificationError(f"{label}: invalid JSON ({exc})") from exc


def read_utf8(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise VerificationError(f"Cannot read UTF-8 file {path.name}: {exc}") from exc


def read_json(path: Path):
    return parse_json(read_utf8(path), path.name)


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    for number, line in enumerate(read_utf8(path).splitlines(), 1):
        require(bool(line.strip()), f"{path.name}:{number}: empty JSONL row")
        row = parse_json(line, f"{path.name}:{number}")
        require(isinstance(row, dict), f"{path.name}:{number}: expected a JSON object")
        rows.append(row)
    return rows


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def nonempty_string(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def verify(data_dir: Path) -> dict:
    lock = read_json(data_dir / "source_lock.json")
    require(isinstance(lock, dict) and lock.get("schema_version") == 1, "source_lock.json: unsupported schema")
    require(lock.get("expected_total_scenes") == EXPECTED_TOTAL, "source_lock.json: expected total must stay 84")
    locked_works = lock.get("works")
    require(isinstance(locked_works, dict) and set(locked_works) == set(EXPECTED_COUNTS), "source_lock.json: expected exactly the three approved works")
    books = read_json(data_dir / "books.json")
    require(isinstance(books, dict) and set(books) == set(EXPECTED_COUNTS), "books.json: work slugs differ")
    sources = read_json(data_dir / "SOURCES.json")
    require(isinstance(sources, list) and len(sources) == 3, "SOURCES.json: expected three source records")
    require(all(isinstance(item, dict) and nonempty_string(item.get("slug")) for item in sources), "SOURCES.json: invalid source record")
    require(len({item["slug"] for item in sources}) == 3, "SOURCES.json: duplicate source slug")
    source_by_slug = {item["slug"]: item for item in sources}
    require(set(source_by_slug) == set(EXPECTED_COUNTS), "SOURCES.json: work slugs differ")
    totals = Counter()
    duration_totals = Counter()
    result_works = []
    locked_file_count = 0
    for slug, expected_count in EXPECTED_COUNTS.items():
        baseline = locked_works[slug]
        require(isinstance(baseline, dict) and baseline.get("scene_count") == expected_count, f"{slug}: locked scene count differs")
        expected_names = {f"{slug}.jsonl", f"{slug}.source-ko.jsonl", f"{slug}.audio.json"}
        files = baseline.get("files")
        require(isinstance(files, dict) and set(files) == expected_names, f"{slug}: manifest must lock exactly its three package files")
        for name, expected_hash in files.items():
            require(isinstance(expected_hash, str) and re.fullmatch(r"[0-9a-f]{64}", expected_hash) is not None, f"{name}: malformed manifest SHA-256")
            try:
                actual_hash = digest((data_dir / name).read_bytes())
            except OSError as exc:
                raise VerificationError(f"Missing package file {name}: {exc}") from exc
            require(actual_hash == expected_hash, f"{name}: SHA-256 differs from the reviewed baseline; review the content before explicitly maintaining source_lock.json")
            locked_file_count += 1
        expected_metadata = baseline.get("metadata")
        require(isinstance(expected_metadata, dict), f"{slug}: missing locked metadata")
        require(books[slug] == expected_metadata, f"{slug}: books.json differs from approved website metadata")
        source_record = source_by_slug[slug]
        require(source_record.get("title") == expected_metadata["title"] and source_record.get("author") == expected_metadata["author"], f"{slug}: source title/author differs")
        require(source_record.get("source_url") == baseline.get("source_url") and source_record.get("source_ebook_id") == baseline.get("source_ebook_id"), f"{slug}: source attribution differs")
        creator = read_jsonl(data_dir / f"{slug}.jsonl")
        korean = read_jsonl(data_dir / f"{slug}.source-ko.jsonl")
        audio_package = read_json(data_dir / f"{slug}.audio.json")
        require(isinstance(audio_package, dict) and audio_package.get("slug") == slug and audio_package.get("model_family") == "LTX-2", f"{slug}: audio package metadata differs")
        audio_rows = audio_package.get("scenes")
        require(isinstance(audio_rows, list), f"{slug}: audio.scenes must be an array")
        require(len(creator) == len(korean) == len(audio_rows) == expected_count, f"{slug}: creator/Korean/audio row count differs")
        story_parts = []
        modes = Counter()
        longest_speech = 0
        total_duration = 0
        for number, (row, ko, cue) in enumerate(zip(creator, korean, audio_rows), 1):
            label = f"{slug}/1_{number}"
            require(set(row) == CREATOR_FIELDS, f"{label}: creator must have exactly five fields")
            require(type(row["chapter"]) is int and row["chapter"] == 1, f"{label}: chapter must be integer 1")
            require(type(row["scene_number"]) is int and row["scene_number"] == number, f"{label}: scene number must be sequential")
            require(row["scene_id"] == f"1_{number}", f"{label}: creator scene ID differs")
            require(nonempty_string(row["scene_text"]), f"{label}: missing original English text")
            script = row["video_script"]
            require(isinstance(script, dict) and set(script) == {"prompt"}, f"{label}: video_script must contain only prompt")
            prompt = script["prompt"]
            require(nonempty_string(prompt) and len(prompt) > 100, f"{label}: missing audiovisual prompt")
            require(MUTING.search(prompt) is None, f"{label}: prompt contains a forced-muting instruction")
            require(CONTINUOUS_SHOT.search(prompt) is not None, f"{label}: missing continuous-shot instruction")
            require(re.search(r"no (?:subtitles|captions)", prompt, re.I) is not None, f"{label}: missing no-rendered-text constraint")
            require(set(ko) == KOREAN_FIELDS, f"{label}: Korean input must have exactly four legacy fields")
            require(type(ko["Chapter"]) is int and ko["Chapter"] == 1 and type(ko["Scene number"]) is int and ko["Scene number"] == number, f"{label}: Korean chapter/scene ID differs")
            require(ko["Content"] == row["scene_text"], f"{label}: English text differs between creator and Korean input")
            translation = ko["Content_kor"]
            require(nonempty_string(translation) and re.search("[가-힣]", translation) is not None, f"{label}: missing Korean translation")
            require(re.search(r"TODO|번역 예정|번역 생략|요약만|[\u3040-\u30ff]", translation) is None, f"{label}: translation placeholder or unexpected language")
            require(isinstance(cue, dict), f"{label}: invalid audio scene")
            require(cue.get("scene_id") == row["scene_id"] and cue.get("source_scene_id") == f"{slug}-001-{number:03d}", f"{label}: audio source/creator ID differs")
            require(type(cue.get("chapter")) is int and cue["chapter"] == 1 and type(cue.get("scene_number")) is int and cue["scene_number"] == number, f"{label}: audio chapter/scene differs")
            seconds = cue.get("duration_seconds")
            require(type(seconds) is int and seconds in (8, 10, 12), f"{label}: duration must be 8, 10 or 12 seconds")
            require(nonempty_string(cue.get("continuity_notes_ko")), f"{label}: missing continuity notes")
            audio = cue.get("audio")
            require(isinstance(audio, dict) and set(audio) == AUDIO_FIELDS, f"{label}: audio must have mode, speaker, text_en and text_ko")
            mode = audio["mode"]
            require(mode in ("dialogue", "narration", "ambience"), f"{label}: invalid audio mode")
            require(nonempty_string(audio["speaker"]), f"{label}: missing speaker label")
            require(isinstance(audio["text_en"], str) and isinstance(audio["text_ko"], str), f"{label}: invalid audio text type")
            if mode != "ambience":
                quote = normalized(audio["text_en"])
                require(bool(quote), f"{label}: missing spoken line")
                require(quote in normalized(row["scene_text"]), f"{label}: spoken line is not a contiguous source excerpt after whitespace normalization")
                require(quote in normalized(prompt), f"{label}: spoken line is missing from prompt")
                require(nonempty_string(audio["text_ko"]) and re.search("[가-힣]", audio["text_ko"]) is not None, f"{label}: missing Korean speech translation")
                word_count = len(quote.split())
                require(word_count <= seconds * 2.5, f"{label}: speech exceeds 2.5 words per second")
                longest_speech = max(longest_speech, word_count)
            story_parts.append(row["scene_text"])
            modes[mode] += 1
            duration_totals[seconds] += 1
            total_duration += seconds
        reconstructed = "".join(story_parts)
        require(len(reconstructed) == baseline.get("source_characters"), f"{slug}: reconstructed source character count differs")
        require(digest(reconstructed.encode("utf-8")) == baseline.get("source_story_sha256"), f"{slug}: full original English story SHA-256 differs")
        totals.update(modes)
        result_works.append({"slug": slug, "scenes": expected_count, "source_characters": len(reconstructed),
                             "original_english_sha256": baseline["source_story_sha256"],
                             "audio_modes": dict(modes), "duration_seconds_total": total_duration,
                             "longest_spoken_line_words": longest_speech})
    require(locked_file_count == 9 and sum(totals.values()) == EXPECTED_TOTAL, "Expected exactly nine locked files and 84 scenes")
    return {"verified": True, "total_scenes": EXPECTED_TOTAL, "locked_files_verified": locked_file_count,
            "audio_modes": dict(totals), "duration_counts": {str(k): duration_totals[k] for k in sorted(duration_totals)},
            "works": result_works,
            "checks": ["exact five-field creator schema and original scene IDs", "reviewed byte hashes of all nine content files",
                       "complete original English story SHA-256", "exact English/Korean source correspondence and nonempty locked Korean translations",
                       "audio scene IDs and duration values", "contiguous original-source speech excerpts and prompt inclusion",
                       "speech timing budget", "continuous audiovisual prompts without forced muting", "approved titles and source attribution"],
            "execution": {"model_run": False, "network_access": False, "files_modified": False},
            "limits": "Checks preserve the reviewed translation bytes; they do not independently prove translation meaning or synthesized video/audio quality."}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, default=REPO_ROOT / "data" / "short_stories", help="Package directory (default: repo/data/short_stories)")
    parser.add_argument("--json", action="store_true", help="Emit a JSON report for CI")
    args = parser.parse_args(argv)
    try:
        report = verify(args.data_dir.resolve())
    except (VerificationError, KeyError, TypeError, ValueError) as exc:
        if args.json:
            print(json.dumps({"verified": False, "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"Short-story verification failed: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Verified {report['total_scenes']} scenes across three works; {report['locked_files_verified']} reviewed content files match their fixed hashes.")
        for work in report["works"]:
            print(f"  {work['slug']}: {work['scenes']} scenes, {work['source_characters']} original characters, max {work['longest_spoken_line_words']} spoken words")
        print("No model execution, network access or file modifications occurred.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
