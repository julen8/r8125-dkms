import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parent.parent
INPUTS = (
    'PKGBUILD',
    'scripts/build-truenas-ko.sh',
    'scripts/truenas_artifacts.py',
    '.github/workflows/truenas-ko.yml',
)
SUFFIXES = ('.ko', '.config', '.txt', '.SHA256SUMS')


def build_fingerprint(version, target, root=ROOT):
    inputs = {
        'schema': 1,
        'version': version,
        'target': target,
        'files': {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in INPUTS
        },
    }
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()


def receipt_name(version, fingerprint):
    return f'r8125-TrueNAS-{version}-{fingerprint}.build.json'


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_files(directory, receipt, version, fingerprint):
    if receipt['schema'] != 1 or receipt['version'] != version:
        raise ValueError('Invalid build receipt version')
    if receipt['fingerprint'] != fingerprint:
        raise ValueError('Build fingerprint mismatch')
    files = receipt['files']
    modules = [name for name in files if name.endswith('.ko')]
    if len(modules) != 1:
        raise ValueError('Expected one module')
    base = modules[0][:-3]
    if not re.fullmatch(r'[A-Za-z0-9._+-]+', base):
        raise ValueError('Invalid artifact name')
    if set(files) != {base + suffix for suffix in SUFFIXES}:
        raise ValueError('Incomplete artifact set')
    for name, checksum in files.items():
        path = directory / name
        if not re.fullmatch(r'[0-9a-f]{64}', checksum):
            raise ValueError('Invalid artifact checksum')
        if not path.is_file() or path.stat().st_size == 0 or file_hash(path) != checksum:
            raise ValueError(f'Artifact checksum mismatch: {name}')
    expected = ''.join(f'{files[base + suffix]}  {base + suffix}\n'
                       for suffix in SUFFIXES[:-1])
    if (directory / (base + '.SHA256SUMS')).read_text() != expected:
        raise ValueError('SHA256SUMS does not match the build receipt')


def record(directory, version, fingerprint):
    files = {path.name: file_hash(path) for path in directory.iterdir()
             if path.is_file() and path.suffix in SUFFIXES}
    receipt = {'schema': 1, 'version': version, 'fingerprint': fingerprint,
               'files': files}
    verify_files(directory, receipt, version, fingerprint)
    (directory / receipt_name(version, fingerprint)).write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + '\n')


def restore(directory, version, fingerprint, repository):
    name = receipt_name(version, fingerprint)
    try:
        result = subprocess.run(
            ['gh', 'api', '--paginate', '--slurp',
             f'repos/{repository}/releases?per_page=100'],
            check=True, capture_output=True, text=True)
        pages = json.loads(result.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError) as error:
        print(f'::warning::Cannot list releases; rebuilding ({type(error).__name__}).')
        return False
    for page in pages:
        for release in page:
            if release['draft'] or name not in {asset['name'] for asset in release['assets']}:
                continue
            try:
                with tempfile.TemporaryDirectory() as temporary:
                    staging = Path(temporary)
                    command = ['gh', 'release', 'download', release['tag_name'],
                               '--repo', repository, '--dir', temporary]
                    subprocess.run(command + ['--pattern', name], check=True,
                                   capture_output=True, text=True)
                    receipt = json.loads((staging / name).read_text())
                    assets = {asset['name'] for asset in release['assets']}
                    files = receipt['files']
                    if not isinstance(files, dict) or len(files) != len(SUFFIXES):
                        raise ValueError('Invalid receipt files')
                    if not all(re.fullmatch(r'[A-Za-z0-9._+-]+', asset) for asset in files):
                        raise ValueError('Invalid asset name')
                    if not set(files).issubset(assets):
                        raise ValueError('Release is missing build assets')
                    for asset in files:
                        subprocess.run(command + ['--pattern', asset], check=True,
                                       capture_output=True, text=True)
                    verify_files(staging, receipt, version, fingerprint)
                    directory.mkdir(parents=True, exist_ok=True)
                    for asset in [*files, name]:
                        shutil.copy2(staging / asset, directory / asset)
                print(f'Reused TrueNAS {version} from release {release["tag_name"]}')
                return True
            except (subprocess.CalledProcessError, OSError, ValueError, KeyError, TypeError):
                print(f'::warning::Invalid or unavailable artifacts for TrueNAS {version}; trying next release.')
    print(f'No verified published build for TrueNAS {version}; rebuilding.')
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('restore', 'record'))
    arguments = parser.parse_args()
    version = os.environ['TRUENAS_VERSION']
    fingerprint = os.environ['BUILD_FINGERPRINT']
    if not re.fullmatch(r'[0-9][A-Za-z0-9._-]*', version):
        raise SystemExit('Invalid TrueNAS version')
    if not re.fullmatch(r'[0-9a-f]{64}', fingerprint):
        raise SystemExit('Invalid build fingerprint')
    directory = ROOT / 'dist' / version
    if arguments.command == 'record':
        record(directory, version, fingerprint)
    else:
        reused = False
        if os.environ.get('FORCE_REBUILD', 'false') != 'true':
            reused = restore(directory, version, fingerprint, os.environ['GH_REPO'])
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            output.write(f'reused={str(reused).lower()}\n')


if __name__ == '__main__':
    main()