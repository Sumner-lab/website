# Sumner Lab website

This repo holds the Sumner Lab website, live at **[www.sumnerlab.co.uk](https://www.sumnerlab.co.uk)**. It replaced our old 123reg/WordPress hosting and is hosted for free on GitHub Pages.

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
- **A blog post**: add a file to `_posts/`, named `YYYY-MM-DD-title.md`. Don't want to touch git/Markdown directly? Use the [Submit a new post](https://github.com/Sumner-lab/website/issues/new?template=new-post.yml) form instead — it opens a pull request automatically for someone to review.
- **A media appearance** (TV, radio, podcast, print, talk, prize, exhibition): add an entry to `_data/media.yml`, or use the [Submit a media appearance](https://github.com/Sumner-lab/website/issues/new?template=new-media.yml) form instead — same as above, it opens a pull request automatically.
- **A team member**: add a file to `_people/`, with `name`, `role`, `status` (`current` or `alumni`) and `photo` in the front matter at the top of the file. New lab members can use the [Add a new lab member](https://github.com/Sumner-lab/website/issues/new?template=new-member.yml) form instead — it builds their profile (photo, links and all) and opens a pull request automatically. Current members are listed alphabetically on the People page; `order:` is only needed to pin someone to the top.
- **The nav menu**: edit `_data/nav.yml` — one file, applies everywhere.
- **Images**: drop them anywhere under `wp-content/uploads/`, reference with a relative path.

Preview locally before pushing. `main` is protected: changes go in through a pull request, which needs an approval from another lab member before it can be merged. GitHub Actions rebuilds and redeploys automatically whenever `main` changes (see `.github/workflows/pages.yml`).

The social wall and visit analytics data (`_data/social_wall.json`, `_data/analytics.json`, `_data/analytics_totals.json`) are refreshed by scheduled bots on the separate `site-data` branch, since a bot can't get its changes approved. The live build always uses the `site-data` copies; the ones on `main` are only there so local previews have something to show.

## Profile pages

Each file in `_people/` is one profile, shown as a "field notebook" page (`_layouts/person.html`): a polaroid photo, a specimen-label summary, and tabs for **About**, **Research**, **Publications** and **In the media**. A tab only appears when it has something in it.

Everything goes in the front matter at the top of the file. Only `name`, `role`, `status` and `photo` are needed; leave out anything that doesn't apply.

| Field | What it's for |
|---|---|
| `name`, `role`, `photo`, `photo_position`, `links` | Header, People page card, link buttons |
| `status` | `current` or `alumni` ("Left the nest") |
| `joined` / `left`, or `stints` for more than one spell | "In the lab" years |
| `position` | Specimen label, e.g. `PhD Student` |
| `studies` | Specimen label, e.g. `Asian giant hornets` |
| `project` | Research tab |
| `themes` | Research tab, and the theme filters on the People page, e.g. `[Ecology, Genomics]` |
| `background` | Research tab: a list, one line per role, newest first. Lines starting with years (`2019–2023: …`) are drawn on the career ruler |
| `intro`, `interests`, `ask_me_about`, `other_interests`, `biography`, `contact` | About tab (Markdown) |
| `publications` (+ optional `publications_label`) | Publications tab: a list, one publication per line (Markdown) |

Media appearances fill in the **In the media** tab automatically, from entries in `_data/media.yml` that list the person under `people:`. Anything written below the front matter still shows on the About tab, so sections that don't fit a field (Teaching, Book chapters…) can stay as normal Markdown.

Older profiles were written as one block of Markdown with bold labels (`**Position:**`, `**Background**`…). `bin/convert_profiles.py` moves those into the fields above without losing any text; run `python3 bin/convert_profiles.py --check` to preview it. It skips profiles that already use the fields, so it's safe to re-run.

To see what each profile is still missing (years in the lab, career history, ORCID link, the newer fields…), run `python3 bin/profile_checklist.py`. It prints a table that can be pasted into an issue for the lab.

## Previewing a pull request

Every pull request gets a temporary copy of the site with its changes, built by Netlify (settings in `netlify.toml`). A couple of minutes after a PR is opened or updated, a **Deploy Preview** link appears in the checks at the bottom of the PR. Click it to look around before approving. Previews don't count towards visit analytics, and the live site is unaffected: it's still built by GitHub Pages.

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
- [x] Full site converted (pages, posts, people)
- [x] Merged into `main`
- [x] GitHub Pages switched on with our domain
- [x] DNS updated so sumnerlab.co.uk points here
- [x] HTTPS confirmed working
