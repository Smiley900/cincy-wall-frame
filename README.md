# Cincy Wall Frame

A web page for a framed touch screen on the wall. It shows a painting by day, goes dark at night, and a tap opens Cincinnati events and the weather.

- `index.html` is the whole page.
- `data.json` holds the events, forecast and painting list. The page re-reads it every 30 minutes.
- `restaurants.json` holds the Restaurants tab: the household's picks, nearest first, each with a QR code for its Google Maps listing. It is built by `tools/build_restaurants.py` from `tools/restaurants.json`, and the events refresh does not touch it.
- `art/` holds public-domain paintings from Wikimedia Commons.

The live page is served by GitHub Pages from the `gh-pages` branch.
