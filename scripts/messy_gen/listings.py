"""Sample data for "Building LSH and an IVF Vector Index".

Writes out/listings/listings.jsonl: a second-hand marketplace's listings
(listing_id, seller, posted, title, description, price), one JSON object per
line. Sellers repost the same item again and again, and every repost is a
little different, which is what makes near-duplicate search necessary:

- reposts with the price changed, words in another case, punctuation
  added or removed, a typo, a sentence added ("Still available!") or a
  sentence dropped;
- a few sellers who post many different items from one template, so their
  listings share most of their text without being the same item;
- boilerplate that many unrelated listings share ("Pick up only. Cash
  only."), so some short pieces of text appear in hundreds of listings;
- prices written in several ways ("$120", "120.00", "120 CAD", "OBO").

There is no answer key on purpose: the lesson computes the exact Jaccard
similarity of every pair and measures LSH against it.
"""
import json
import random
from datetime import date, timedelta
from pathlib import Path

ITEMS = [
    ("oak dining table", "solid oak dining table, seats six, a few light scratches on the top"),
    ("ikea billy bookcase", "white billy bookcase, two extra shelves, assembled once and never moved"),
    ("standing desk", "electric standing desk with memory presets, 140 by 70 cm top, quiet motor"),
    ("road bike", "aluminium road bike, 54 cm frame, new tyres and chain this spring"),
    ("mountain bike", "full suspension mountain bike, hydraulic disc brakes, size medium"),
    ("espresso machine", "dual boiler espresso machine, descaled monthly, comes with two baskets"),
    ("gaming monitor", "27 inch gaming monitor, 165 hz, no dead pixels, original box"),
    ("office chair", "ergonomic office chair, adjustable lumbar support and arms, mesh back"),
    ("leather sofa", "three seat leather sofa, brown, pet free and smoke free home"),
    ("baby stroller", "travel system stroller with car seat adapter, folds with one hand"),
    ("kayak", "sit on top kayak with paddle and seat, stored indoors over winter"),
    ("snowboard", "all mountain snowboard 156 with bindings, waxed last season"),
    ("vinyl records", "box of about forty jazz and soul records, mostly first pressings"),
    ("acoustic guitar", "dreadnought acoustic guitar, solid spruce top, hard case included"),
    ("sewing machine", "computerised sewing machine, 100 stitches, barely used"),
    ("air fryer", "5 litre air fryer, dishwasher safe basket, works perfectly"),
    ("bunk bed", "solid pine bunk bed, converts to two single beds, mattresses not included"),
    ("lawn mower", "cordless lawn mower with two batteries and charger, 40 cm cut"),
    ("camera lens", "50mm f1.8 prime lens, clean glass, front and rear caps"),
    ("bread maker", "programmable bread maker, gluten free setting, recipe book included"),
    ("dresser", "six drawer dresser in walnut veneer, drawers glide smoothly"),
    ("tent", "four person dome tent, footprint and repair kit included, no leaks"),
    ("treadmill", "folding treadmill, 12 programs, max speed 16 km/h, manual included"),
    ("piano keyboard", "88 key weighted digital piano with stand and sustain pedal"),
    ("aquarium", "120 litre aquarium with filter, heater and led light, fish not included"),
]
ADJ = ["great", "excellent", "good", "like new", "gently used", "very good", "decent", "mint"]
CONDITION = ["Works perfectly.", "Some wear, see photos.", "No issues at all.",
             "Small mark on one side.", "Cleaned and ready to go.", "Barely used."]
REASON = ["Moving out of town.", "Upgraded to a new one.", "No longer needed.",
          "Downsizing.", "Kids outgrew it.", "Making space."]
EXTRA = ["Still available!", "Price drop!", "Must go this week.", "Serious buyers only.",
         "Can deliver for a small fee.", "Open to offers."]
BOILERPLATE = ["Pick up only. Cash only.", "No holds, first come first served.",
               "Please do not ask if it is still available, the ad is up.",
               "E-transfer or cash on pickup."]
CITIES = ["Montreal", "Laval", "Longueuil", "Verdun", "Rosemont", "Plateau"]
TEMPLATE_SELLERS = {
    "deals_by_marc": "Marc's Furniture Outlet. {item} in {adj} condition. All our items are cleaned "
                     "and inspected. Delivery available across the island. Visit our warehouse "
                     "Saturday and Sunday 10 to 4. Financing available.",
    "liquidation_pro": "LIQUIDATION SALE!!! {item}, {adj} condition, priced to sell. Hundreds of items "
                       "in stock, new arrivals every week. Text for the full catalogue. "
                       "We buy estates and moving sales.",
}


def _price(rng, base):
    style = rng.randrange(5)
    if style == 0:
        return f"${base}"
    if style == 1:
        return f"{base}.00"
    if style == 2:
        return f"{base} CAD"
    if style == 3:
        return f"${base} OBO"
    return str(base)


def _typo(rng, text):
    words = text.split(" ")
    i = rng.randrange(len(words))
    w = words[i]
    if len(w) > 3:
        j = rng.randrange(1, len(w) - 1)
        w = w[:j] + w[j + 1] + w[j] + w[j + 2:]
        words[i] = w
    return " ".join(words)


def _edit(rng, desc, sentences):
    """A repost: the same ad with one to three small edits."""
    for _ in range(rng.randint(1, 3)):
        kind = rng.randrange(6)
        if kind == 0:
            desc = _typo(rng, desc)
        elif kind == 1:
            desc = desc.upper() if rng.random() < 0.3 else desc.lower()
        elif kind == 2:
            desc = desc.replace(", ", " ").replace(".", "") if rng.random() < 0.5 else desc + "!"
        elif kind == 3:
            desc = desc + " " + rng.choice(EXTRA)
        elif kind == 4 and len(sentences) > 2:
            drop = rng.choice(sentences[1:])
            desc = desc.replace(" " + drop, "")
        else:
            desc = rng.choice(EXTRA) + " " + desc
    return desc


def generate(out: Path) -> None:
    rng = random.Random(4848)
    d = out / "listings"
    d.mkdir(parents=True, exist_ok=True)
    rows = []
    start = date(2026, 9, 1)
    next_id = 1

    def emit(seller, posted, title, desc, price):
        nonlocal next_id
        rows.append({"listing_id": f"L{next_id:04d}", "seller": seller, "posted": posted.isoformat(),
                     "title": title, "description": desc, "price": price})
        next_id += 1

    # Ordinary sellers: an original ad, sometimes reposted with edits.
    for s in range(150):
        seller = f"user{s:03d}"
        title, base = rng.choice(ITEMS)
        sentences = [f"{rng.choice(ADJ).capitalize()} {base}.", rng.choice(CONDITION),
                     rng.choice(REASON)]
        if rng.random() < 0.5:
            sentences.append(rng.choice(BOILERPLATE))
        sentences.append(f"Located in {rng.choice(CITIES)}.")
        desc = " ".join(sentences)
        price = rng.randrange(20, 900, 5)
        posted = start + timedelta(days=rng.randrange(20))
        emit(seller, posted, title, desc, _price(rng, price))
        reposts = rng.choice([0, 0, 0, 1, 1, 2, 3, 5])
        for _ in range(reposts):
            posted += timedelta(days=rng.randint(1, 4))
            price = max(10, price - rng.choice([0, 0, 10, 25, 50]))
            emit(seller, posted, title, _edit(rng, desc, sentences), _price(rng, price))

    # Template sellers: many different items, one shared template.
    for seller, template in TEMPLATE_SELLERS.items():
        for _ in range(20):
            title, base = rng.choice(ITEMS)
            desc = template.format(item=base.capitalize(), adj=rng.choice(ADJ))
            emit(seller, start + timedelta(days=rng.randrange(28)), title, desc,
                 _price(rng, rng.randrange(50, 1500, 10)))

    rng.shuffle(rows)
    with open(d / "listings.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
