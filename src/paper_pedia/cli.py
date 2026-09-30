import argparse
from .server.service import get_papers, refresh_catalog
from .scraper.venues import VENUES
def main():
    parser = argparse.ArgumentParser(description="Paper Pedia local paper cache")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("catalog", help="Refresh the venue catalog")
    scrape = commands.add_parser("scrape", help="Fetch one venue/year/group")
    scrape.add_argument("--venue", required=True, help="For example CVPR.2026")
    scrape.add_argument("--group", default="")
    scrape.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    if args.command == "catalog":
        print(f"Saved {len(refresh_catalog()['venues'])} venues to catalog.json")
    else:
        venue, year = args.venue.rsplit(".", 1)
        papers, path = get_papers(venue, int(year), args.group, args.refresh)
        print(f"Saved {len(papers)} papers: {path}")
if __name__ == "__main__": main()
