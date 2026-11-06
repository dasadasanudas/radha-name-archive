# Radha.name archive (runs on your own PC)

Public repo. It holds the archiver code and progress notes only. Downloaded documents are saved to a folder on your PC, not to GitHub, so the 40 GB library never hits GitHub's size limits.

**Why your PC:** GitHub's own machines were refused (HTTP 403) by Radha.name, while a normal browser connection works. A self-hosted runner uses your connection.

`archiver.py --mode index` finds pages and file links (respects robots.txt for pages, waits 10 s between pages, skips refused pages, stops after 3 refusals in a row). `--mode download` saves files under `/sites/default/files/documents/` to your folder, 3 s apart, skips what is already saved, and stops if the site returns a challenge page or rate-limits. Nothing tries to bypass a challenge.

Note: the site's robots.txt disallows crawlers in `/sites/`, where all documents live. The site itself invites downloads. Downloading is your explicit choice.

Status files: `crawl-manifest.json` (pages, queue, refusals) and `download-summary.json` (counts). A queue or counts below the site's claimed 8,000 items means incomplete.

The workflow template is in `workflow-template/self-hosted.yml` until it is moved into `.github/workflows/`.
