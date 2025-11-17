# TrueNAS Deployment Guide

This guide covers deploying the Cook Islands Legislation RAG service on TrueNAS using Docker.

## Prerequisites

- TrueNAS with Docker/Kubernetes support
- Pinecone account with an index created
- OpenAI API key
- OpenRouter API key (for OCR processing)

## Memory Requirements

With Pinecone handling vector storage, the app is very lightweight:

- **RAM**: 250-400MB (down from 1-2.5GB with local embeddings)
- **Storage**: ~100MB for app + data directory for PDFs
- **CPU**: Minimal (1 core sufficient)

## Setup Steps

### 1. Clone Repository

```bash
git clone <your-repo-url>
cd ai-manako-tika
```

### 2. Configure Environment Variables

Copy the example env file:

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```bash
# OpenAI Configuration
OPENAI_API_KEY=sk-your-actual-key
OPENAI_EMBED_MODEL=text-embedding-3-large
OPENAI_CHAT_MODEL=gpt-5.1

# OpenRouter (for OCR)
OPENROUTER_API_KEY=sk-or-your-actual-key
OPENROUTER_OCR_MODEL=qwen/qwen-2-vl-7b-instruct

# Pinecone Configuration
PINECONE_API_KEY=your-pinecone-api-key
PINECONE_INDEX_NAME=cook-islands-legislation
PINECONE_CLOUD=aws
PINECONE_REGION=us-east-1

# Application Security
APP_SECRET=<generate-random-secret>
API_KEY=<generate-api-key>
```

### 3. Build and Run

Using docker-compose:

```bash
docker-compose up -d
```

Or build manually:

```bash
docker build -t ai-manako-tika .
docker run -d \
  --name ai-manako-tika \
  --env-file .env \
  -p 1905:8080 \
  -v $(pwd)/data:/data \
  ai-manako-tika
```

### 4. Verify Deployment

Check the service is running:

```bash
curl http://localhost:1905/health
```

Should return:

```json
{
  "ok": true,
  "service": "cook-islands-legislation-rag",
  "chunks": 0,
  "vectors": 0
}
```

### 5. Access the Chat Interface

Open your browser to:

```
http://<truenas-ip>:1905/chat
```

## Pinecone Index Setup

The app will automatically create the Pinecone index on first run if it doesn't exist. However, you can create it manually:

1. Go to [Pinecone Console](https://app.pinecone.io/)
2. Create new index:
   - **Name**: `cook-islands-legislation`
   - **Dimensions**: 3072 (for text-embedding-3-large)
   - **Metric**: Cosine
   - **Cloud**: AWS (or your preference)
   - **Region**: us-east-1 (or your preference)

## Ingesting Data

Once the service is running, you can ingest PDFs using your other system:

1. Process PDFs and generate embeddings
2. Upsert to Pinecone directly
3. The TrueNAS deployment will query Pinecone for searches

## Monitoring

View logs:

```bash
docker logs -f ai-manako-tika
```

Check stats:

```bash
curl http://localhost:1905/stats
```

## Troubleshooting

### Container won't start

Check logs:
```bash
docker logs ai-manako-tika
```

Common issues:
- Missing environment variables
- Invalid Pinecone API key
- Port 1905 already in use

### No search results

- Verify Pinecone index has vectors: Check Pinecone console
- Check Pinecone API key is correct
- Verify index name matches configuration

### Out of memory

The app should use <400MB RAM. If using more:
- Check for memory leaks in logs
- Restart container: `docker restart ai-manako-tika`

## Updating

Pull latest changes and rebuild:

```bash
git pull
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

## Port Configuration

Default port mapping: `1905:8080`

To change the external port, edit `docker-compose.yml`:

```yaml
ports:
  - "YOUR_PORT:8080"
```

## Data Persistence

The `./data` directory is mounted as a volume and contains:

- `/data/legislation` - Downloaded PDF files
- `/data/markdown` - Extracted markdown
- `/data/config.json` - Processing configuration
- `/data/logs` - Application logs

This data persists across container restarts.

## Security Notes

- Change default `APP_SECRET` and `API_KEY` in production
- Use `SESSION_COOKIE_SECURE=true` if behind HTTPS proxy
- Restrict API endpoints with firewall rules if needed
- Keep API keys secure and never commit them to git

## Performance Optimization

For better performance:

1. **Use Pinecone's serverless tier** for automatic scaling
2. **Enable connection pooling** in Pinecone client (already configured)
3. **Use reverse proxy** (nginx/traefik) for SSL and caching
4. **Monitor Pinecone usage** to optimize costs

## Cost Estimate

Assuming moderate usage (100 queries/day):

- **Pinecone**: ~$0-5/month (serverless tier)
- **OpenAI Embeddings**: ~$0.13 per 1M tokens
- **OpenAI Chat**: Variable based on usage
- **TrueNAS**: Free (self-hosted)

Total: ~$5-20/month depending on usage
