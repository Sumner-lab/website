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

## Status

- [x] Site content copied over
- [ ] GitHub Pages switched on with our domain
- [ ] DNS updated so sumnerlab.co.uk points here
- [ ] HTTPS confirmed working
