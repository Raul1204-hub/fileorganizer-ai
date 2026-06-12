# FileOrganizer AI — Claude Code Context

## What this project is
A local Python application that scans a user-defined folder, classifies and 
analyzes files using local AI (Ollama), stores metadata in SQLite, and exposes 
a professional Flask web UI. No external APIs. Runs 100% offline on Windows.

## Tech stack
- Python 3.10+ on Windows (pathlib.Path for all paths)
- Ollama at http://localhost:11434
  - qwen3:30b → document analysis, tagging, recommendations
  - qooba/qwen3-coder-30b-a3b-instruct → Text-to-SQL, chat responses
- SQLite (built-in sqlite3) → data/catalogo.db
- Flask → web UI at localhost:5000
- pdfplumber → PDF text extraction
- python-magic-bin → magic byte file detection (Windows DLLs included)
- hashlib → MD5 duplicate detection

## Module responsibilities
- main.py: orchestrator, CLI entry point
- scanner.py: recursive scan, extension classification, MD5 hashing
- analyzer.py: text extraction + Ollama content analysis (Documentos only)
- organizer.py: propose moves → user approval → execute → log backup
- database.py: ALL SQLite reads/writes, schema creation
- recommendations.py: 7 automated recommendation rules
- chat.py: Text-to-SQL pipeline, safety filter, natural language response
- web/app.py: Flask routes, opens browser automatically on start

## Key rules
- NEVER move or delete files without explicit user approval (Y/N prompt or web button)
- ALWAYS save backup record before any file operation (tabla: backup_operaciones)
- ALL AI inference goes through Ollama local API, never external APIs
- SQL safety: chat.py only allows SELECT statements, blocks DROP/DELETE/UPDATE/INSERT
- All paths use pathlib.Path — never hardcoded slashes
- Use python-magic-bin, not python-magic

## Database tables
archivos, categorias, etiquetas, historial, recomendaciones, 
chat_historial, backup_operaciones

## UI design principles
- Professional, modern, friendly dark-mode capable interface
- Sidebar navigation, card-based layouts, color-coded categories
- Tailwind CSS via CDN for styling
- Every destructive action requires confirmation modal
- Backup/undo always visible and accessible

## Git / GitHub
- Repo: to be configured by user at setup
- .gitignore excludes: data/catalogo.db, __pycache__/, *.pyc, venv/, .env
- data/catalogo.db is personal data — never committed
