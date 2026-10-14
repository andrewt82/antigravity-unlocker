"""Automatic-mode integration tests. No real apps, sudo, codesign or processes touched."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AutomaticModeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.bin = self.home / "bin"
        self.bin.mkdir()
        self.log = self.home / "actions"
        self.cli = self.home / ".local/bin/agy"
        self.cli.parent.mkdir(parents=True)
        self.cli.write_text("inexigible")
        self.cli.chmod(0o755)
        self.app = self.home / "Antigravity Test.app"
        self.server = self.app / "Contents/Resources/bin/language_server"
        self.server.parent.mkdir(parents=True)
        self.server.write_text("inexigible")
        self.server.chmod(0o755)
        self.mock("file", 'echo "Mach-O 64-bit executable arm64"')
        self.mock("codesign", '''
if [ "$1" = --verify ]; then
  for target in "$@"; do :; done
  [ ! -f "$target.unsigned" ]
else
  printf 'sign %s\n' "$*" >> "$TEST_LOG"
  [ -z "$TEST_SIGN_FAIL" ] || exit 1
  for target in "$@"; do :; done
  rm -f "$target.unsigned"
fi''')
        self.mock("ps", 'printf "%s\\n" "$TEST_PROCESSES"')
        self.mock("xattr", 'printf "xattr\\n" >> "$TEST_LOG"')
        self.mock("sudo", 'printf "sudo\\n" >> "$TEST_LOG"; exit 1')
        self.mock("pkill", 'printf "pkill\\n" >> "$TEST_LOG"; exit 99')
        self.env = dict(os.environ, HOME=str(self.home), AG_NO_ELEVATE="1",
                        PATH=f"{self.bin}:/usr/bin:/bin:/usr/sbin:/sbin",
                        TEST_LOG=str(self.log), TEST_PROCESSES="", TEST_SIGN_FAIL="")
        # The test shell runs without sudo; isolate the fixed per-user lock.
        self.env["SUDO_UID"] = f"test-{os.getpid()}-{self.home.name}"

    def mock(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/bash\n" + body + "\n")
        path.chmod(0o755)

    def run_mode(self, mode, expected=0):
        result = subprocess.run(
            ["/bin/bash", str(ROOT / "macos/ag_unlocker_mac.sh"), mode,
             "--cli-path", str(self.cli), "--app", str(self.app)],
            env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, expected, result.stderr)
        self.assertEqual(result.stdout, "")
        return result

    def test_ready_is_read_only_and_allows_active_sessions(self):
        self.env["TEST_PROCESSES"] = f"42 {self.cli}\n43 {self.app}/Contents/MacOS/Antigravity"
        self.run_mode("--check")
        self.run_mode("--ensure-patched")
        self.assertFalse(self.log.exists())

    def test_patches_only_changed_binary_and_bundle(self):
        self.server.write_text("ineligible inexigible")
        self.run_mode("--check", 10)
        self.run_mode("--ensure-patched")
        self.assertEqual(self.server.read_text(), "inexigible inexigible")
        actions = self.log.read_text()
        self.assertIn(str(self.server), actions)
        self.assertIn(str(self.app), actions)
        self.assertNotIn(str(self.cli), actions)
        self.run_mode("--check")
        self.run_mode("--ensure-patched")
        self.assertEqual(self.log.read_text(), actions)

    def test_unsigned_cli_is_repaired(self):
        Path(str(self.cli) + ".unsigned").touch()
        self.run_mode("--check", 10)
        self.run_mode("--ensure-patched")
        self.assertNotIn(str(self.app), self.log.read_text())

    def test_active_cli_or_app_blocks_changes(self):
        self.cli.write_text("ineligible")
        for executable in (self.cli, self.app / "Contents/MacOS/Antigravity"):
            self.env["TEST_PROCESSES"] = f"42 {executable}"
            self.run_mode("--ensure-patched", 1)
            self.assertEqual(self.cli.read_text(), "ineligible")
            self.assertFalse(self.log.exists())

    def test_unrelated_process_does_not_block(self):
        self.cli.write_text("ineligible")
        self.env["TEST_PROCESSES"] = "42 /some/other/agy"
        self.run_mode("--ensure-patched")
        self.assertNotIn("pkill", self.log.read_text())

    def test_unknown_build_and_missing_server_fail_without_writes(self):
        self.cli.write_text("unknown build")
        self.run_mode("--check", 1)
        self.run_mode("--ensure-patched", 1)
        self.assertFalse(self.log.exists())
        self.cli.write_text("inexigible")
        self.server.unlink()
        self.run_mode("--check", 1)

    def test_signing_failure_prevents_success_and_releases_lock(self):
        self.cli.write_text("ineligible")
        self.env["TEST_SIGN_FAIL"] = "1"
        self.run_mode("--ensure-patched", 1)
        self.env["TEST_SIGN_FAIL"] = ""
        self.run_mode("--ensure-patched")

    def test_existing_lock_blocks_patch(self):
        self.cli.write_text("ineligible")
        lock = Path(f"/private/tmp/ag-unlocker-{self.env['SUDO_UID']}.lock")
        lock.mkdir()
        self.addCleanup(lock.rmdir)
        self.run_mode("--ensure-patched", 1)
        self.assertEqual(self.cli.read_text(), "ineligible")
        self.assertFalse(self.log.exists())

    def test_ide_markers_and_unknown_signature(self):
        main = self.app / "Contents/Resources/app/out/main.js"
        main.parent.mkdir(parents=True)
        main.write_text("// UNLOCKED\n")
        self.run_mode("--check")
        main.write_text("unknown auth function\n")
        self.run_mode("--check", 1)
        self.assertFalse(self.log.exists())

    def test_ide_js_patch_and_backups(self):
        main = self.app / "Contents/Resources/app/out/main.js"
        ext = self.app / "Contents/Resources/app/extensions/antigravity/dist/extension.js"
        main.parent.mkdir(parents=True)
        ext.parent.mkdir(parents=True)
        original_main = ('class X{async signIn(t){if(this.sender.send({type:t.isGcpTos?'
                         '"GCP_SIGN_IN":"SIGN_IN"}),this.state.resetIsTierGCPTos(),'
                         'this.a.isGoogleInternal){try{await this.loader.loadCodeAssist(t);'
                         'const{settings:s,userTier:u}=await this.refreshUserStatus(t),i=fun(t);'
                         'this.pub.pushUpdate(i),this.sender.send({type:"AUTH_SUCCESS",tokenInfo:t}),'
                         'this.event.fire({settings:s,userTier:u})}catch(e){}return}return;}}\n')
        original_ext = ('async function test(){const t=await ns.UserStatus.getUserStatus();'
                        'if(!t)return[];const n=(0,parse)(t,dz),{email:e,name:nm}=n;'
                        'return""===e?[]:[n];}\n')
        main.write_text(original_main)
        ext.write_text(original_ext)
        self.run_mode("--check", 10)
        self.run_mode("--ensure-patched")
        self.assertEqual(Path(str(main) + ".ag_backup").read_text(), original_main)
        self.assertEqual(Path(str(ext) + ".ag_backup").read_text(), original_ext)
        self.assertIn("// UNLOCKED", main.read_text())
        self.assertIn("/*[AG_EXT_PATCHED]*/", ext.read_text())
        self.run_mode("--check")
        # Validate generated JavaScript with real Node when available.
        import shutil
        node = shutil.which("node")
        if node:
            for target in (main, ext):
                result = subprocess.run([node, "--check", str(target)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_sudo_refusal_preserves_targets(self):
        self.mock("id", 'echo 501')
        self.env.pop("AG_NO_ELEVATE")
        self.cli.write_text("ineligible")
        self.run_mode("--ensure-patched", 1)
        self.assertEqual(self.cli.read_text(), "ineligible")
        self.assertEqual(self.log.read_text(), "sudo\n")

    def test_menu_exit_remains_available(self):
        result = subprocess.run(["/bin/bash", str(ROOT / "macos/ag_unlocker_mac.sh")],
                                input="0\n", env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Выбор:", result.stdout)
        self.assertFalse(self.log.exists())

    def test_zsh_wrapper_preserves_io_arguments_and_exit_status(self):
        unlocker = self.home / "dev/ai/avt-antigravity-unlocker/macos/ag_unlocker_mac.sh"
        unlocker.parent.mkdir(parents=True)
        unlocker.write_text('printf "%s\\n" "$1" >> "$TEST_LOG"\nexit "${TEST_CHECK_RC:-0}"\n')
        self.cli.write_text('#!/bin/bash\nprintf "arg=<%s>\\n" "$@"\ncat\npwd\nexit 7\n')
        command = ['zsh', '-fc', f'source "{ROOT}/macos/agy.zsh"; agy "a b" "" --flag']
        result = subprocess.run(command, input="stdin survives\n", cwd=self.home,
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(result.stdout, f"arg=<a b>\narg=<>\narg=<--flag>\nstdin survives\n{self.home}\n")
        self.assertEqual(self.log.read_text(), "--check\n")
        self.env["TEST_CHECK_RC"] = "1"
        result = subprocess.run(command, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.env["TEST_CHECK_RC"] = "10"
        result = subprocess.run(command, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 10)
        self.assertEqual(result.stdout, "")
        self.assertTrue(self.log.read_text().endswith("--check\n--ensure-patched\n"))


if __name__ == "__main__":
    unittest.main()
