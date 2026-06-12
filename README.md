# FileOrganizer AI

A local Python application that scans a folder, classifies and analyzes files using local AI (Ollama), stores metadata in SQLite, and exposes a professional Flask web UI. Runs 100% offline on Windows.

## Requirements

- Python 3.10+
- [Ollama](https://ollama.com) running locally with the required models:

```bash
ollama pull qwen3:8b            # document analysis + chat responses
ollama pull qwen2.5-coder:7b    # Text-to-SQL (natural language search)
```

## Setup

```bash
pip install -r requirements.txt
python main.py
```

Opens automatically at http://localhost:5000

## Features

- Recursive file scan with extension-based classification
- AI-powered document analysis (PDF, DOCX, TXT, XLSX, CSV) via Ollama
- Incremental scan — only re-processes new or modified files
- Duplicate detection via selective BLAKE2b hashing
- 7 automated recommendation rules
- Natural language file search via Text-to-SQL chat
- Real-time scan progress with ETA (Server-Sent Events)
- Full backup and undo system for all file operations
- Professional dark-mode web UI

## Configuration

All settings can be overridden with environment variables (prefix `FORG_`):

| Variable | Default | Description |
|---|---|---|
| `FORG_OLLAMA_BASE` | `http://localhost:11434/api` | Ollama API base URL |
| `FORG_OLLAMA_TIMEOUT` | `180` | Request timeout in seconds |
| `FORG_ANALYSIS_MODEL` | `qwen3:8b` | Model for document analysis |
| `FORG_SQL_MODEL` | `qwen2.5-coder:7b` | Model for Text-to-SQL |
| `FORG_RESPONSE_MODEL` | `qwen3:8b` | Model for chat answers |
| `FORG_DB_PATH` | `data/catalogo.db` | SQLite database path |

Example — use a larger model for better analysis:

```bash
FORG_ANALYSIS_MODEL=qwen3:30b python main.py
```

## CLI usage

```bash
python main.py              # start web UI (default)
python main.py scan PATH    # incremental scan from CLI
```
