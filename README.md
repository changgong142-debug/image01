# Background Removal Service

A full-stack application for removing image backgrounds using the [rembg](https://github.com/danielgatis/rembg) ONNX models. The backend exposes a FastAPI service that performs the background removal work, and the frontend provides a drag-and-drop experience for single or batch processing.

## Table of Contents
- [Overview](#overview)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Initial Setup](#initial-setup)
  - [Create & Activate a Virtual Environment](#create--activate-a-virtual-environment)
  - [Install Backend Dependencies](#install-backend-dependencies)
  - [Install Frontend Dependencies](#install-frontend-dependencies)
- [rembg Model Download](#rembg-model-download)
- [Running the Application](#running-the-application)
  - [Start the Backend](#start-the-backend)
  - [Launch the Frontend UI](#launch-the-frontend-ui)
- [Usage](#usage)
  - [Single Image Upload](#single-image-upload)
  - [Batch Upload](#batch-upload)
  - [Progress & Downloads](#progress--downloads)
  - [API Examples](#api-examples)
- [Configuration & Environment Variables](#configuration--environment-variables)
- [Troubleshooting](#troubleshooting)
- [Future Enhancements & Deployment Notes](#future-enhancements--deployment-notes)

## Overview
The service accepts PNG, JPG, JPEG, and WebP images, removes the background from each asset, and returns transparent PNGs. Typical use cases include e-commerce photography, profile pictures, and quick graphics prototyping. The backend is optimized for CPU-first inference but can be configured to leverage GPU acceleration if available.

## Architecture
- **Backend**: FastAPI running on Uvicorn, exposing REST endpoints for single and batch removals.
- **Background removal**: Powered by the `rembg` library and ONNX runtime. Models are automatically cached after the first download.
- **Frontend**: A React (Vite) single-page application that communicates with the backend via REST.
- **Storage**: Files are held in memory or a temporary directory during processing; no persistent storage is required by default.

```
client -> frontend UI -> FastAPI API -> rembg model -> processed image download
```

## Prerequisites
Ensure you have the following installed before continuing:

| Tool | Version | Notes |
|------|---------|-------|
| Python | 3.10+ | Required for the backend service. |
| pip | 22+ | Ships with Python; upgrade if needed. |
| Node.js | 18+ | Required for the frontend (Vite) tooling. |
| npm | 9+ | Installed with Node.js; yarn/pnpm also work if preferred. |
| virtualenv (optional) | latest | Recommended for isolated Python environments. |

If you plan to use GPU acceleration with ONNX runtime, install the appropriate CUDA drivers beforehand.

## Initial Setup
Clone the repository and move into the project root:

```bash
git clone <repo-url>
cd <repo-root>
```

The repository follows a two-folder layout:

```
backend/    # FastAPI app, requirements.txt, and model utilities
frontend/   # React/Vite UI
```

### Create & Activate a Virtual Environment

```bash
python -m venv .venv
# macOS/Linux
source .venv/bin/activate
# Windows (PowerShell)
.venv\Scripts\Activate.ps1
```

Each time you work on the backend, reactivate the virtual environment.

### Install Backend Dependencies

```bash
pip install --upgrade pip
pip install -r backend/requirements.txt
```

If you need developer tooling (linting, formatting, pre-commit hooks), install extras defined in `backend/requirements-dev.txt`.

### Install Frontend Dependencies

```bash
cd frontend
npm install
# optional: npm run lint
cd ..
```

## rembg Model Download
The first time `rembg` runs it downloads the default **U2NET** model (~169MB) into your user cache (usually `~/.u2net`). To pre-seed the model cache:

```bash
python -c "from rembg import session_factory; session_factory.new_session(model='u2net')"
```

You can force a specific model at runtime by setting `REMBG_MODEL_NAME` (see [Configuration & Environment Variables](#configuration--environment-variables)). The following models are supported out of the box: `u2net`, `u2netp`, `u2net_human_seg`, `isnet-general-use`, and `sam`. Custom `.onnx` models can be used by pointing to the file path.

> **Note:** Model downloads require an active internet connection. If the download fails, check firewall/proxy settings and retry.

## Running the Application

### Start the Backend

From the project root (with your virtual environment activated):

```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

- `--reload` enables hot reloading in development.
- Adjust `--host`/`--port` to match your deployment environment.
- For production, drop `--reload` and consider a process manager such as `gunicorn` or `uvicorn` with `--workers`.

Once started, the API docs are available at:
- Swagger UI: <http://localhost:8000/docs>
- ReDoc: <http://localhost:8000/redoc>

### Launch the Frontend UI

In a separate terminal:

```bash
cd frontend
npm run dev -- --host
```

Vite exposes the UI on <http://localhost:5173> by default. When the backend and frontend run locally, the frontend proxy forwards API calls to `http://localhost:8000`. To point to a different backend endpoint, set `VITE_API_BASE_URL` before starting the dev server:

```bash
VITE_API_BASE_URL="https://your-backend-url" npm run dev -- --host
```

To build the production bundle:

```bash
npm run build
npm run preview
```

Front-end static assets can be deployed behind any static host (S3, Netlify, Vercel, etc.).

## Usage

### Single Image Upload
1. Open the frontend UI (<http://localhost:5173>).
2. Drag & drop an image onto the drop zone or click **Browse** to select a file.
3. The backend queues the task, and the UI displays a progress indicator ("Processing…").
4. When complete, the output preview replaces the original background with transparency.
5. Click **Download PNG** to save the processed file locally.

Processing time usually ranges from 1–3 seconds for standard 1024×1024 images on CPU. Larger images or low-powered machines may take longer.

### Batch Upload
1. Select multiple images (Shift/Cmd-click) or drop an entire folder.
2. The UI uploads each file individually and shows per-file progress.
3. Completed files can be downloaded one-by-one or as a zipped archive using the **Download All** button.
4. Failed items (e.g., unsupported formats) appear in the error list with suggested fixes.

Batch jobs process sequentially by default; set `BATCH_CONCURRENCY` to increase parallelism (see [Configuration](#configuration--environment-variables)).

### Progress & Downloads
- A global progress bar reflects the overall batch status.
- Individual tiles display `Queued`, `Processing`, `Completed`, or `Failed` badges.
- Downloads are streamed directly from the backend to avoid storing outputs on the server.
- Use the **Download JSON** option (if enabled) to retrieve metadata (dimensions, processing time, model used).

### API Examples
If you prefer direct API access (useful for automation), here are sample commands:

```bash
# Single file
curl -X POST "http://localhost:8000/api/remove" \
  -H "accept: application/octet-stream" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@/path/to/photo.jpg" \
  --output output.png

# Batch request (zip archive)
curl -X POST "http://localhost:8000/api/remove/batch" \
  -H "accept: application/zip" \
  -F "files=@/path/to/images.zip" \
  --output processed.zip
```

Endpoints return standard HTTP error codes (`400` for invalid files, `422` for validation errors, `500` for unexpected failures).

## Configuration & Environment Variables
Configure the service by creating a `.env` file in `backend/` or exporting variables before runtime.

| Variable | Purpose | Default |
|----------|---------|---------|
| `REMBG_MODEL_NAME` | Base model to load (`u2net`, `isnet-general-use`, etc.). | `u2net` |
| `REMBG_SESSION_PATH` | Override the location of cached models. | Auto-detected user cache |
| `MAX_IMAGE_SIZE_MB` | Reject files larger than this threshold. | `25` |
| `ALLOWED_EXTENSIONS` | Comma-delimited whitelist (e.g., `png,jpg,jpeg,webp`). | `png,jpg,jpeg,webp` |
| `BATCH_CONCURRENCY` | Number of parallel background removal workers. | `2` |
| `BACKEND_URL` | Base URL the frontend targets. | `http://localhost:8000` |
| `VITE_API_BASE_URL` | Frontend build-time override for API requests. | same as `BACKEND_URL` |
| `LOG_LEVEL` | Logging verbosity (`info`, `debug`, `warning`). | `info` |

You can load these with `python-dotenv` (add to requirements if not already present) or your process manager.

## Troubleshooting

| Symptom | Cause | Resolution |
|---------|-------|------------|
| `Model u2net not found` | The rembg model cache is empty or corrupted. | Run `python -m rembg --version` to trigger a download, or manually fetch models into `~/.u2net`. Verify permissions on the cache directory. |
| `HTTP 400: Unsupported file type` | File extension or MIME type is not in `ALLOWED_EXTENSIONS`. | Convert the image to PNG/JPG/WebP or update the allow-list via `ALLOWED_EXTENSIONS`. |
| `HTTP 413: Request Entity Too Large` | Uploaded file exceeds the allowed payload size. | Increase `MAX_IMAGE_SIZE_MB` or compress images before uploading. |
| `Uvicorn ERROR: address already in use` | Port 8000 (or 5173 for the frontend) is occupied. | Stop the conflicting process (`lsof -i :8000`), or start the service on a different port (`--port 8001`). |
| `rembg` download is slow | Network throttling or firewall restrictions. | Pre-download models using a machine with faster access, then copy the `.onnx` files to the cache directory. |
| Frontend cannot reach backend | CORS or proxy misconfiguration. | Set `BACKEND_URL`/`VITE_API_BASE_URL` consistently and ensure the backend has CORS enabled for the frontend origin. |

## Future Enhancements & Deployment Notes
- **Containerization**: Provide Dockerfiles for the backend and frontend; build multi-stage images to cache models inside the container.
- **Queue/Worker Model**: Use Redis + RQ/Celery to handle large batch uploads, improving scalability and resilience.
- **GPU Support**: Ship optional ONNX runtime GPU builds and auto-detect GPU availability.
- **Observability**: Integrate structured logging (JSON), metrics via Prometheus, and tracing to monitor performance.
- **Authentication**: Add API keys or OAuth for multi-tenant environments.
- **Deployment Targets**: The backend is suitable for serverless (Azure Functions, AWS Lambda with container image), but ensure cold-start friendly models or warm the cache. For traditional servers, use systemd, Docker Compose, or Kubernetes.
- **CDN for Assets**: Serve processed outputs through a CDN when hosting high-volume workloads.

For production rollouts, remember to:
- Enable HTTPS (behind a reverse proxy such as Nginx or Traefik).
- Configure environment-specific `.env` files and secrets management.
- Set up periodic cache pruning or disk monitoring for temporary directories.

---

If you encounter issues not covered here, please open a GitHub issue with logs (`backend/logs/app.log` if enabled) and reproduction steps.
