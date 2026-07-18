import re
import os

filenames = os.listdir('original_archives')

def parse_filename(filename):
    # Regex for sides: looks for 4-0, 4.0, 4-4, 4.4
    sides_match = re.search(r'4[-.][04]', filename)
    sides = sides_match.group(0) if sides_match else None
    
    # Regex for order number: looks for (number-NUMBER) and extracts NUMBER
    order_match = re.search(r'\((\d+)-(\d+)\)', filename)
    order_number = order_match.group(2) if order_match else None
    
    return sides, order_number

for f in filenames:
    if f.endswith('.rar'):
        sides, order = parse_filename(f)
        print(f"Sides: {sides}, Order: {order} | File: {f}")
        if not sides or not order:
            print("  ---> PARSE ERROR")
