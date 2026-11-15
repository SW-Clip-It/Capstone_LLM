"""Fast standard-library checks; never import or execute a model runtime."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "mk_script_video.py"
SPEC = importlib.util.spec_from_file_location("ltx2_script_generator", SCRIPT)
generator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generator)


class PromptTests(unittest.TestCase):
    def setUp(self):
        self.row = {
            "scene_id": "magi-001-029",
            "chapter": 1,
            "scene_number": 29,
            "scene_text": 'Jim said, "I sold the watch to get the money to buy your combs."',
            "characters": ["Jim", "Della"],
            "mood": ["tender"],
            "important_nodes": [],
        }

    def prompt_text(self, **kwargs):
        return "\n".join(message["content"] for message in
                         generator.build_video_script_prompt(self.row, **kwargs))

    def test_source_speech_voice_and_timing_rules(self):
        prompt = self.prompt_text(clip_seconds=8)
        self.assertIn(self.row["scene_text"], prompt)
        for rule in ("exact English quotation", "double quotation marks",
                     "ONE speaking character", "vocal timbre", "synchronized mouth movement",
                     "no more than 20 spoken English words", "2.5 words per second",
                     "only when essential", "environmental sound alone"):
            self.assertIn(rule, prompt)

    def test_configured_style_replaces_old_forced_defaults(self):
        prompt = self.prompt_text(work_title="The Selfish Giant",
                                  visual_style="Painterly European fairy tale",
                                  clip_seconds=12)
        self.assertIn('"work_title": "The Selfish Giant"', prompt)
        self.assertIn('"visual_style": "Painterly European fairy tale"', prompt)
        self.assertIn("no more than 30 spoken English words", prompt)
        self.assertIn("4 to 8", prompt)
        self.assertIn("metaphor or hypothetical comparison", prompt)
        self.assertIn("readable text", prompt)
        for obsolete in ("silent text-to-video", "Create a silent", "No dialogue",
                         "Do not include dialogue", "exactly 3 sentences",
                         "dark Victorian detective"):
            self.assertNotIn(obsolete, prompt)

    def test_legacy_helper_arguments_and_graph_ablation(self):
        messages = generator.build_video_script_prompt(self.row, False)
        self.assertEqual([item["role"] for item in messages], ["system", "user"])
        prompt = "\n".join(item["content"] for item in messages)
        self.assertNotIn("Previously retrieved graph context", prompt)
        self.assertIn(self.row["scene_text"], prompt)
        self.assertIn("no more than 20 spoken English words", prompt)

    def test_legacy_make_result_prompt_only_without_new_attributes(self):
        legacy_args = SimpleNamespace(no_graph_context=False, save_prompts=False,
                                      prompt_only=True)
        result = generator.make_result(self.row, 1, legacy_args, {"prompt_only": True})
        for key, value in self.row.items():
            self.assertEqual(result[key], value)
        self.assertIsNone(result["video_script"])
        self.assertEqual(result["generation_status"], "retrieval_only")
        self.assertIn("generation_messages", result)
        self.assertEqual(result["semantic_validation"], "not_performed")

    def test_legacy_cli_prompt_only_skips_runtime_and_preserves_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.jsonl"
            target = Path(directory) / "preview.jsonl"
            source.write_text(json.dumps(self.row) + "\n", encoding="utf-8")
            argv = [str(SCRIPT), "--input", str(source), "--output", str(target),
                    "--prompt-only", "--limit", "1"]
            # Any eager model construction makes this regression test fail.
            with patch.object(sys, "argv", argv), \
                    patch.object(generator, "VideoGenerator", side_effect=AssertionError("model loaded")), \
                    contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(generator.main(), 0)
            result = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(result["scene_text"], self.row["scene_text"])
            self.assertEqual(result["generation_status"], "retrieval_only")
            self.assertEqual(result["generation_config"]["max_new_tokens"], 480)
            self.assertEqual(result["generation_config"]["max_input_tokens"], 8192)
            self.assertEqual(result["generation_config"]["clip_seconds"], 8)
            self.assertIsNone(result["video_script"])

    def test_invalid_duration_is_rejected_before_runtime(self):
        for duration in (0, -1, float("inf"), float("nan")):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                self.prompt_text(clip_seconds=duration)


if __name__ == "__main__":
    unittest.main()
