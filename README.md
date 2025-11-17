# AI Manako Tika - Legislative RAG System

A Retrieval-Augmented Generation (RAG) system designed to provide semantic search capabilities over Cook Islands legislation and regulations.

## Overview

This project demonstrates the practical application of agentic AI tools as a human-computer interface, emphasizing:

- **Semantic Search**: Natural language querying of legislative documents
- **RAG Architecture**: Vector embeddings and retrieval for accurate, contextual responses
- **Human-in-the-Loop**: AI-assisted development with strategic human oversight
- **Rapid Prototyping**: Demonstrating accelerated development cycles through AI tooling

## Project Name

"Manako Tika" is Cook Islands Māori for "to search correctly" or "accurate vision" - reflecting the project's goal of providing precise access to legislative information.

## Technology Stack

### Backend
- **FastAPI**: Modern async web framework
- **OpenAI**: GPT-5.1 for chat, text-embedding-3-large for embeddings
- **OpenRouter**: Qwen2-VL for OCR of scanned PDFs
- **FastMCP**: Model Context Protocol server for RAG tools
- **JSONL**: Vector storage (with Qdrant migration planned)

### Document Processing
- **Playwright**: Web scraping for legislation downloads
- **pypdf**: Text extraction from PDFs
- **pdf2image**: PDF to image conversion
- **BeautifulSoup**: HTML parsing

### Frontend
- **WebSocket**: Real-time streaming chat
- **Vanilla JS**: Lightweight, no-build interface
- **Responsive CSS**: Mobile-friendly design

### Deployment
- **Docker**: Containerization
- **GitHub Actions**: CI/CD pipeline
- **Watchtower**: Automatic container updates
- **TrueNAS**: Self-hosted infrastructure

## Features

- ✅ **Semantic Search**: Natural language queries over legislation
- ✅ **OCR Support**: Process both text-based and scanned PDFs
- ✅ **Hierarchical Chunking**: Preserves legal document structure (Acts > Parts > Sections)
- ✅ **Real-time Chat**: WebSocket streaming with GPT-5.1
- ✅ **Function Calling**: Automatic RAG tool invocation
- ✅ **Web Scraping**: Automated legislation downloads
- ✅ **MCP Integration**: Extensible tool ecosystem
- ✅ **Docker Deployment**: One-command production setup

## Quick Start

### Prerequisites
- Docker and Docker Compose
- OpenAI API key
- OpenRouter API key (for OCR)

### 1. Clone and Configure

```bash
git clone https://github.com/mossly/ai-manako-tika.git
cd ai-manako-tika

# Create environment file
cp .env.example .env
```

### 2. Edit `.env` with your API keys

```bash
OPENAI_API_KEY=sk-your-openai-key-here
OPENROUTER_API_KEY=sk-or-your-openrouter-key-here
APP_SECRET=your-random-secret-key
API_KEY=your-api-key-for-admin-endpoints
```

### 3. Start the service

```bash
# Build and run locally
docker-compose up -d

# OR pull from GitHub Container Registry (production)
docker-compose -f docker-compose.ghcr.yml up -d
```

### 4. Access the application

- **Web Interface**: http://localhost:1905/chat
- **Status Page**: http://localhost:1905/
- **Health Check**: http://localhost:1905/health
- **MCP Server**: http://localhost:1905/mcp

## Usage

### Ingesting Legislation

#### Option 1: Scrape and Ingest Automatically

```bash
# Scrape legislation from government websites
curl -X POST http://localhost:1905/scrape \
  -H "Authorization: Bearer YOUR_API_KEY"

# Ingest all downloaded PDFs
curl -X POST http://localhost:1905/ingest/all \
  -H "Authorization: Bearer YOUR_API_KEY"
```

#### Option 2: Ingest from URL

```bash
curl -X POST http://localhost:1905/ingest/url \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "url=https://example.com/banking_act.pdf" \
  -F "act_name=Banking Act 1996"
```

#### Option 3: Ingest Local PDF

```bash
curl -X POST http://localhost:1905/ingest/pdf \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "pdf_path=/data/legislation/banking_act_1996.pdf" \
  -F "act_name=Banking Act 1996"
```

### Querying Legislation

Visit http://localhost:1905/chat and ask questions like:

- "What are the capital requirements for banks?"
- "Tell me about licensing requirements in the Banking Act"
- "What does the law say about corporate governance?"

### MCP Integration

The service exposes MCP tools that can be used by Claude Desktop or other MCP clients:

```json
{
  "mcpServers": {
    "cook-islands-legislation": {
      "url": "http://localhost:1905/mcp"
    }
  }
}
```

**Available Tools**:
- `search_legislation_tool`: Semantic search over legislation
- `get_legislation_stats`: Get RAG store statistics

## Project Structure

```
ai-manako-tika/
├── app/
│   ├── main.py                 # FastAPI application
│   ├── mcp_server.py           # MCP tool definitions
│   ├── config.py               # Configuration management
│   ├── rag/
│   │   ├── indexer.py          # RAG store and embeddings
│   │   └── chunking.py         # Legal document chunking
│   ├── tools/
│   │   ├── scraper.py          # Web scraping for legislation
│   │   ├── pdf_processor.py   # PDF processing and OCR
│   │   └── ingest.py           # Ingestion pipeline
│   ├── templates/
│   │   └── chat.html           # Web chat interface
│   └── static/
│       ├── app.js              # Frontend JavaScript
│       └── style.css           # Styles
├── Dockerfile                  # Docker image definition
├── docker-compose.yml          # Local development
├── docker-compose.ghcr.yml     # Production (GHCR pull)
├── requirements.txt            # Python dependencies
├── .env.example                # Environment variables template
├── ROADMAP.md                  # Future enhancements
└── README.md                   # This file
```

## Development

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Run development server
uvicorn app.main:app --reload --port 8080
```

### Testing

```bash
# Health check
curl http://localhost:1905/health

# Get RAG statistics
curl http://localhost:1905/stats

# Test ingestion
curl -X POST http://localhost:1905/ingest/pdf \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "pdf_path=/path/to/test.pdf" \
  -F "act_name=Test Act 2024"
```

## Deployment to TrueNAS

### 1. SSH into TrueNAS

```bash
ssh claude-truenas
```

### 2. Create application directory

```bash
sudo mkdir -p /mnt/Machina/apps/ai-manako-tika
cd /mnt/Machina/apps/ai-manako-tika
```

### 3. Create `.env` file with production credentials

### 4. Create `docker-compose.ghcr.yml` (copy from repo)

### 5. Start the service

```bash
sudo docker-compose -f docker-compose.ghcr.yml up -d
```

### 6. Configure Cloudflare Tunnel

Set up tunnel to expose at https://ai.manakotika.co.ck (following ntfy pattern from CLAUDE.md)

### 7. Watchtower Auto-Updates

The service is configured with watchtower labels. It will automatically pull and update when new images are pushed to GHCR.

## CI/CD Pipeline

The project uses GitHub Actions for automated builds:

1. Push to `main` branch
2. GitHub Actions builds Docker image
3. Publishes to `ghcr.io/mossly/ai-manako-tika:latest`
4. Watchtower on TrueNAS pulls new image
5. Container restarts automatically

## Purpose

This serves as a practical demonstration of how AI can:
- Abstract away lower-level operational complexity
- Enable rapid prototyping and deployment
- Provide domain-specific knowledge access through natural language interfaces
- Maintain governance through version control and CI/CD practices

## Development Approach

The project showcases end-to-end AI-assisted development, from initial architecture through deployment, while maintaining human oversight for strategic decisions and architectural choices.

## Roadmap

See [ROADMAP.md](ROADMAP.md) for planned enhancements including:
- Migration from JSONL to Qdrant vector database
- Hybrid search (semantic + keyword)
- OAuth/SAML authentication
- Multi-jurisdiction support
- Analytics dashboard

## License

This is a demonstration project for Bank of the Cook Islands. All rights reserved.

## Contact

**Aaron 'Mossly' Moss**
Systems Analyst Programmer
Bank of the Cook Islands

---

*This is a demonstration project exploring the intersection of AI, governance, and rapid application development.*
