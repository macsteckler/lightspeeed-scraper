# Lightspeed Scraper

A high-performance web scraping system for collecting and processing articles from various sources.

## Features

- Efficient link collection using Playwright and Diffbot
- Smart content extraction with fallback mechanisms
- URL canonicalization and deduplication
- Asynchronous processing with rate limiting
- Supabase integration for data storage

## Setup

1. Clone the repository:

```bash
git clone https://github.com/yourusername/lightspeeed-scraper.git
cd lightspeeed-scraper
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Set up environment variables:

```bash
cp .env.example .env
# Edit .env with your configuration
```

## Usage

The scraper consists of two main components:
- Source processor: Collects article links from source pages
- Article processor: Extracts and processes content from individual articles

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details. 