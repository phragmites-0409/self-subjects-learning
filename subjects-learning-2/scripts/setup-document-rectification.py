"""Pinned official UVDoc ONNX model; reuse the verified range downloader."""
import importlib.util,json,runpy,sys
from pathlib import Path
from runtime_paths import portable_manifest
spec=importlib.util.spec_from_file_location('document_setup',Path(__file__).with_name('setup-document-ocr.py'))
setup=importlib.util.module_from_spec(spec);spec.loader.exec_module(setup)
target=setup.BASE/'models/uvdoc';target.mkdir(parents=True,exist_ok=True)
revision='3bcf535371727d11e783101f79a504c68848aae3'
entry=(target/'inference.onnx',f'https://huggingface.co/PaddlePaddle/UVDoc_onnx/resolve/{revision}/inference.onnx',31684150,'54cab30dc2cf347b4f3d6971c833b1c3d84f5ef17280f1f6d15796bff20e63d6')
setup.download(entry)
(target/'manifest.json').write_text(json.dumps(portable_manifest({'source':'https://huggingface.co/PaddlePaddle/UVDoc_onnx','revision':revision,'path':str(entry[0]),'sha256':entry[3],'license':'Apache-2.0','preview_only':True}),indent=2),encoding='utf-8')
sys.path.insert(0,str(setup.BASE/'local-ocr-packages'))
runpy.run_path(str(Path(__file__).with_name('export-uvdoc-grid.py')),run_name='__main__')
print('UVDoc ready',flush=True)
