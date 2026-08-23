# Sumner Lab website

This repo holds the Sumner Lab website, live at **[sumner-lab.github.io/website](https://sumner-lab.github.io/website/)**. It replaced our old 123reg/WordPress hosting and is hosted for free on GitHub Pages.

The site is built as Markdown pages on Jekyll, with one shared template, so editing a page means editing a short Markdown file, and a nav change happens in one place instead of being duplicated across hundreds of files. The original straight-HTML copy of the old WordPress site (working, but with every page's nav/header duplicated in every file) is archived on the [`old_web_format`](https://github.com/Sumner-lab/website/tree/old_web_format) branch.

## Previewing the site

This branch is *source*, not a built website — Jekyll needs to compile the Markdown + templates into HTML before there's anything to view in a browser. One-time setup, then a normal preview command:

```bash
bundle install          # one-time, installs Jekyll and plugins
bundle exec jekyll serve
```

Then open `http://localhost:4000`. Leave it running — it rebuilds automatically as you save files.

Needs Ruby + [Bundler](https://bundler.io/) installed (`gem install bundler` if you don't have it).

## Editing

- **A page** (Contact, a research theme, etc.): edit its `.md` file directly — e.g. `contact.md`, `research/evolution.md`.
- **A blog post**: add a file to `_posts/`, named `YYYY-MM-DD-title.md`.
- **A team member**: add a file to `_people/`, with `name`, `role`, `status` (`current` or `alumni`) and `photo` in the front matter at the top of the file.
- **The nav menu**: edit `_data/nav.yml` — one file, applies everywhere.
- **Images**: drop them anywhere under `wp-content/uploads/`, reference with a relative path.

Preview locally before pushing. GitHub Actions rebuilds and redeploys automatically on every push to `main` (see `.github/workflows/pages.yml`).

## Sharing a preview with someone outside the team

Since this branch is unbuilt source, you can't just zip the repo and hand it over the way phase 1 worked — there'd be nothing to look at without Jekyll installed. Instead:

```bash
./bin/package-preview.sh
```

This builds the site and produces `sumnerlab-preview.zip` — the actual rendered pages, images and all, no Ruby/Jekyll needed to view it. Send that zip. They unzip it, run `python3 -m http.server 8000` from inside the folder, and open `http://localhost:8000`.

For a real link instead of a download (no account needed): after running the script, drag the unzipped folder onto [app.netlify.com/drop](https://app.netlify.com/drop). These are temporary unless claimed with a free Netlify account.

The zip is large (~160MB) because it includes every image on the site — fine for Netlify Drop or a cloud drive link, too big for most email attachments.

## Status

- [x] Jekyll scaffold + shared template (fixes phase 1's duplicated-nav problem)
- [x] A representative slice converted and padded out for design review (homepage, 5 people, 3 posts, several research/outreach pages)
- [ ] Remaining ~120 pages/posts/people batch-converted
- [x] Merged into `main`
- [ ] GitHub Pages switched on with our domain
- [ ] DNS updated so sumnerlab.co.uk points here
- [ ] HTTPS confirmed working
