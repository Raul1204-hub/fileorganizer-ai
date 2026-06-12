# FileOrganizer AI

A local Python application that scans a folder, classifies and analyzes files using local AI (Ollama), stores metadata in SQLite, and exposes a professional Flask web UI. Runs 100% offline on Windows.

## Requirements

- Python 3.10+
- [Ollama](https://ollama.com) running locally with models:
  - `ollama pull qwen3:30b`
  - `ollama pull qooba/qwen3-coder-30b-a3b-instruct`

## Setup

```bash
pip install -r requirements.txt
python main.py
```

Opens automatically at http://localhost:5000

## Features

- Recursive file scan with extension-based classification
- AI-powered document analysis (PDF, DOCX, TXT, XLSX, CSV) via Ollama
- Duplicate detection via MD5 hashing
- 7 automated recommendation rules
- Natural language file search via Text-to-SQL chat
- Full backup and undo system for all file operations
- Professional dark-mode capable web UI
