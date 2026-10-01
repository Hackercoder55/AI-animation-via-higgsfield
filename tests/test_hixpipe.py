import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import hixpipe as hp  # noqa: E402

DEMO = hp.ROOT / "projects" / "passport-rush-demo"


def demo_project() -> dict:
    return hp.load(DEMO)


class PromptTests(unittest.TestCase):
    def test_five_blocks_in_order(self):
        proj = demo_project()
        text = hp.build_shot_prompt(proj, hp.find_shot(proj, "S03"))
        heads = ["SCENE CONTEXT & STYLE", "ACTIVE REFERENCES", "SHOT STRUCTURE",
                 "LOCKS & CONSTRAINTS", "ANIMATION PRINCIPLES"]
        idx = [text.index(h) for h in heads]
        self.assertEqual(idx, sorted(idx))
        self.assertTrue(text.startswith("SCENE CONTEXT & STYLE\nOn the highway"))
        self.assertIn("@previs", text)
        self.assertIn("No music. SFX and ambience only.", text)
        self.assertIn("100% match the reference", text)

    def test_element_id_is_embedded_and_not_sent_as_media(self):
        proj = demo_project()
        proj["assets"]["maya"]["element_id"] = "11111111-1111-4111-8111-111111111111"
        proj["assets"]["taxi"]["media_id"] = "media-taxi"
        shot = hp.find_shot(proj, "S02")
        shot["keyframe_media_id"] = "media-key"
        prompt = hp.build_shot_prompt(proj, shot)
        self.assertIn("<<<11111111-1111-4111-8111-111111111111>>>", prompt)
        params = hp.mcp_params(hp.build_request(proj, shot, prompt))
        self.assertEqual(params["mode"], "omni_reference")
        self.assertEqual(params["medias"], [
            {"value": "media-taxi", "role": "image_references"},
            {"value": "media-key", "role": "start_image"},
        ])

    def test_previs_video_reference(self):
        proj = demo_project()
        shot = hp.find_shot(proj, "S03")
        shot["previs_media_id"] = "media-previs"
        params = hp.build_request(proj, shot, "x")
        self.assertIn({"value": "media-previs", "role": "video_references", "_label": "@previs"}, params["medias"])
        self.assertEqual(params["duration"], 4)

    def test_t2v_mode_without_refs(self):
        proj = demo_project()
        params = hp.build_request(proj, hp.find_shot(proj, "S01"), "plain prompt")
        self.assertEqual(params["mode"], "t2v")
        self.assertNotIn("medias", params)

    def test_asset_prompts_render_for_every_type(self):
        proj = demo_project()
        for aid in proj["assets"]:
            text = hp.build_asset_prompt(proj, aid)
            self.assertNotIn("{", text)
        self.assertIn("watercolor", hp.build_asset_prompt(proj, "trucks"))
        self.assertIn("turnaround", hp.build_asset_prompt(proj, "maya"))


class ValidationTests(unittest.TestCase):
    def test_demo_has_no_errors(self):
        errors, _ = hp.validate(demo_project(), DEMO)
        self.assertEqual(errors, [])

    def test_catches_bad_shots(self):
        proj = demo_project()
        proj["shots"].append({"id": "S01", "route": "dance", "duration": 60, "assets": ["ghost"], "beats": []})
        errors, _ = hp.validate(proj, DEMO)
        joined = "\n".join(errors)
        for needle in ("duplicate id", "route must be", "outside seedance_2_5", "unknown asset", "at least one beat"):
            self.assertIn(needle, joined)

    def test_locked_asset_needs_reference(self):
        proj = demo_project()
        proj["assets"]["maya"]["locked"] = True
        errors, _ = hp.validate(proj, DEMO)
        self.assertTrue(any("locked but has no" in e for e in errors))


class FrameSizeTests(unittest.TestCase):
    def test_sizes(self):
        self.assertEqual(hp.frame_size("16:9", "1080p"), (1920, 1080))
        self.assertEqual(hp.frame_size("9:16", "720p"), (720, 1280))
        self.assertEqual(hp.frame_size("1:1", "1080p"), (1080, 1080))
        self.assertEqual(hp.frame_size("21:9", "1080p"), (2520, 1080))


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
class AssembleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.pdir = self.tmp / "proj"
        shutil.copytree(DEMO, self.pdir)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def make_clip(self, name, size, dur, audio):
        out = self.tmp / name
        cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=s={size}:r=30:d={dur}"]
        if audio:
            cmd += ["-f", "lavfi", "-i", f"sine=f=440:d={dur}", "-shortest"]
        cmd += ["-pix_fmt", "yuv420p", str(out)]
        subprocess.run(cmd, check=True)
        return out

    def test_take_flow_and_assemble(self):
        a = self.make_clip("a.mp4", "1280x720", 5, audio=True)
        b = self.make_clip("b.mp4", "720x1280", 5, audio=False)  # wrong aspect, silent
        p = str(self.pdir)
        hp.main(["take", "add", p, "S01", "--file", str(a)])
        hp.main(["take", "add", p, "S02", "--file", str(b)])
        hp.main(["take", "approve", p, "S01", "--n", "1"])
        hp.main(["take", "approve", p, "S02", "--n", "1", "--in", "0.5", "--out", "4"])
        with self.assertRaises(SystemExit):  # S03 still missing
            hp.main(["assemble", p, "--resolution", "480p"])
        out = self.tmp / "film.mp4"
        hp.main(["assemble", p, "--resolution", "480p", "--placeholders", "--out", str(out)])
        info = hp.ffprobe_json(out)
        v = next(s for s in info["streams"] if s["codec_type"] == "video")
        self.assertEqual((v["width"], v["height"]), (854, 480))
        self.assertTrue(any(s["codec_type"] == "audio" for s in info["streams"]))
        self.assertAlmostEqual(float(info["format"]["duration"]), 5 + 3.5 + 4, delta=0.3)
        proj = json.loads((self.pdir / "project.json").read_text())
        self.assertEqual(hp.find_shot(proj, "S02")["trim_in"], 0.5)


if __name__ == "__main__":
    unittest.main()
