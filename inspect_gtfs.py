import csv
import io
import itertools
import sys
import zipfile

if len(sys.argv) < 2:
    sys.exit("Usage: python inspect_gtfs.py path\\to\\dmrc_gtfs.zip")

z = zipfile.ZipFile(sys.argv[1])
names = z.namelist()
print("Files in the zip:", names)


def rows(filename):
    match = [n for n in names if n.lower().endswith(filename)]
    if not match:
        return None
    f = z.open(match[0])
    return csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))


for filename in ("stops.txt", "routes.txt", "trips.txt", "stop_times.txt"):
    reader = rows(filename)
    print(f"\n=== {filename} ===")
    if reader is None:
        print("not found")
        continue
    print("columns:", reader.fieldnames)
    for row in itertools.islice(reader, 3):
        print(row)

# Which stops match the central Delhi stations we care about?
print("\n=== stops matching central Delhi names ===")
keys = ("patel", "rajiv", "central sec", "janpath", "mandi", "barakhamba",
        "jantar", "udyog", "khan market")
reader = rows("stops.txt")
if reader:
    for row in reader:
        name = (row.get("stop_name") or "").lower()
        if any(k in name for k in keys):
            print(row.get("stop_id"), "|", row.get("stop_name"), "|",
                  row.get("stop_lat"), row.get("stop_lon"))