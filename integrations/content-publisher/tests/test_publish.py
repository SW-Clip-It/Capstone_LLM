import hashlib
import importlib.util
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("clipit_publish", Path(__file__).resolve().parents[1] / "clipit_publish.py")
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


class AlreadyStored(Exception):
    response = {"ResponseMetadata": {"HTTPStatusCode": 412}}


class FakeSession:
    def __init__(self, role):
        self.role, self.objects, self.calls = role, {}, []
        self.raise_upload = None

    def client(self, service):
        if service not in {"sts", "s3"}:
            raise AssertionError(service)
        return self

    def get_caller_identity(self):
        return {"Arn": publisher.IDENTITIES.get(self.role, "arn:aws:iam::123:user/admin")}

    def put_object(self, **kwargs):
        self.calls.append(kwargs)
        if self.raise_upload:
            raise self.raise_upload
        value = kwargs["Body"]
        self.objects[kwargs["Key"]] = value if isinstance(value, bytes) else value.read()


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.scripts = self.root / "scripts.jsonl"
        self.korean = self.root / "korean.jsonl"
        self.video = self.root / "1_1.mp4"
        self.video.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"complete-video")
        self.row = {"scene_id": "1_1", "chapter": 1, "scene_number": 1,
                    "scene_text": "Unchanged English source.\n",
                    "video_script": {"prompt": "Della softly speaks her original line while holding the chain."}}
        self.write_rows([self.row])
        self.options = dict(slug="book", title="Book", author="Author", title_ko="책")

    def tearDown(self):
        self.temp.cleanup()

    def write_rows(self, rows):
        self.scripts.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")

    def prepare(self, **extra):
        return publisher.prepare_publication(self.scripts, self.root, **self.options, **extra)

    def publish(self, script=None, video=None, **extra):
        return publisher.publish_completed(self.scripts, self.root,
                                           script_session=script or FakeSession("script"),
                                           video_session=video or FakeSession("video"),
                                           publish_token="dedicated-publish-token-long-enough", **self.options, **extra)

    def test_five_fields_preserve_source_prompt_and_optional_korean(self):
        self.korean.write_text(json.dumps({"Chapter": 1, "Scene number": 1,
                                          "Content": self.row["scene_text"], "Content_kor": "바꾸지 않은 한국어 원문 번역."}, ensure_ascii=False) + "\n")
        result = self.prepare(korean_path=self.korean)
        source = json.loads(result["source_bytes"].splitlines()[0])
        script = json.loads(result["script_bytes"].splitlines()[0])
        self.assertEqual(source["scene_text"], self.row["scene_text"])
        self.assertEqual(source["content_ko"], "바꾸지 않은 한국어 원문 번역.")
        self.assertEqual(script["video_script"], self.row["video_script"])
        self.assertEqual(script["generation_config"]["input_sha256"], hashlib.sha256(result["source_bytes"]).hexdigest())
        self.assertEqual(result["translated_scenes"], 1)
        self.assertIn("videos/book/published/1_1/", result["videos"][0]["storage_path"])

    def test_retries_have_identical_immutable_keys(self):
        one, two = self.prepare(), self.prepare()
        self.assertEqual(one["body"], two["body"])
        self.assertEqual(one["source_bytes"], two["source_bytes"])
        self.assertEqual(one["script_bytes"], two["script_bytes"])

    def test_mismatched_english_in_korean_file_is_rejected(self):
        self.korean.write_text(json.dumps({"Chapter": 1, "Scene number": 1, "Content": "Different text", "Content_kor": "번역"}) + "\n")
        with self.assertRaises(publisher.PublishError):
            self.prepare(korean_path=self.korean)

    def test_duplicate_preview_invalid_file_and_missing_video_are_rejected(self):
        self.write_rows([self.row, self.row])
        with self.assertRaises(publisher.PublishError):
            self.prepare()
        self.write_rows([{**self.row, "generation_status": "retrieval_only"}])
        with self.assertRaises(publisher.PublishError):
            self.prepare()
        self.write_rows([self.row])
        self.video.write_bytes(b"not-a-completed-mp4")
        with self.assertRaises(publisher.PublishError):
            self.prepare()
        self.video.unlink()
        with self.assertRaises(publisher.PublishError):
            self.prepare()

    def test_puts_use_separate_identities_before_the_one_publication_request(self):
        scripts, videos = FakeSession("script"), FakeSession("video")
        def confirm(base, token, body):
            self.assertEqual(len(scripts.objects), 2)
            self.assertEqual(len(videos.objects), 1)
            self.assertEqual(body["videos"][0]["file_size_bytes"], self.video.stat().st_size)
            return {"ok": True, "registered_in_web": True, "registered_scenes": 1}
        with patch.object(publisher, "_publish_request", side_effect=confirm) as api:
            self.assertTrue(self.publish(scripts, videos)["registered_in_web"])
        api.assert_called_once()
        self.assertTrue(all(key.startswith(("originals/", "scripts/")) for key in scripts.objects))
        self.assertTrue(all(key.startswith("videos/book/published/") for key in videos.objects))
        for call in scripts.calls + videos.calls:
            self.assertEqual(call["IfNoneMatch"], "*")
            self.assertEqual(call["ServerSideEncryption"], "AES256")
            self.assertIn("ChecksumSHA256", call)

    def test_immutable_precondition_retries_succeed_without_read_permission(self):
        scripts, videos = FakeSession("script"), FakeSession("video")
        scripts.raise_upload = AlreadyStored()
        videos.raise_upload = AlreadyStored()
        with patch.object(publisher, "_publish_request", return_value={"ok": True, "registered_in_web": True}) as api:
            self.publish(scripts, videos)
        api.assert_called_once()

    def test_wrong_identity_or_failed_put_never_publishes(self):
        for script_session, video_session in [(FakeSession("admin"), FakeSession("video")),
                                               (FakeSession("script"), FakeSession("script"))]:
            with patch.object(publisher, "_publish_request") as api, self.assertRaises(publisher.PublishError):
                self.publish(script_session, video_session)
            api.assert_not_called()
            self.assertEqual(script_session.calls + video_session.calls, [])
        videos = FakeSession("video")
        videos.raise_upload = RuntimeError("secret must never escape")
        with patch.object(publisher, "_publish_request") as api, self.assertRaises(publisher.PublishError) as error:
            self.publish(video=videos)
        api.assert_not_called()
        self.assertNotIn("secret must never escape", str(error.exception))

    def test_modified_video_during_upload_does_not_register(self):
        videos = FakeSession("video")
        put = videos.put_object
        def modify(**kwargs):
            put(**kwargs)
            self.video.write_bytes(self.video.read_bytes() + b"modified")
        videos.put_object = modify
        with patch.object(publisher, "_publish_request") as api, self.assertRaises(publisher.PublishError):
            self.publish(video=videos)
        api.assert_not_called()

    def test_private_config_accepts_only_the_six_keys_without_printing(self):
        config = self.root / ".env.content-publisher.json"
        values = {key: "dummy-private-value" for key in publisher.CONFIG_KEYS}
        config.write_text(json.dumps(values))
        config.chmod(0o600)
        with patch.dict(publisher.os.environ, {}, clear=False):
            self.assertTrue(publisher.load_private_config(config))
            self.assertEqual(publisher.os.environ["CONTENT_PUBLISH_TOKEN"], "dummy-private-value")
        config.write_text(json.dumps({**values, "ADMIN_API_KEY": "must-be-rejected"}))
        with self.assertRaises(publisher.PublishError):
            publisher.load_private_config(config)
        config.write_text(json.dumps(values))
        config.chmod(0o644)
        if publisher.os.name == "posix":
            with self.assertRaises(publisher.PublishError):
                publisher.load_private_config(config)
        self.assertFalse(publisher.load_private_config(self.root / "missing.json"))

    def test_http_error_does_not_disclose_raw_response(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(409)
                self.end_headers()
                self.wfile.write(b'{"code":"PUBLICATION_SOURCE_CONFLICT","error":"private error body"}')
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.assertRaises(publisher.PublishError) as error:
                publisher._publish_request(f"http://127.0.0.1:{server.server_port}", "valid-publish-token-very-long", {}, allow_local_http=True)
            self.assertIn("PUBLICATION_SOURCE_CONFLICT", str(error.exception))
            self.assertNotIn("private error body", str(error.exception))
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_bearer_request_does_not_follow_an_http_redirect(self):
        hits = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                hits.append(self.path)
                self.send_response(307)
                self.send_header("Location", "/must-not-be-followed")
                self.end_headers()
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.assertRaises(publisher.PublishError):
                publisher._publish_request(f"http://127.0.0.1:{server.server_port}", "valid-publish-token-very-long", {}, allow_local_http=True)
            self.assertEqual(hits, ["/api/integrations/publications"])
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
