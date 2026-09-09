# Local vision model selection for FapFinder

## Decision

Use Google's **SigLIP 2 Base, patch 16, 224 px** as the initial local embedding and zero-shot classification engine. The choice prioritizes repeatable ranking, bulk throughput, straightforward Windows deployment, and substantial headroom within a 6 GB GPU. It is an engineering choice for this application, not a claim that this checkpoint is the most accurate model available for every human appearance attribute.

SigLIP 2 supports both text–image retrieval and zero-shot image classification. Its authors report improved semantic, localization, and dense-feature capabilities over the original family. Those general-purpose evaluations support using it as a retrieval backbone; they do not establish accuracy for body build, skin appearance, apparent age, or face shape. [Google model card](https://huggingface.co/google/siglip2-base-patch16-224), [Tschannen et al., 2025](https://arxiv.org/abs/2502.14786).

The application pins revision `75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2`. The public files total approximately 1.54 GB. The model weights are supplied as safetensors, and the model card identifies an Apache-2.0 license. The loader uses the fixed-resolution checkpoint through Transformers' SiglipModel/SiglipProcessor classes. It never executes remote repository code. [Pinned files](https://huggingface.co/google/siglip2-base-patch16-224/tree/75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2).

## Alternatives considered

| Candidate | Relevant strengths | Application tradeoff | Decision |
|---|---|---|---|
| SigLIP 2 Base 224 | Image/text embeddings; zero-shot labels; public safetensors checkpoint | Broad prompts do not provide reliable per-trait calibration | Implemented and measured locally |
| OpenCLIP family | Mature open implementation; many image/text checkpoints | Requires selecting and validating a specific checkpoint; changing the family alone does not validate appearance tags | A viable future interchangeable embedding engine |
| SmolVLM-256M-Instruct | Very small image-to-text model; conversational image descriptions | Generated answers require constrained parsing and still need confidence calibration; not a drop-in retrieval index | Not added to the default pipeline |
| Qwen3-VL-2B-Instruct | Richer image-to-text reasoning and description interface | Additional model and generation state; a separate embedding index would still be useful for fast search | Possible optional second-pass reviewer after a real-photo evaluation |

OpenCLIP explicitly provides an open implementation and a range of pretrained CLIP-compatible models. Its repository documents zero-shot classification and image/text feature extraction. This makes it a credible alternative, but no head-to-head appearance-label evaluation was performed for this project. [OpenCLIP repository](https://github.com/mlfoundations/open_clip).

SmolVLM-256M is supplied as an image-to-text model with an Apache-2.0 license and a small parameter count. The published usage generates text from images and prompts. It is attractive for short descriptions, but its model-card examples do not establish calibrated confidence for the requested traits. [SmolVLM model card](https://huggingface.co/HuggingFaceTB/SmolVLM-256M-Instruct).

Qwen3-VL-2B-Instruct is also an Apache-2.0 image-to-text checkpoint. Its documented interface supports multimodal conversation and generated responses. Choosing it as the only engine would change the search architecture: descriptions can be indexed, but image-to-image and text-to-image retrieval still benefit from dedicated comparable embeddings. The decision to defer it is an architectural judgment, not a measured claim that SigLIP is more accurate. [Qwen model card](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct).

## Processing design

Each imported image is content-hashed, orientation-corrected for display and analysis, and given a small JPEG preview. The original is copied by default without modifying its bytes. Large collections do not create one widget per file: the native gallery paints visible items and retains a bounded preview cache.

The AI engine builds a normalized embedding for each image. It creates a prototype for each predefined trait option by averaging two normalized prompt embeddings. Each image is compared with these prototypes, and each trait group receives a softmax over its own options plus an unknown/not-visible alternative. A fixed temperature multiplier of 20 is part of the stored model-version identifier. Prompt changes or temperature changes should increment that identifier.

This classification recipe is application code, not an official calibrated trait head. Scores vary with the candidate set, wording, image resolution, and lighting. Softmax sums to one even when none of the offered options fits well. Adding an Unknown prompt and requiring a score/margin before promoting a label reduces forced labels, but does not solve this problem.

Automatic label promotion requires at least 0.55 and a 0.12 lead over the runner-up. Apparent age uses 0.75. These are conservative interface thresholds, not thresholds selected on a labeled validation set. The editor retains the strongest raw suggestion so a person can inspect uncertainty. Weighted search deliberately uses all raw candidate scores for exploratory ranking, even when the promoted label is Unknown.

Text inputs use the checkpoint's expected lowercasing, padding, and 64-token maximum. Long descriptions are truncated by the tokenizer; short concrete searches work best. Image/text embeddings are L2-normalized before cosine comparison. Transformers documents the relevant image and text feature APIs and preprocessing behavior. [Transformers documentation](https://huggingface.co/docs/transformers/model_doc/siglip2).

## Height and other ambiguous traits

An uncalibrated photo does not supply metric scale. A short subject photographed nearby and a tall subject photographed farther away can occupy the same pixel height. The app therefore records actual height only when entered by a person with a known measurement. Relative apparent height from composition is not substituted for centimeters.

Apparent body build is affected by clothing, pose, cropping, and lens perspective. It is not a health assessment. Visible skin tone is a description of color in a particular image; it must not be interpreted as ethnicity or race. Apparent adult age ranges are unreliable and do not establish adulthood. Face-shape scores describe the image perspective and can change with head angle.

The current engine analyzes the whole frame. It does not detect and isolate each person, verify that the subject is a woman, or determine which person a trait refers to in a group photograph. For consistent results, use clearly framed single-person images and review automatically suggested tags. All requested visual categories have manual overrides so an image remains searchable when the model is wrong or the trait is not visible.

## Local performance and memory

The measured workload used 1,500 unique synthetic PNGs at 160 × 200, with batch size 16. Import took 23.8 seconds. GPU analysis took 33.0 seconds, or approximately 45.4 images/second. Initial model load took 6.0 seconds. PyTorch reported peak allocated GPU memory of 799.5 MiB and reserved memory of 834.0 MiB, excluding display/driver allocations. Weighted search took 125 ms; one text-embedding-plus-search query took 39 ms after loading.

These are measurements from this computer, not source-model benchmarks. Synthetic fixtures test import scale, storage, tensor execution, and ranking. They do not test label correctness. Large JPEGs, slow drives, battery power limits, and competing GPU applications may substantially increase total time. A separate real-photo validation set is needed to compare accuracy or estimate real collection throughput.

For 1,500 images, 768-dimensional float32 embeddings require about 4.6 MB before database overhead. This is small enough for direct NumPy cosine ranking without a separate vector database. SQLite stores typed records, model/version information, and user overrides; WAL mode permits short background writes while the interface reads.

## Offline behavior

The only application-managed network operation in the analysis stack is the explicit model setup downloader. It requests a pinned public repository revision, verifies the large weights against the repository's SHA-256 metadata, and records hashes for every downloaded file. It supports retrying completed verified files and resuming partial pinned files.

Normal inference loads local paths with offline settings, local-files-only loading, safetensors, and disabled remote code. During integration verification, socket connection methods were replaced with rejecting functions before model loading. Load, all 1,500 analyses, text search, and image similarity completed with zero connection attempts. This is a targeted behavior test, not an operating-system firewall or a guarantee against unrelated software on the computer.

Online discovery in version 1.1 is opt-in: an editable text description retrieves candidates from Bing's public image index, then downloaded previews are compared locally using SigLIP 2. Reference images and embeddings remain on the computer. Numeric trait weights affect local reranking; they are not remotely enforced filters. The index cannot cover every site or guarantee source availability. This is an ordinary public-page adapter, not the retired Bing Search API; no paid API key is required.

## Validation still needed for accuracy claims

A meaningful accuracy study should use photographs representative of the intended collection, with independently reviewed labels and an Unknown option. Measurements should report per-trait precision and coverage at the chosen thresholds, rates of inappropriate forced labels on obscured/group images, and retrieval usefulness judged over several complete queries. Apparent age and body categories may have substantial disagreement even between reviewers, so agreement should be reported alongside model performance.

No such labeled collection was supplied. The delivered app is operational, but no claim is made that its appearance scores have a particular accuracy. A future model change should be compared on the same held-out images and queries before replacing the current model or migrating saved embeddings.

## Sources

1. Google. [SigLIP 2 Base model card](https://huggingface.co/google/siglip2-base-patch16-224), checkpoint released 2025; inspected 9 September 2026.
2. Tschannen et al. [SigLIP 2: Multilingual Vision-Language Encoders with Improved Semantic Understanding, Localization, and Dense Features](https://arxiv.org/abs/2502.14786), 2025.
3. Hugging Face. [SigLIP 2 Transformers documentation](https://huggingface.co/docs/transformers/model_doc/siglip2), API documentation; inspected 9 September 2026.
4. ML Foundations. [OpenCLIP](https://github.com/mlfoundations/open_clip), repository documentation; inspected 9 September 2026.
5. HuggingFaceTB. [SmolVLM-256M-Instruct](https://huggingface.co/HuggingFaceTB/SmolVLM-256M-Instruct), model card; inspected 9 September 2026.
6. Qwen. [Qwen3-VL-2B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct), model card; inspected 9 September 2026.
7. PyTorch. [Start locally](https://docs.pytorch.org/get-started/locally/), installation documentation; inspected 9 September 2026. The project installs the official CUDA 12.8 Windows wheel.
