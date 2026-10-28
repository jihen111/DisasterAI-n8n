# DisasterAI

Multi-agent AI assistant for disaster assessment and response. Final project, Advanced Deep Learning (AI Automation), class 5DS1, Esprit, 2026-2027.

DisasterAI is a decision-support prototype. It does not replace emergency services, dispatch vehicles or make life-critical decisions.

A witness report (text, optional photo, English or French) goes into an **n8n** workflow. Six agents read it, look at the photo with a **local vision model**, search our own **knowledge base (RAG)**, assess the risk and write a sourced report. Automatic checks then validate the report.

| Brief requirement | Where it is in this repository |
|---|---|
| 1. Automation platform, triggerable end to end | `n8n/workflows/disasterai.json` (78 nodes), started by one POST to the webhook |
| 2. Prompt engineering, versioned library | `prompts/` (one file per version), `prompts/CHANGELOG.md`, `docs/PROMPT_LIBRARY.md` |
| 3. RAG and retrieval evaluation | `rag/` (corpus, chunking, ChromaDB), `rag/eval/` (queries and results), RAG section of `docs/EVIDENCE_LOG.md` |
| 4. Multi-agent system | Pipeline section below, `docs/N8N_WORKFLOW_PLAN.md` |
| 5. Multimodality (images) | `docs/VISION_ARCHITECTURE.md`, `vision/test_images/` |
| Technical report, prompt library, retrieval evaluation | `docs/` (see Documents) |

## Quick start (Windows, PowerShell)

Needs Docker Desktop (running), Python 3.10 or newer, Git, and a free Groq API key. For the local vision model you also need an NVIDIA GPU with 6 GB of memory and about 10 GB of free disk space.

```powershell
git clone https://github.com/jihen111/DisasterAI-n8n.git
cd DisasterAI-n8n
copy .env.example .env
notepad .env                      # paste GROQ_API_KEY=... (and optionally GEMINI_API_KEY=...)
python -m venv .venv
.\.venv\Scripts\Activate.ps1      # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install torch --index-url https://download.pytorch.org/whl/cpu   # CPU build, much smaller
pip install -r requirements.txt
docker compose up -d              # n8n on http://localhost:5678
python -m rag.ingest --strategy both
```

Local vision model, Ollama in Docker with the GPU (one time, about 3.3 GB):

```powershell
docker run -d --name ollama --restart unless-stopped --gpus all -p 11434:11434 -v ollama_models:/root/.ollama -e OLLAMA_KEEP_ALIVE=24h ollama/ollama
docker exec ollama ollama pull qwen3-vl:4b-instruct
python scripts/llm_ping.py --model ollama:qwen3-vl:4b-instruct --image --json   # first call about 70 s (model loading)
```

Then:

1. Start the service and leave the window open: `uvicorn rag.service:app --host 0.0.0.0 --port 8010`. Restart it after any change to `.env`.
2. Open http://localhost:5678 and create the owner account.
3. Import both workflows: **Create workflow → ⋯ → Import from File**, choose `n8n/workflows/disasterai.json`, then `disasterai_error.json`. Then **Publish** "DisasterAI pipeline".
4. In a second window (activate the venv first), run `streamlit run ui/app.py`. Pick `fire_01`, upload `vision/test_images/fire_01.jpg` and press **Run**.

In PowerShell, call the webhook with `curl.exe`, not `curl` (which is an alias for `Invoke-WebRequest`). Free-tier rate limits are normal: the chain then falls back to the next model, and the console shows which model answered each step.

Verified on 2026-10-28 on a fresh Windows 11 machine (RTX 4050, 6 GB), following the steps above. `fire_01` with its image ran with 6 model calls in 29 s of model time: vision took 10 s on `qwen3-vl:4b-instruct`, the risk step fell back after a Groq rate limit, there were no degraded steps and validation passed. Raw file: `eval/results/ui_runs/20261028-192102-524_fire_01.json`.

## Status (2026-10-18)

Built and tested offline: the knowledge base (91 entries, English and French), retrieval, agent output schemas, the `/validate` guardrails, the model fallback chain, the n8n workflow generator, a test console (UI), and the JavaScript of the workflow nodes (run under Node). Run in n8n with MOCK agents (all six incidents, seven failure paths) and with real models for a limited number of runs, including images through a local vision model (`qwen3-vl:4b-instruct`, Docker, GPU). Real runs through the test console exposed and led to fixes of two defects (a repair pass that returned a truncated report, and fire coverage reported as "good" although the base has no guidance for flames reaching a house).

**Not yet shown:** a clean batch of the six incidents with images on real models; that the pipeline beats a single prompt (the baseline ran once, text only, and was not re-scored); stability between runs (one incident changed severity across four console runs); reviewed French translations. Free-tier quotas ran out repeatedly. Prompt versions incident v3, report v4, knowledge v2 and risk v2 are drafts with partial evidence; vision v2 and risk v3 (image-only vision and the comparison on the text side) are written and benchmarked but not the default. The honest list is in `docs/EVIDENCE_LOG.md`, `docs/SPRINT_STATUS.md` and `docs/BOTTLENECKS.md`.

## Pipeline

Incident (text and optional image) -> n8n webhook -> Incident Understanding Agent -> Vision Agent and RAG Agent (parallel) -> Merge -> Risk Assessment Agent -> Report Agent -> `/validate` (one repair pass, never returned if it makes the report worse) -> final report.

Scope of version 1: forest fires, floods, structural or urban emergencies. Languages: English and French.

```
client --multipart--> n8n webhook
                         |
                  Incident Understanding --(unclear)--> "more information needed"
                         |
            +------------+-------------+
            |                          |
         Vision                  RAG queries -> /search -> Knowledge synthesis
            |                          |
            +-----------Merge----------+
                         |
                  Risk -> Report -> /validate -> (repair once) -> response
```

n8n owns the orchestration (branches, parallel paths, retries, error workflow, what a failure means). Every agent is a pair of nodes: a Set node holding the versioned prompt and an HTTP node calling `POST /llm`. Python stays small: one FastAPI service with `/search` (retrieval), `/validate` (guardrails), `/llm` (model fallback chain) and two stateless image tools, `/vision/variants` and `/vision/merge`, which are only used by the optional three-view vision path.

**Vision.** The default is one vision call per image (prompt vision v1, which also sees the report). A failed vision step gives `vision: null` and `image_status: analysis_failed`, never "unusable image". An optional three-view path (`python scripts/build_workflow.py --vision-mode tta`, merge policy `--tta-merge majority|keep_high`) makes three views of the image, calls the model once per view from n8n, and merges agreed observations. It is tested and documented but stays off: on 12 images it showed no benefit for about three times the latency (`docs/VISION_ARCHITECTURE.md`, `docs/EVIDENCE_LOG.md`).

## Stack

- Automation: n8n, self-hosted with Docker
- Models: a fallback chain over Gemini, Groq and OpenRouter free tiers (`LLM_CHAIN` in `.env`, `backend/llm_chain.py`). Each response lists the model that answered every step (`models_used`). Image calls use their own `VISION_CHAIN`: a local `qwen3-vl:4b-instruct` served by Ollama in Docker with the GPU, then Gemini, then an OpenRouter vision model. The Hugging Face provider is coded and unit-tested but not tried (no token). The thinking tag `qwen3-vl:4b` does not work with this chain.
- Embeddings: multilingual-e5-small via sentence-transformers (local)
- Vector store: ChromaDB (local), section chunking (chosen after evaluation); `/search` can keep results of both languages in the list (`balance_languages`, on in the workflow)
- Service: Python FastAPI on port 8010
- Test console: Streamlit (`ui/`)
- Language: Python, version control with Git

## Repository layout

- `prompts/` one folder per agent, one file per prompt version, `CHANGELOG.md`
- `rag/` retrieval service, corpus (`rag/corpus/en`, `fr`), evaluation queries (`rag/eval/`); `rag/knowledge_base/` is the knowledge base build and QA tools
- `backend/` agent output schemas, `/validate`, the model chain, the vision tools, the MOCK Gemini, tests
- `n8n/workflows/` generated workflow JSON (never edit by hand)
- `eval/incidents/` six fixed test incidents, `eval/results/` raw outputs of every run
- `vision/test_images/` twelve CC BY test images with attribution, `GROUND_TRUTH.json` (one reader), and the decision rules written before the vision benchmarks
- `ui/` the Streamlit test console (client, rendering, saved runs, samples)
- `scripts/` helper, benchmark and test scripts
- `docs/` plans, evidence log, status, proposals

## Setup

1. Install Docker and Python 3.10 or newer.
2. Copy `.env.example` to `.env`. Fill in at least one provider key: `GEMINI_API_KEY` (Google AI Studio), `GROQ_API_KEY` (console.groq.com), `OPENROUTER_API_KEY` (openrouter.ai). Create the keys yourself and never commit `.env`. Set `LLM_CHAIN` to models you verified (below).
3. Create a virtual environment and install dependencies:

   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt

4. Start n8n:

   docker compose up -d

   Then open http://localhost:5678 and create the owner account. A new n8n is empty: import the workflows (step 3 of "Run it") before using the console, otherwise the webhook answers 404.
5. Run the environment check: `python scripts/check_env.py` (add `--skip-embeddings` to skip the first embedding model download).
6. Check the models of the chain: `python scripts/llm_ping.py --list groq`, then `python scripts/llm_ping.py --json` (one call per model of `LLM_CHAIN`, never prints a key).

Local vision model: run the `ollama/ollama` Docker image with `--gpus all`, pull `qwen3-vl:4b-instruct` (not the thinking tag `qwen3-vl:4b`) and set `VISION_CHAIN=ollama:qwen3-vl:4b-instruct,...`; exact commands in `docs/VISION_ARCHITECTURE.md`. Needs about 3.3 GB per model, a GPU with 6 GB, and several GB free on C: or Docker fails. Do not run a second Ollama on the same port (the Windows app and the Docker container both use 11434; the chain uses `localhost`).

Notes from the development machine (Windows 11): if Python reports certificate errors, `pip install truststore` (the scripts use it when present); a network that re-signs TLS (an antivirus) also breaks the Ollama container, which then needs that root certificate mounted and `SSL_CERT_DIR` set (see `docs/EVIDENCE_LOG.md`); if importing sentence-transformers fails with a Keras 3 message, set `USE_TF=0` and `TRANSFORMERS_NO_TF=1`; with no internet set `HF_HUB_OFFLINE=1` after the first model download. Port 8000 was taken by another application, so the service uses 8010. Long benchmarks fail if the PC sleeps (a call took 4,000 s once): keep it awake.

## Run it

1. Build the index (first run downloads the embedding model): `python -m rag.ingest --strategy both`
2. Start the service for n8n: `uvicorn rag.service:app --host 0.0.0.0 --port 8010`. It serves `/search`, `/validate`, `/llm`, `/llm/status`, `/vision/variants`, `/vision/merge` and `/health`. n8n in Docker reaches it at `http://host.docker.internal:8010`. Restart it after changing code: n8n does not.
3. Generate and import the workflow: `python scripts/build_workflow.py`, then in n8n **Import from file** `n8n/workflows/disasterai.json` and `disasterai_error.json` and switch the workflow on (or with the CLI inside the container: `n8n import:workflow --input=...`, `n8n publish:workflow --id=disasterai-pipeline`, restart n8n). The default build uses the draft prompts incident v3, vision v1, rag queries v1, knowledge v2, risk v2 and report v4. For the previously tested prompts: `--prompt incident=incident_understanding/v1.md --prompt report=report/v3.md`. Several variants can live side by side with `--workflow-id`, `--path` and `--out-name`.
4. Send an incident:

   curl -X POST "http://localhost:5678/webhook/incident" -F "incident_text=Smoke is rising from the hills behind the village." -F "output_language=en" -F "image=@vision/test_images/fire_01.jpg;type=image/jpeg"

   The image part needs its own Content-Type (`;type=image/jpeg`), otherwise n8n delivers it as text and the Vision step is skipped (the workflow says so in `degraded_steps`).

The response is JSON: `status` (ok, needs_more_information, degraded, flagged, rejected), `report`, `report_markdown`, `validation` (with `first_violations` when a repair ran, and `repair_discarded` when the repaired report was worse and the original was returned), `knowledge_coverage`, `degraded_steps`, `models_used`, `prompt_versions`.

### Test console (UI)

A Streamlit screen to send an incident to the n8n webhook and read the result: `streamlit run ui/app.py` (opens on http://localhost:8501). Pick the n8n instance in the sidebar (default `http://localhost:5678/webhook/incident`, the one `docker compose up -d` publishes), check the health lights (n8n, RAG service, model chains, local vision model, disk), choose a fixed incident or write your own, add a photo, press Run. The result shows a plain-language status, the report with the source of each statement and the passage behind each recommendation, the image next to the report, the real pipeline steps (model, seconds, fallbacks, degraded steps, first validation problems, a discarded repair) and the raw JSON. For a fixed incident it also shows the expected values (type, severity) as met or not. Every run is saved in `eval/results/ui_runs/` and can be compared in the History tab. n8n answers only when the whole run ends, so the progress bar is a timer. The console explains its own errors (unreachable, workflow not active, timeout, not JSON). To try the screen without spending model quota: `python scripts/replay_webhook.py` and pick "Replay of saved answers" (it replays saved real answers and is labelled MOCK; add `?mode=degraded`, `flagged`, `repair_discarded`, `rejected`, `error500`... in a custom URL to see the failure paths). Tests: `backend/tests/test_ui.py` and `test_ui_app.py`.

## Tests

- Unit tests (no network, no model): `python -m unittest discover -s rag/tests -t .` and `python -m unittest discover -s backend/tests -t .` (32 and 209 tests on 2026-10-18). The tests of the workflow's JavaScript nodes need Node (`node` on the path) and are skipped without it.
- Retrieval: `python -m rag.evaluate --queries rag/eval/queries_v2.csv --strategy both` (add `--use-topic-filter`, `--balance-languages`); query sets v2, v3 and v4 (v4 is a held-out set for the language balance); `python scripts/rag_query_vs_direct.py` compares the RAG-query agent with a direct query on pre-registered cases
- Contracts and workflow: `python scripts/check_contracts.py`, `python scripts/check_workflow.py` (static, does not run n8n)
- Offline replay with MOCK agents: `python scripts/replay_mock.py`; failure paths with a MOCK Gemini: `python scripts/failure_paths_mock.py --url <webhook>`
- Real end-to-end, six incidents: `python scripts/run_incidents.py --url <webhook> --runs 2` then read each report with `python scripts/show_run.py <results folder> <incident id> <run>` and score `manual_checks`
- Vision: `python scripts/vision_bench.py --model ollama:qwen3-vl:4b-instruct --runs 2 --prompt vision/v1.md --prompt vision/v2.md` (add `--prompt tta:vision/v2.md` for the three-view path; `--rescore <folder>` recomputes a finished run); `python scripts/incident_type_check.py` checks incident types on a held-out set. The decision rules for adopting a vision change are written before the runs in `vision/test_images/*CRITERIA*.md`.
- Baseline, one prompt instead of the pipeline: `python scripts/baseline_single_prompt.py --runs 2`
- Prompt before and after: `python scripts/before_after.py` (pipeline) and `python scripts/report_ab.py` (paired, one pinned model). Both need fresh quotas, see `docs/NEXT_STEPS.md`.

## Known limits

- Free tiers: daily and per-minute quotas stop long runs and force fallbacks to slower models (a repair pass once took 112 s on a fallback). A pipeline run is about 7 model calls.
- Vision: the local model takes 9 to 17 s per image once loaded and 70 to 90 s for the first call. Benchmarks use 12 stand-in images, one reader's ground truth and 2 to 3 runs, so a difference of one call is not a difference. The model sometimes echoes the report text as observations (the image-only prompt v2 had none in 24 calls), flags a blurred or dark image in only about half of the calls, and always misses the flood on the satellite image. No second local vision model has been benchmarked (`gemma3:4b` was pulled, never benchmarked and removed on 2026-10-18 to free disk).
- Results vary between runs: the same incident gave severity high, moderate, high and undetermined in four console runs; the report agent on one fallback model sometimes returns a truncated JSON, which the repair pass fixes or the workflow discards.
- Fire guidance is limited (FI-01 says what the knowledge base does not cover); coverage is capped at partial for fire when FI-01 is retrieved. Tunisian guidance is one news report of an ONPC communique.
- French translations by the team are not reviewed by an outside reader: FI-21 to FI-26, FL-27 to FL-33, ST-27 to ST-32. The new French entries also pull French queries towards themselves; the language balance in `/search` keeps the other language in the list, at ranks 4 and 5. Four OCR-only flood pages were not re-verified on the last QA run.
- The guardrails are regular expressions and only catch what they test.
- The severity scale (low, moderate, high, critical, undetermined) is a working scale of this prototype, not an official standard.

## Documents

- `docs/EVIDENCE_LOG.md` what was run, results, failures, limitations (every number comes from here)
- `docs/SPRINT_STATUS.md`, `docs/SPRINT_PLAN.md`, `docs/NEXT_STEPS.md` plan and status
- `docs/BOTTLENECKS.md` bottlenecks and proposed fixes
- `docs/VISION_ARCHITECTURE.md` the vision architecture: single call, local model, the three-view option and why it is off
- `docs/N8N_WORKFLOW_PLAN.md`, `docs/CONTRACT_MISMATCHES.md`, `docs/RAG_CORPUS_PLAN.md`
- `docs/PROMPT_LIBRARY.md` the prompt library: roles, techniques, before and after examples, failure cases
- `prompts/README.md` data contract between agents, `prompts/CHANGELOG.md` prompt iterations
- `vision/test_images/SOURCES.md`, `rag/corpus/SOURCES.md` licences and sources

## Evidence rules

Every number in the report and slides must come from a run we logged. Results from the MOCK Gemini or the replay webhook are labelled MOCK and say nothing about model quality. A prompt version is never edited after it has been tested: write the next version and a CHANGELOG entry with the failing input. For a change that is meant to improve a measure, the pass rule and a held-out set are written before the run.

## Team

| Member | Main role |
|---|---|
| _Name_ | Architecture and coordination |
| _Name_ | RAG (corpus, chunking, retrieval evaluation) |
| _Name_ | Multi-agent system and n8n integration |
| _Name_ | Prompt engineering |
| Jihen Troudi | _role_ |
| _Name_ | Multimodality (vision) |

Everyone must be able to explain every part of the system.

## Credits

Originally developed in [aminbaccari/DisasterDL](https://github.com/aminbaccari/DisasterDL) (branch `n8n-workflow`). The commit history is kept here. Test images are CC BY with attribution in `vision/test_images/SOURCES.md`, and corpus sources are listed in `rag/corpus/SOURCES.md`.
