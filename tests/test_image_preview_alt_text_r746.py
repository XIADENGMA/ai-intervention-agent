"""R746: the alt text of an image preview is the file name as it is.

``DOMSecurity.createImagePreview`` ran the file name through an HTML entity escaper
before assigning it to ``img.alt``. ``alt`` is a DOM property: the browser keeps the
string as given and nobody parses it as HTML, so a file called ``Tom & Jerry's.png``
got the alt text ``Tom &amp; Jerry&#x27;s.png`` and a screen reader read the entities
out. The VS Code panel and the image modal already assign the name unchanged.

The tests load the real ``dom-security.js`` into Node with a fake DOM and read the
``alt`` of the preview it builds.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOM_SECURITY_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "dom-security.js"
)

NODE_AVAILABLE = shutil.which("node") is not None

HARNESS = textwrap.dedent(
    """
    const fs = require('fs');
    const vm = require('vm');

    function makeElement(tag) {
      return {
        tag, children: [], attrs: {}, className: '', textContent: '', id: '',
        src: '', alt: '',
        appendChild(child) { this.children.push(child); return child; },
        setAttribute(name, value) { this.attrs[name] = value; },
        addEventListener() {},
      };
    }

    const source = fs.readFileSync(%(path)s, 'utf8');
    const sandbox = {
      console,
      window: {},
      document: { createElement: makeElement },
    };
    vm.createContext(sandbox);
    vm.runInContext(source + '\\n;this.DOMSecurity = DOMSecurity;', sandbox);

    function previewOf(name) {
      const item = { id: 'img-1', name, previewUrl: 'blob:preview', size: 2048 };
      return sandbox.DOMSecurity.createImagePreview(item);
    }
    function altOf(name) {
      return previewOf(name).children.find((child) => child.tag === 'img').alt;
    }
    """
)


def _run_node(case_js: str) -> dict:
    script = HARNESS % {"path": json.dumps(str(DOM_SECURITY_JS))} + case_js
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        check=False,
        text=True,
        timeout=20,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return json.loads(proc.stdout)


@unittest.skipUnless(NODE_AVAILABLE, "node runtime unavailable")
class TestImagePreviewAltText(unittest.TestCase):
    def test_the_alt_text_is_the_file_name_as_it_is(self) -> None:
        names = [
            "photo.png",
            "Tom & Jerry's.png",
            'say "cheese" <1>.png',
            "&amp;.png",
            "日本語 – 名前.png",
        ]
        result = _run_node(
            f"""
            const names = {json.dumps(names)};
            console.log(JSON.stringify(names.map(altOf)));
            """
        )
        self.assertEqual(result, names)

    def test_a_name_that_is_not_a_string_gives_an_empty_alt_text(self) -> None:
        result = _run_node(
            """
            const odd = [undefined, null, 42, {}, ['a.png']];
            console.log(JSON.stringify(odd.map(altOf)));
            """
        )
        self.assertEqual(result, [""] * 5)

    def test_the_preview_still_shows_the_image_with_its_buttons_and_label(self) -> None:
        result = _run_node(
            """
            const preview = previewOf('photo.png');
            const img = preview.children.find((child) => child.tag === 'img');
            console.log(JSON.stringify({
              id: preview.id,
              tags: preview.children.map((child) => child.tag),
              src: img.src,
              imgClass: img.className,
            }));
            """
        )
        self.assertEqual(
            result,
            {
                "id": "preview-img-1",
                "tags": ["img", "button", "div"],
                "src": "blob:preview",
                "imgClass": "image-preview-thumbnail",
            },
        )


if __name__ == "__main__":
    unittest.main()
