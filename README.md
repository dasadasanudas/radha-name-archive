# Radha.name archive notes

Public repo with archiver code and progress notes. No documents are stored here.

**What works:** page indexing from GitHub Actions (see `crawl-manifest.json`: pages visited, pages still queued, pages refused, candidate file links). The index is partial and its file links include site graphics.

**What does not:** downloading document files from GitHub's machines. Radha.name refused those requests with HTTP 403, most likely a bot check on file links (not confirmed). No attempt is made to bypass it.

`archiver.py` is the fixed crawler (skips refused pages, stops after 3 refusals in a row). `archive.py` and `.github/workflows/crawl.yml` are the older version and still need to be updated. `workflow-template/self-hosted.yml` needs a runner on your own PC and is unused.
