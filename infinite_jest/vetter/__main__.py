"""python3 -m infinite_jest.vetter "Full Name" --booked 2026-12-01 --hint "New School" --hint actor"""

import argparse
import sys

from . import llm, store, vet, web


def main(argv=None):
    ap = argparse.ArgumentParser(prog="vetter", description="Build a guest file on this machine from public pages.")
    ap.add_argument("name", nargs="?")
    ap.add_argument("--booked", help="booking date (required to research anyone)")
    ap.add_argument("--hint", action="append", default=[], help="something the guest told us: school, city, job")
    ap.add_argument("--url", action="append", default=[], help="a page the guest gave us as their own")
    ap.add_argument("--export", action="append", default=[],
                    help="the guest's own Instagram or Facebook download (zip or folder), handed over by them")
    ap.add_argument("--years", type=int, default=1, help="how far back to read (terms: 1). 0 = no limit, "
                    "only for someone who agreed to that")
    ap.add_argument("--group", choices=sorted(vet.rules.PRIORS))
    ap.add_argument("--no-model", action="store_true", help="word lists only, do not ask the local model")
    ap.add_argument("--dir", help="where guest files live")
    ap.add_argument("--show", action="store_true", help="print the guest's file (for the guest, on request)")
    ap.add_argument("--delete", action="store_true", help="delete the guest's file now")
    ap.add_argument("--purge", action="store_true", help="delete every file past its delete date")
    a = ap.parse_args(argv)
    if a.purge:
        print("deleted:", ", ".join(store.purge(root=a.dir)) or "nothing was due")
        return 0
    if not a.name:
        ap.error("a name is needed")
    if a.show:
        print(store.show(a.name, a.dir) or "no file is held for this name")
        return 0
    if a.delete:
        print("deleted" if store.delete(a.name, a.dir) else "no file was held for this name")
        return 0
    model = None if a.no_model else llm.LocalModel()
    try:
        data, _ = vet.vet(a.name, web.Web(), hints=a.hint, urls=a.url, group=a.group, booked=a.booked,
                          model=model, root=a.dir, export=a.export, years=a.years)
    except ValueError as e:
        print("refused:", e, file=sys.stderr)
        return 2
    o = data["ocean_detail"]
    print(f"{data['name']}: {len(data['sources'])} pages read, {len(data['skipped_other_person'])} left out, "
          f"{len(data['quotes'])} quotes" + (" (thin: treat as a stranger)" if data["thin"] else ""))
    print("  " + "  ".join(f"{t} {o[t]['pct']}±{o[t]['range']}" for t in "OCEAN") + f"  first room: {data['hook']}")
    print("  file:", data["folder"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
