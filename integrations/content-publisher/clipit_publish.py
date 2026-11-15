#!/usr/bin/env python3
"""Publish completed JSONL, optional Korean text and MP4s from Jupyter.

No model calls, administrator credentials, public ACLs or database access.
The script and video IAM sessions deliberately remain separate.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BUCKET = "clipit-videos-506318770879"
REGION = "ap-northeast-1"
DEFAULT_API = "https://cbnu-clip-it.vercel.app"
IDENTITIES = {
    "script": "arn:aws:iam::506318770879:user/clipit-script-uploader",
    "video": "arn:aws:iam::506318770879:user/clipit-video-uploader",
}
MAX_JSONL_BYTES = 10 * 1024 * 1024
CONFIG_KEYS = frozenset({"CLIPIT_API_BASE", "CONTENT_PUBLISH_TOKEN",
                         "CLIPIT_SCRIPT_ACCESS_KEY_ID", "CLIPIT_SCRIPT_SECRET_ACCESS_KEY",
                         "CLIPIT_VIDEO_ACCESS_KEY_ID", "CLIPIT_VIDEO_SECRET_ACCESS_KEY"})


class PublishError(RuntimeError):
    """Safe to display: messages never include keys, bearer tokens or signed URLs."""


def load_private_config(path=".env.content-publisher.json"):
    """Load only the six permitted settings into this process; never print values."""
    config_path = Path(path).expanduser()
    if not config_path.exists():
        return False
    if os.name == "posix" and config_path.stat().st_mode & 0o077:
        raise PublishError("Set the private configuration permissions to 0600 before loading it.")
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise PublishError("The private configuration must be a valid UTF-8 JSON object.") from None
    if not isinstance(config, dict) or set(config) != CONFIG_KEYS or any(
        not isinstance(value, str) or not value.strip() for value in config.values()
    ):
        raise PublishError("The private configuration must contain exactly the six documented non-empty settings.")
    os.environ.update(config)
    return True


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


def _rows(path):
    raw = Path(path).expanduser().read_bytes()
    if len(raw) > MAX_JSONL_BYTES:
        raise PublishError("Each JSONL file must be at most 10 MiB.")
    try:
        rows = [json.loads(line, parse_constant=lambda value: (_ for _ in ()).throw(ValueError()))
                for line in raw.decode("utf-8-sig").splitlines() if line.strip()]
    except (UnicodeError, ValueError):
        raise PublishError("Use UTF-8 JSONL with one valid JSON object per line.") from None
    if not 1 <= len(rows) <= 1000 or any(not isinstance(row, dict) for row in rows):
        raise PublishError("JSONL must contain 1 to 1000 scene objects.")
    return rows


def _position(row, *, korean=False):
    chapter = row.get("chapter", row.get("Chapter")) if korean else row.get("chapter")
    scene = row.get("scene_number", row.get("scene", row.get("Scene number"))) if korean else row.get("scene_number")
    if any(isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 100000
           for value in (chapter, scene)):
        raise PublishError("Every scene needs integer chapter and scene_number values from 1 to 100000.")
    return chapter, scene


def _file_digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_publication(scripts_path, videos_dir, *, slug, title, author, title_ko=None,
                        genre=None, korean_path=None, replace_videos=False, replace_translations=False):
    """Pure local validation; credentials and cloud calls are unnecessary here."""
    if not isinstance(slug, str) or len(slug) > 120 or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        raise PublishError("Use the web team's lowercase work slug with numbers and single hyphens.")
    for name, value, limit in (("title", title, 300), ("author", author, 300),
                               ("title_ko", title_ko, 300), ("genre", genre, 100)):
        if value is None and name in {"title_ko", "genre"}:
            continue
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise PublishError(f"{name} must be a non-empty string of at most {limit} characters.")
    if not isinstance(replace_videos, bool) or not isinstance(replace_translations, bool):
        raise PublishError("Replacement options must be explicit booleans.")
    rows = _rows(scripts_path)
    sources, script_rows, positions, identities = [], [], set(), set()
    for row in rows:
        position = _position(row)
        scene_id = row.get("scene_id")
        if isinstance(scene_id, bool) or not isinstance(scene_id, (str, int)) or (
            isinstance(scene_id, int) and not 0 < scene_id <= 9007199254740991
        ):
            raise PublishError("scene_id must be a non-empty string or positive safe integer.")
        scene_id = str(scene_id).strip()
        if not scene_id or len(scene_id) > 255 or scene_id in identities or position in positions:
            raise PublishError("Scene IDs and chapter/scene numbers must be non-empty and unique.")
        content, script = row.get("scene_text"), row.get("video_script")
        if not isinstance(content, str) or not content.strip() or len(content) > 100000:
            raise PublishError("Every scene needs unchanged, non-empty scene_text up to 100000 characters.")
        if not isinstance(script, dict) or set(script) != {"prompt"} or not isinstance(script["prompt"], str) or not script["prompt"].strip() or len(script["prompt"]) > 20000:
            raise PublishError("Every video_script must contain only a non-empty prompt up to 20000 characters.")
        if "<think>" in script["prompt"] or "</think>" in script["prompt"]:
            raise PublishError("Remove reasoning tags from the actual video prompt.")
        config = row.get("generation_config") or {}
        if not isinstance(config, dict):
            raise PublishError("generation_config, when supplied, must be an object.")
        if row.get("generation_status", "json_valid") != "json_valid" or row.get("generation_error") is not None or config.get("prompt_only") is True:
            raise PublishError("Preview and failed script rows cannot be published.")
        positions.add(position)
        identities.add(scene_id)
        sources.append({"scene_id": scene_id, "chapter": position[0], "scene_number": position[1], "scene_text": content})
        script_rows.append({**row, "scene_id": scene_id})
    if korean_path:
        translated_positions = set()
        by_position = {(_position(row)): row for row in sources}
        for row in _rows(korean_path):
            position = _position(row, korean=True)
            if position not in by_position or position in translated_positions:
                raise PublishError("Korean scenes must uniquely match a scene in the completed script file.")
            translated_positions.add(position)
            original = row.get("scene_text", row.get("content", row.get("Content")))
            if original is not None and original != by_position[position]["scene_text"]:
                raise PublishError("The Korean file's English text differs from the completed script scene.")
            translation = row.get("content_ko", row.get("Content_kor", row.get("scene_text_ko")))
            if translation is not None:
                if not isinstance(translation, str) or not translation.strip() or len(translation) > 100000:
                    raise PublishError("Each provided Korean translation must be non-empty text up to 100000 characters.")
                by_position[position]["content_ko"] = translation
    for row in sources:
        incoming = next(script for script in script_rows if script["scene_id"] == row["scene_id"])
        if "content_ko" not in row and incoming.get("content_ko") is not None:
            translation = incoming["content_ko"]
            if not isinstance(translation, str) or not translation.strip() or len(translation) > 100000:
                raise PublishError("content_ko must be non-empty Korean text or null.")
            row["content_ko"] = translation
    source_bytes = b"\n".join(_json_bytes(row) for row in sources) + b"\n"
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    for row in script_rows:
        row.update(generation_status="json_valid", generation_error=None,
                   generation_config={"input_sha256": source_sha, "prompt_only": False,
                                      "publication_method": "completed_video_handoff",
                                      "prior_generation_config": row.get("generation_config")})
    script_bytes = b"\n".join(_json_bytes(row) for row in script_rows) + b"\n"
    if max(len(source_bytes), len(script_bytes)) > MAX_JSONL_BYTES:
        raise PublishError("Normalized source/script JSONL exceeds the 10 MiB file limit.")
    batch = hashlib.sha256(source_bytes + b"\n" + script_bytes).hexdigest()
    videos, root = [], Path(videos_dir).expanduser().resolve(strict=True)
    for source in sources:
        chapter, scene = _position(source)
        path = root / f"{chapter}_{scene}.mp4"
        if not path.is_file():
            raise PublishError(f"Missing completed MP4: {chapter}_{scene}.mp4")
        stat = path.stat()
        if not 12 <= stat.st_size <= 5 * 1024**3:
            raise PublishError(f"MP4 must be complete and at most 5 GiB: {chapter}_{scene}.mp4")
        with path.open("rb") as stream:
            if stream.read(12)[4:8] != b"ftyp":
                raise PublishError(f"MP4 container header is missing: {chapter}_{scene}.mp4")
        digest = _file_digest(path)
        after = path.stat()
        if (stat.st_size, stat.st_mtime_ns, stat.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise PublishError("An MP4 changed during validation; finish encoding before publishing.")
        videos.append({"chapter": chapter, "scene_number": scene,
                       "storage_path": f"videos/{slug}/published/{chapter}_{scene}/video-{digest}.mp4",
                       "file_size_bytes": stat.st_size, "sha256": digest, "path": path,
                       "mtime_ns": stat.st_mtime_ns, "inode": stat.st_ino})
    body = {"slug": slug, "title": title.strip(), "author": author.strip(),
            "source_key": f"originals/{slug}/{batch}.jsonl", "script_key": f"scripts/{slug}/{batch}.jsonl",
            "replace_videos": replace_videos, "replace_translations": replace_translations,
            "videos": [{key: video[key] for key in ("chapter", "scene_number", "storage_path", "file_size_bytes")} for video in videos]}
    if title_ko is not None:
        body["title_ko"] = title_ko.strip()
    if genre is not None:
        body["genre"] = genre.strip()
    return {"body": body, "source_bytes": source_bytes, "script_bytes": script_bytes,
            "videos": videos, "translated_scenes": sum("content_ko" in row for row in sources)}


def dedicated_session(access_key_id, secret_access_key, *, role):
    """Two separate exact-IAM checks; never silently use administrator/default keys."""
    import boto3
    from botocore.config import Config

    if role not in IDENTITIES or not access_key_id.strip() or not secret_access_key.strip():
        raise PublishError("Provide the dedicated script or video IAM credentials.")
    session = boto3.Session(aws_access_key_id=access_key_id.strip(),
                            aws_secret_access_key=secret_access_key.strip(), region_name=REGION)
    config = Config(connect_timeout=10, read_timeout=120, retries={"mode": "standard", "max_attempts": 4})
    try:
        arn = session.client("sts", config=config).get_caller_identity().get("Arn")
    except Exception:
        raise PublishError("Could not verify the dedicated AWS identity; check the supplied keys and HTTPS connection.") from None
    if arn != IDENTITIES[role]:
        raise PublishError(f"Use only the dedicated {role} uploader identity; administrator/root keys are refused.")
    return session


def _put(client, key, body, *, content_type, size, digest):
    try:
        client.put_object(Bucket=BUCKET, Key=key, Body=body, ContentType=content_type,
                          ContentLength=size, ServerSideEncryption="AES256", IfNoneMatch="*",
                          ChecksumSHA256=base64.b64encode(bytes.fromhex(digest)).decode("ascii"))
    except Exception as exc:
        response = getattr(exc, "response", {})
        if response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 412:
            return
        raise PublishError("S3 upload failed; check the dedicated identity, allowed path and HTTPS connection.") from None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _publish_request(base_url, token, body, *, allow_local_http=False):
    base = base_url.rstrip("/")
    parsed = urllib.parse.urlsplit(base)
    local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if (parsed.scheme != "https" and not (allow_local_http and local and parsed.scheme == "http")) or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:
        raise PublishError("Use the CLIP-IT HTTPS origin without a path, query or embedded credentials.")
    if not isinstance(token, str) or len(token) < 24 or any(char.isspace() for char in token):
        raise PublishError("A dedicated CONTENT_PUBLISH_TOKEN of at least 24 characters is required.")
    request = urllib.request.Request(base + "/api/integrations/publications", data=_json_bytes(body), method="POST",
                                     headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=60) as response:
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise PublishError("The publish response was too large.")
            result = json.loads(raw)
            if not isinstance(result, dict) or result.get("ok") is not True or result.get("registered_in_web") is not True:
                raise PublishError("The website did not confirm publication; retry the same unchanged files.")
            return result
    except urllib.error.HTTPError as exc:
        status, code = exc.code, "PUBLICATION_FAILED"
        try:
            data = json.loads(exc.read(4096))
            if isinstance(data, dict) and re.fullmatch(r"[A-Z_]{1,80}", str(data.get("code", ""))):
                code = data["code"]
        except (ValueError, OSError):
            pass
        finally:
            exc.close()
        raise PublishError(f"Website publication returned HTTP {status} ({code}); inspect the documented retry/conflict steps.") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise PublishError("Website connection failed; stored immutable files can be retried without regenerating videos.") from None
    except (ValueError, UnicodeError):
        raise PublishError("Website returned invalid publication JSON.") from None


def publish_completed(scripts_path, videos_dir, *, script_session, video_session,
                      publish_token, api_base=DEFAULT_API, **options):
    """Upload all immutable objects, then atomically register the completed work."""
    prepared = prepare_publication(scripts_path, videos_dir, **options)
    # Validate origin/token before sending files. This request is not made until all PUTs finish.
    parsed = urllib.parse.urlsplit(api_base.rstrip("/"))
    if parsed.scheme != "https" or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise PublishError("Use the CLIP-IT HTTPS origin without a path, query or credentials.")
    if not isinstance(publish_token, str) or len(publish_token) < 24 or any(char.isspace() for char in publish_token):
        raise PublishError("A dedicated CONTENT_PUBLISH_TOKEN of at least 24 characters is required.")
    for role, session in (("script", script_session), ("video", video_session)):
        try:
            arn = session.client("sts").get_caller_identity().get("Arn")
        except Exception:
            raise PublishError("Could not verify the dedicated AWS identity; no objects were uploaded.") from None
        if arn != IDENTITIES[role]:
            raise PublishError(f"Use only the dedicated {role} uploader identity; no objects were uploaded.")
    script_client, video_client = script_session.client("s3"), video_session.client("s3")
    for name in ("source", "script"):
        raw = prepared[f"{name}_bytes"]
        _put(script_client, prepared["body"][f"{name}_key"], raw,
             content_type="application/x-ndjson; charset=utf-8", size=len(raw), digest=hashlib.sha256(raw).hexdigest())
    for video in prepared["videos"]:
        stat = video["path"].stat()
        if (stat.st_size, stat.st_mtime_ns, stat.st_ino) != (video["file_size_bytes"], video["mtime_ns"], video["inode"]):
            raise PublishError("An MP4 changed after validation; finish encoding and retry unchanged files.")
        with video["path"].open("rb") as stream:
            _put(video_client, video["storage_path"], stream, content_type="video/mp4",
                 size=video["file_size_bytes"], digest=video["sha256"])
        after = video["path"].stat()
        if (after.st_size, after.st_mtime_ns, after.st_ino) != (stat.st_size, stat.st_mtime_ns, stat.st_ino):
            raise PublishError("An MP4 changed during upload; no website publication was requested.")
    return _publish_request(api_base, publish_token, prepared["body"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scripts", required=True)
    parser.add_argument("--videos", required=True)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--author", required=True)
    parser.add_argument("--title-ko")
    parser.add_argument("--genre")
    parser.add_argument("--korean")
    args = parser.parse_args()
    result = prepare_publication(args.scripts, args.videos, slug=args.slug, title=args.title,
                                 author=args.author, title_ko=args.title_ko, genre=args.genre, korean_path=args.korean)
    print(json.dumps({"validated": True, "scene_count": len(result["videos"]),
                      "translated_scenes": result["translated_scenes"], "cloud_calls": 0}))
