source "https://rubygems.org"

gem "jekyll", "~> 4.3"

group :jekyll_plugins do
  gem "jekyll-feed"
  gem "jekyll-sitemap"
  gem "jekyll-seo-tag"
  gem "jekyll-redirect-from"
end

# GitHub Pages runs on Windows/Linux CI; this silences a common local warning on some platforms
gem "webrick", "~> 1.8"

# Ruby 3.4+ dropped these from default gems; older Jekyll/github-pages deps still expect them
gem "csv"
gem "base64"
gem "logger"
gem "bigdecimal"
