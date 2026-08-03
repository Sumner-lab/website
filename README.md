# Sumner Lab website

This repo holds the Sumner Lab website. It replaces our old 123reg/WordPress hosting — the site is now hosted for free on GitHub Pages.

## What's here (phase 1)

This is a straight copy of the old WordPress site: every page saved as plain HTML, with all the images and styling, pulled directly from the live site. There's no WordPress, database, or admin login behind it anymore — GitHub just serves these files as they are.

**Phase 2 (planned):** convert the pages to Markdown, which will be much easier to read and edit than raw HTML. Editing instructions will follow once that's done.

## Previewing the site

To see the site on your own computer:

```bash
python3 -m http.server 8000
```

Then open `http://localhost:8000` in a browser.

## Sharing a preview with someone outside the team

Some links on the site use absolute paths (e.g. `/our-group/`), so just double-clicking `index.html` won't navigate correctly — it needs to be served, not opened directly as a file. Two easy ways to hand someone a working preview:

**Zip it and have them run the same local server:**

```bash
zip -r site-preview.zip . -x ".git/*"
```

Send the zip. They unzip it, run `python3 -m http.server 8000` from inside the folder, and open `http://localhost:8000`.

**Or get them an actual link, no download needed:** drag the folder onto [app.netlify.com/drop](https://app.netlify.com/drop) — it publishes it and gives you a public URL in seconds, no account required. These are temporary unless claimed with a free Netlify account, so it's best for a quick look rather than a permanent link.

## Status

- [x] Site content copied over
- [ ] GitHub Pages switched on with our domain
- [ ] DNS updated so sumnerlab.co.uk points here
- [ ] HTTPS confirmed working
