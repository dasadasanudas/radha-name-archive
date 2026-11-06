# Radha.name archive: bounded pilot

This PUBLIC repository runs a small feasibility test, not a full mirror. All committed files and the crawl index are visible to everyone.

The approved pilot downloads exactly three documents: *Divisions Of Devotion*, *Nityananda Charitamrita*, and *Japa Tips*. It checks file signatures and records SHA-256 hashes. The crawler discovers links, but **does not download additional discovered files**. One manually dispatched run checks up to 20 pages by default and resumes the saved queue on later runs. A cap of 40 pages per run limits CI time.

It obeys the current robots rules for discovered pages, observes a minimum 10-second delay, stays on radha.name, and stops on HTTP 401/403/429. The three individually approved test documents are direct URLs in `/sites/`, which the site's robots file disallows for crawlers. Do not treat the discovery index as permission to fetch those URLs automatically.

Results: `documents/` and `crawl-manifest.json`. `crawl_status: partial` means the queue was not exhausted; even an exhausted known queue does not prove all site content was found. Failed requests and source URLs are recorded. This is not an analysis of the documents.

The site's stated rights remain with Radha.name or the respective owners. This public repo republishes the pilot files, so review rights before distributing or expanding it. GitHub-hosted Actions are subject to GitHub's terms and usage limits.
