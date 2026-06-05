import csv
import io
from typing import List, Any

def generate_csv_with_bom(headers: List[str], rows: List[List[Any]]) -> bytes:
    """Generates a CSV file as bytes, encoded in UTF-8 with BOM prefix."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)
    
    # Return as bytes prefixed with the UTF-8 Byte Order Mark (BOM)
    bom = b'\xef\xbb\xbf'
    return bom + output.getvalue().encode('utf-8')
