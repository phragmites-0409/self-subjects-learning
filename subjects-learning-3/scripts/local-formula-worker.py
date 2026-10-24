"""One bounded offline formula transcription in its compatible Python environment."""

import base64
import contextlib
import json
import sys

with contextlib.redirect_stdout(sys.stderr):
    from rapid_latex_ocr import LaTeXOCR
    from rapid_latex_ocr.utils_load import OrtInferSession

    original_init = OrtInferSession.__init__

    def bounded_threads(self, model_path, num_threads=-1):
        original_init(self, model_path, num_threads=4)

    # The library does not expose thread settings through LaTeXOCR's constructor.
    OrtInferSession.__init__ = bounded_threads

    request = json.loads(sys.stdin.read())
    engine = LaTeXOCR(**request["config"])
    text, elapsed = engine(base64.b64decode(request["image"]))
print(json.dumps({"text": text, "seconds": elapsed}, ensure_ascii=False))
