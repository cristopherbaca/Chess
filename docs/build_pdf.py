"""Render the technical document with local Chrome/Chromium; no pip dependencies."""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser', help='Path to Chrome or Chromium')
    args = parser.parse_args()
    candidates = [args.browser] if args.browser else [
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        shutil.which('google-chrome'), shutil.which('chromium'),
        shutil.which('chromium-browser'),
    ]
    browser = next((p for p in candidates if p and Path(p).is_file()), None)
    if browser is None:
        parser.error('Install Chrome/Chromium or supply --browser /path/to/browser')
    folder = Path(__file__).resolve().parent
    output = folder / 'IA_Y_DEPLOYMENT.pdf'
    with tempfile.TemporaryDirectory(prefix='chess-docs-') as temporary:
        rendered = Path(temporary) / output.name
        result = subprocess.run([
            browser, '--headless=new', '--no-first-run', '--no-default-browser-check',
            '--disable-background-networking', '--disable-extensions',
            f'--user-data-dir={temporary}/profile', '--no-pdf-header-footer',
            f'--print-to-pdf={rendered}', (folder / 'IA_Y_DEPLOYMENT.html').as_uri(),
        ], capture_output=True, text=True, timeout=90)
        if result.returncode or not rendered.is_file():
            raise RuntimeError(f'PDF rendering failed: {result.stderr[-4000:]}')
        if not rendered.read_bytes().startswith(b'%PDF-'):
            raise RuntimeError('Browser did not produce a PDF')
        shutil.copyfile(rendered, output)
    print(f'Created {output} ({output.stat().st_size:,} bytes)')


if __name__ == '__main__':
    main()
