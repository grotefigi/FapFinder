# Third-party software

FapFinder's application code is MIT-licensed. Bundled dependencies retain their own licenses and notices; the application license does not replace them.

| Component | Project | License / notice |
|---|---|---|
| SigLIP 2 model | https://huggingface.co/google/siglip2-base-patch16-224 | Apache-2.0 |
| Transformers | https://github.com/huggingface/transformers | Apache-2.0 |
| Hugging Face Hub, tokenizers, safetensors | https://github.com/huggingface | Apache-2.0 |
| PyTorch | https://github.com/pytorch/pytorch | BSD-style; see bundled notices |
| Qt / PySide6 Essentials / Shiboken | https://www.qt.io/qt-for-python | LGPLv3 / GPLv3 / commercial; shipped as dynamic libraries |
| NumPy | https://numpy.org | BSD-3-Clause and bundled library notices |
| Pillow | https://python-pillow.org | HPND |
| SentencePiece | https://github.com/google/sentencepiece | Apache-2.0 |
| Python | https://www.python.org | PSF License |
| NVIDIA CUDA runtime / cuDNN libraries | https://developer.nvidia.com | NVIDIA redistribution terms supplied with the PyTorch distribution |
| PyInstaller bootloader | https://pyinstaller.org | GPL with bootloader exception |

The portable build keeps Qt and other shared libraries separately replaceable inside `_internal`. Source for the application, build specification, and pinned dependency list accompanies this project. Consult each dependency's license before redistributing a modified package.
