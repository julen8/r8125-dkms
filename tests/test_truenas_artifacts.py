import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import truenas_artifacts as artifacts


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.version = '25.04.1'
        self.fingerprint = 'a' * 64
        self.base = 'r8125-9.018.00-TrueNAS-25.04.1-6.12.15-production+truenas-x86_64'

    def create_artifacts(self):
        source = self.root / 'source'
        source.mkdir()
        checksums = []
        for suffix in artifacts.SUFFIXES[:-1]:
            path = source / (self.base + suffix)
            path.write_text(f'fixture {suffix}\n')
            checksums.append(f'{artifacts.file_hash(path)}  {path.name}\n')
        (source / (self.base + '.SHA256SUMS')).write_text(''.join(checksums))
        artifacts.record(source, self.version, self.fingerprint)
        return source

    def fake_gh(self, source, draft=False, include_receipt=True):
        receipt = artifacts.receipt_name(self.version, self.fingerprint)
        assets = [{'name': path.name} for path in source.iterdir()
                  if include_receipt or path.name != receipt]
        release = {'draft': draft, 'tag_name': 'ci-test', 'assets': assets}

        def run(command, **kwargs):
            if command[1] == 'api':
                return subprocess.CompletedProcess(command, 0, json.dumps([[release]]))
            name = command[command.index('--pattern') + 1]
            destination = Path(command[command.index('--dir') + 1]) / name
            destination.write_bytes((source / name).read_bytes())
            return subprocess.CompletedProcess(command, 0, '')

        return run

    def test_fingerprint_tracks_target_and_shared_inputs(self):
        for name in artifacts.INPUTS:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(name)
        targets = {'25.04.1': {'update_sha256': 'a' * 64}}
        original = artifacts.build_fingerprint(self.version, targets[self.version], self.root)
        targets['25.10.7'] = {'update_sha256': 'b' * 64}
        self.assertEqual(original, artifacts.build_fingerprint(
            self.version, targets[self.version], self.root))
        self.assertNotEqual(original, artifacts.build_fingerprint(
            '25.10.7', targets['25.10.7'], self.root))
        targets[self.version]['update_sha256'] = 'c' * 64
        self.assertNotEqual(original, artifacts.build_fingerprint(
            self.version, targets[self.version], self.root))
        targets[self.version]['update_sha256'] = 'a' * 64
        for name in artifacts.INPUTS:
            path = self.root / name
            original_contents = path.read_text()
            path.write_text('changed')
            self.assertNotEqual(original, artifacts.build_fingerprint(
                self.version, targets[self.version], self.root))
            path.write_text(original_contents)

    def test_reuses_complete_verified_release(self):
        source = self.create_artifacts()
        destination = self.root / 'restored'
        with patch.object(artifacts.subprocess, 'run', side_effect=self.fake_gh(source)):
            self.assertTrue(artifacts.restore(destination, self.version, self.fingerprint, 'owner/repo'))
        self.assertEqual({path.name for path in source.iterdir()},
                         {path.name for path in destination.iterdir()})

    def test_corruption_forces_rebuild_without_partial_output(self):
        source = self.create_artifacts()
        (source / (self.base + '.ko')).write_text('corrupted')
        destination = self.root / 'restored'
        with patch.object(artifacts.subprocess, 'run', side_effect=self.fake_gh(source)):
            self.assertFalse(artifacts.restore(destination, self.version, self.fingerprint, 'owner/repo'))
        self.assertFalse(destination.exists())

    def test_draft_and_legacy_releases_are_not_reused(self):
        source = self.create_artifacts()
        for options in ({'draft': True}, {'include_receipt': False}):
            with self.subTest(options=options):
                with patch.object(artifacts.subprocess, 'run', side_effect=self.fake_gh(source, **options)) as run:
                    self.assertFalse(artifacts.restore(self.root / 'restored', self.version,
                                                       self.fingerprint, 'owner/repo'))
                    self.assertEqual(run.call_count, 1)

    def test_missing_asset_forces_rebuild(self):
        source = self.create_artifacts()
        (source / (self.base + '.config')).unlink()
        with patch.object(artifacts.subprocess, 'run', side_effect=self.fake_gh(source)):
            self.assertFalse(artifacts.restore(self.root / 'restored', self.version,
                                               self.fingerprint, 'owner/repo'))

    def test_api_failure_forces_rebuild(self):
        with patch.object(artifacts.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'gh')):
            self.assertFalse(artifacts.restore(self.root / 'restored', self.version,
                                               self.fingerprint, 'owner/repo'))

    def test_invalid_receipt_forces_rebuild(self):
        source = self.create_artifacts()
        receipt_path = source / artifacts.receipt_name(self.version, self.fingerprint)
        original = receipt_path.read_text()
        for change in ('fingerprint', 'path', 'checksums'):
            with self.subTest(change=change):
                receipt = json.loads(original)
                if change == 'fingerprint':
                    receipt['fingerprint'] = 'b' * 64
                elif change == 'path':
                    receipt['files']['../unsafe.ko'] = receipt['files'].pop(self.base + '.ko')
                else:
                    path = source / (self.base + '.SHA256SUMS')
                    path.write_text('invalid checksum list\n')
                    receipt['files'][path.name] = artifacts.file_hash(path)
                receipt_path.write_text(json.dumps(receipt))
                with patch.object(artifacts.subprocess, 'run', side_effect=self.fake_gh(source)):
                    self.assertFalse(artifacts.restore(self.root / 'restored', self.version,
                                                       self.fingerprint, 'owner/repo'))
                self.assertFalse((self.root / 'restored').exists())

    def test_force_rebuild_skips_release_lookup(self):
        output = self.root / 'output'
        with patch.dict(artifacts.os.environ, {
            'TRUENAS_VERSION': self.version, 'BUILD_FINGERPRINT': self.fingerprint,
            'FORCE_REBUILD': 'true', 'GITHUB_OUTPUT': str(output),
        }), patch.object(sys, 'argv', ['truenas_artifacts.py', 'restore']), \
                patch.object(artifacts, 'restore') as restore:
            artifacts.main()
        restore.assert_not_called()
        self.assertEqual(output.read_text(), 'reused=false\n')


if __name__ == '__main__':
    unittest.main()