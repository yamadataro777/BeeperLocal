"""Release gates must fail closed without modifying real app signatures."""
import importlib.util
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("macos_signing", Path(__file__).resolve().parents[1] / "scripts/macos_signing.py")
signing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signing)

CERT = "A" * 40
TEAM = "ABC1234567"


class SigningTests(unittest.TestCase):
    def test_release_without_identity_fails_before_any_native_command(self):
        with patch.dict("os.environ", {}, clear=True), patch.object(signing, "run") as run:
            with self.assertRaisesRegex(signing.SigningError, "DEVELOPER_ID_REQUIRED"):
                signing.identity("release")
            run.assert_not_called()

    def test_release_requires_matching_apple_distribution_identity_and_team(self):
        env = {"BEEPERLOCAL_SIGN_IDENTITY": CERT, "BEEPERLOCAL_TEAM_ID": TEAM}
        with patch.dict("os.environ", env, clear=True), patch.object(signing, "run") as run:
            for description in ["Apple Development: Fixture (ABC1234567)",
                                "Developer ID Application: Fixture (OTHER12345)"]:
                run.return_value = f'1) {CERT} "{description}"'
                with self.assertRaisesRegex(signing.SigningError, "NOT_AVAILABLE"):
                    signing.identity("release")
            run.return_value = f'1) {CERT} "Developer ID Application: Fixture ({TEAM})"'
            self.assertEqual(signing.identity("release"), (CERT, TEAM))

    def test_development_never_uses_an_ambient_private_signing_identity(self):
        with patch.dict("os.environ", {"BEEPERLOCAL_SIGN_IDENTITY": CERT}), patch.object(signing, "run") as run:
            self.assertEqual(signing.identity("development"), ("-", None))
            run.assert_not_called()

    def test_release_rejects_adhoc_wrong_team_missing_runtime_or_timestamp(self):
        valid = (f"Identifier={signing.APP_ID}\nTeamIdentifier={TEAM}\nAuthority=Developer ID Application: Fixture\n"
                 "CodeDirectory flags=0x10000(runtime)\nTimestamp=fixture\ndesignated => identifier fixture\n")
        for invalid in [valid.replace(TEAM, "WRONG12345"), valid.replace("(runtime)", ""),
                        valid.replace("Timestamp=fixture", "Signed Time=fixture"),
                        valid.replace("identifier fixture", 'cdhash H"0000"'),
                        valid.replace("Authority=Developer ID Application: Fixture", "Signature=adhoc")]:
            with self.subTest(signature=invalid), patch.object(signing, "run", return_value=invalid):
                with self.assertRaises(signing.SigningError):
                    signing.inspect_signature("fixture", "release", TEAM, signing.APP_ID)

    def test_helper_is_signed_before_app_with_fixed_identifiers(self):
        paths = [(Path("app/Contents/MacOS/core"), signing.APP_ID + ".core"),
                 (Path("app/Contents/MacOS/line"), signing.APP_ID + ".line")]
        with patch.object(signing, "bundle_paths", return_value=(Path("app"), paths)), \
             patch.object(signing, "run") as run, patch.object(signing, "verify", return_value={}):
            signing.sign("app", "release", CERT, TEAM)
            self.assertEqual([call.args[-1] for call in run.call_args_list], [str(p) for p, _ in paths] + ["app"])
            for call in run.call_args_list:
                self.assertIn("--timestamp", call.args)
                self.assertIn("runtime", call.args)
                self.assertNotIn("--deep", call.args)
                self.assertNotIn("--requirements", call.args)

    def test_apple_anchor_is_passed_as_inline_requirement_not_filename(self):
        valid = (f"Identifier={signing.APP_ID}\nTeamIdentifier={TEAM}\nAuthority=Developer ID Application: Fixture\n"
                 "CodeDirectory flags=0x10000(runtime)\nTimestamp=fixture\ndesignated => identifier fixture\n")
        with patch.object(signing, "run", return_value=valid) as run:
            signing.inspect_signature("fixture", "release", TEAM, signing.APP_ID)
            self.assertIn(("/usr/bin/codesign", "--verify", "--strict", "-R", "=anchor apple generic", "fixture"),
                          [call.args for call in run.call_args_list])

    def test_bundle_rejects_untracked_helpers_and_includes_instagram(self):
        with tempfile.TemporaryDirectory() as folder:
            app = Path(folder) / "Fixture.app"
            binaries = app / "Contents/MacOS"
            binaries.mkdir(parents=True)
            (app / "Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": signing.APP_ID,
                                                                      "CFBundleExecutable": "main"}))
            for name in ["main", *signing.HELPERS, "beeperlocal-ig"]:
                (binaries / name).touch()
            _, helpers = signing.bundle_paths(app)
            self.assertEqual(len(helpers), 3)
            self.assertEqual(helpers[-1][1], signing.APP_ID + ".instagram")
            (binaries / "untracked").touch()
            with self.assertRaisesRegex(signing.SigningError, "UNRECOGNIZED"):
                signing.bundle_paths(app)
