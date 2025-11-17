# AI Manako Tika - Roadmap

This document tracks future enhancements and feature requests for the Cook Islands Legislation RAG system.

## Current Status (MVP - v1.0)

✅ PDF processing pipeline with OCR (Qwen via OpenRouter)
✅ Legislation chunking with hierarchical structure
✅ Vector embeddings with OpenAI text-embedding-3-large
✅ JSONL-based vector storage
✅ MCP server for RAG tools
✅ Web chat interface with GPT-5.1
✅ Docker deployment with CI/CD via GitHub Actions
✅ WebSocket streaming for real-time responses
✅ Automated web scraping for legislation downloads

## Planned Enhancements

### High Priority (Post-Demo)

#### Vector Database Migration
- [ ] **Migrate from JSONL to Qdrant**
  - Rationale: Better performance, metadata filtering, production scalability
  - Requirements: Docker setup, migration script
  - Timeline: 1-2 weeks post-demo
  - Benefits:
    - Advanced filtering (by act, date, section type)
    - Faster similarity search at scale
    - Better memory management
    - Production-ready architecture

#### Enhanced Search Capabilities
- [ ] **Hybrid search (semantic + keyword)**
  - BM25 keyword search combined with vector similarity
  - Better handling of specific section numbers and legal citations
  - Fallback for rare legal terminology

- [ ] **Cross-reference detection**
  - Automatically link related sections
  - Show "See also" suggestions
  - Build citation graph

#### Authentication & Access Control
- [ ] **OAuth/SAML integration**
  - Single sign-on for BCI staff
  - Role-based access control
  - Audit logging for compliance

### Medium Priority

#### Data & Content
- [ ] **Automated incremental updates**
  - Weekly cron job to scrape new legislation
  - Detect and re-process amended acts
  - Email notifications for new content

- [ ] **Multi-jurisdiction support**
  - Add support for Pacific Island countries
  - Regional legal search
  - Comparative legislation analysis

- [ ] **Case law integration**
  - Scrape Pacific Islands Legal Information Institute (PacLII)
  - Link acts to relevant court decisions
  - Precedent search

#### User Experience
- [ ] **Advanced chat features**
  - Conversation history persistence
  - Export chat transcripts to PDF
  - Share search results via URL
  - Bookmark favorite sections

- [ ] **Mobile app**
  - Native iOS/Android apps
  - Offline access to cached legislation
  - Push notifications for amendments

- [ ] **Multilingual support**
  - Cook Islands Māori translation
  - English/Māori toggle
  - Bilingual search

#### Analytics & Insights
- [ ] **Usage analytics dashboard**
  - Most searched topics
  - User engagement metrics
  - Popular legislation sections
  - Query patterns analysis

- [ ] **Query quality feedback**
  - Thumbs up/down on responses
  - Report inaccuracies
  - User feedback loop for improvement

### Low Priority / Future Research

#### Advanced AI Features
- [ ] **Fine-tuned legal LLM**
  - Train custom model on Pacific legal corpus
  - Better understanding of local legal terminology
  - Lower API costs

- [ ] **Summarization tools**
  - Automatic act summaries
  - "Explain like I'm 5" mode
  - Key changes in amendments

- [ ] **Legal drafting assistant**
  - Template generation for common documents
  - Citation style enforcement
  - Consistency checking

#### Infrastructure
- [ ] **Local LLM deployment**
  - Self-hosted Llama 3 or similar
  - Reduce OpenAI API dependency
  - Data sovereignty compliance

- [ ] **Distributed RAG**
  - Multiple vector stores for different content types
  - Routing layer for specialized retrievers
  - Ensemble ranking

- [ ] **Real-time collaboration**
  - Multi-user chat rooms
  - Shared research sessions
  - Annotations and notes

#### Compliance & Governance
- [ ] **Data retention policies**
  - Configurable chat history retention
  - GDPR/privacy compliance tools
  - Data anonymization

- [ ] **Audit trail**
  - Complete query logging
  - Access logs for compliance
  - Change tracking for embedded content

## Feature Requests Log

### Submitted by Users
- None yet (system just launched)

## Completed Features

### v1.0 (MVP - Current)
- ✅ Core RAG pipeline
- ✅ Web chat interface
- ✅ Docker deployment
- ✅ CI/CD automation
- ✅ OCR support
- ✅ Web scraping
- ✅ MCP server integration

## Version History

### v1.0.0 (2024-XX-XX)
- Initial release for BCI Board Strategy Day demo
- Basic legislation search and chat functionality
- WebSocket streaming interface
- Automated PDF processing with OCR

---

## Contributing to the Roadmap

To suggest new features or modifications:
1. Create an issue on GitHub with the `enhancement` label
2. Describe the use case and expected benefits
3. Tag with priority level (high/medium/low)
4. Board approval required for high-priority features

## Contact

For questions about the roadmap, contact:
- Aaron 'Mossly' Moss - Systems Analyst Programmer, BCI
- Email: [your-email]@bci.co.ck
