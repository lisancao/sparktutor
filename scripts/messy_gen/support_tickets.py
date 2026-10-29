"""Sample data for "Running a Model over Your Data with pandas UDFs".

Writes out/support_tickets/:
  train.csv               labelled tickets (ticket_id, text, label) for training on the driver
  inbox/part-0000N.jsonl  unlabelled tickets to classify at scale (ticket_id, channel, text)
  inbox_labels.csv        the answer key for the inbox (ticket_id, label)

The four labels match the policy documents in docs/: shipping, returns, warranty
and privacy. The inbox is messy on purpose: shouting, HTML, emoji, extra
whitespace, a few tickets that mix two topics, and a few with no usable text
(empty, only whitespace or punctuation, or null); their label is "unknown".
"""
import csv
import json
import random
from pathlib import Path

PHRASES = {
    "shipping": [
        "where is my order", "my package has not arrived", "the tracking number does not work",
        "delivery is late", "do you offer express shipping to {country}",
        "how long does shipping take", "the courier left no note", "it still says not shipped",
        "can I change the delivery address", "the parcel is stuck in transit",
        "standard shipping is taking forever", "when will my order be delivered",
    ],
    "returns": [
        "I want to return this", "how do I get a refund", "can I send it back",
        "I would like an exchange for a bigger size", "the box is still unopened",
        "I want my money back", "wrong size, please take it back", "refund has not arrived",
        "return label is missing", "I changed my mind about this purchase",
        "please refund the original payment", "how many days do I have to return items",
    ],
    "warranty": [
        "the item arrived broken", "it stopped working after a week", "the screen is cracked",
        "the battery does not charge", "is this covered by the warranty", "it is defective",
        "can you repair it", "batteries died after two months", "the charger is faulty",
        "the device keeps turning off", "one year warranty claim", "the electronics are damaged",
    ],
    "privacy": [
        "please delete my data", "unsubscribe me from marketing emails",
        "what personal information do you store", "remove my email address",
        "I want a copy of my account data", "how long do you keep my order history",
        "stop sending me promotions", "gdpr request for deletion", "close my account and erase my data",
        "who do you share my information with", "update my privacy settings",
        "I did not consent to marketing",
    ],
}
OPENERS = ["", "Hi,", "Hello,", "Hello team,", "Hey there,", "Good morning,", "To whom it may concern,"]
CLOSERS = ["", "Thanks.", "Thank you!", "Please help.", "Regards, a customer", "Cheers"]
COUNTRIES = ["Canada", "Vietnam", "the US", "Germany"]
CHANNELS = ["email", "chat", "web_form"]
NO_TEXT = ["", "   ", "?!", "...", None]


def ticket_text(rng, label):
    parts = [rng.choice(OPENERS)]
    for phrase in rng.sample(PHRASES[label], rng.randint(1, 2)):
        parts.append(phrase.format(country=rng.choice(COUNTRIES)) + rng.choice([".", "?", "!", ""]))
    if rng.random() < 0.5:
        parts.append(f"Order {rng.randint(1000, 1999)}.")
    parts.append(rng.choice(CLOSERS))
    return " ".join(p for p in parts if p)


def messy(rng, text):
    """Make a clean ticket look like real input."""
    roll = rng.random()
    if roll < 0.12:
        return text.upper()
    if roll < 0.22:
        return f"<p>{text}</p><br>"
    if roll < 0.30:
        return text + " \U0001F621\U0001F621"
    if roll < 0.38:
        return "  " + text.replace(" ", "   ") + "\n\n"
    return text


def generate(out: Path) -> None:
    rng = random.Random(2020)
    base = out / "support_tickets"
    (base / "inbox").mkdir(parents=True, exist_ok=True)
    labels = list(PHRASES)

    # ------------------------------------------------------------ training set: clean, balanced
    with open(base / "train.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ticket_id", "text", "label"])
        n = 0
        for label in labels:
            for _ in range(40):
                n += 1
                w.writerow([f"T{n:04d}", ticket_text(rng, label), label])

    # ------------------------------------------------------------ inbox: messy, unlabelled
    answers = []
    n = 0
    for part in range(4):
        with open(base / "inbox" / f"part-{part:05d}.jsonl", "w") as f:
            for _ in range(60):
                n += 1
                tid = f"I{n:04d}"
                if rng.random() < 0.04:
                    text, label = rng.choice(NO_TEXT), "unknown"
                else:
                    label = rng.choice(labels)
                    text = ticket_text(rng, label)
                    if rng.random() < 0.08:
                        # a second, weaker topic: one phrase from another label
                        other = rng.choice([x for x in labels if x != label])
                        text += " Also, " + rng.choice(PHRASES[other]).format(country="Canada") + "."
                    text = messy(rng, text)
                f.write(json.dumps({"ticket_id": tid, "channel": rng.choice(CHANNELS), "text": text},
                                   ensure_ascii=False) + "\n")
                answers.append((tid, label))
    with open(base / "inbox_labels.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ticket_id", "label"])
        w.writerows(answers)
