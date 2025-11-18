# Fixing Failed Legislation Downloads

## Problem

Some Cook Islands legislation acts fail to download because their Legal IDs in the API response don't match the actual download endpoint IDs.

## Solution

We have a two-step automated workflow:

1. **download_legislation.py** - Attempts to download all acts, outputs failed items as JSON
2. **find_download_ids.py** - Uses Playwright to scrape the actual download URLs and extract correct IDs

## Quick Fix (Docker Container)

```bash
# SSH into TrueNAS
ssh claude-truenas

# Exec into the running container
docker exec -it ai-manako-tika bash

# Inside container, run the automated fix script
cd /app
./fix_failed_downloads.sh
```

This will:
1. Run the download script
2. Extract failures automatically
3. Use Playwright to find correct IDs
4. Display the ID mappings

## Manual Usage

### Step 1: Download and identify failures

```bash
python download_legislation.py
```

This outputs:
```
Failed downloads:
  - SHORT TERM CROP LEASES ACT 1966 (LOCI.STCLA)
  - WANDERING ANIMALS ACT 1976 (LOCI.WANDA)
  ...

JSON format (for find_download_ids.py):
[
  {
    "act_name": "SHORT TERM CROP LEASES ACT 1966",
    "legal_id": "LOCI.STCLA"
  },
  ...
]
```

### Step 2: Find correct IDs

**Option A: Pipe the JSON directly**

```bash
python download_legislation.py 2>&1 | \
  grep -A 1000 'JSON format' | \
  grep -A 1000 '^\[' | \
  sed '/^$/q' | \
  xargs -0 python find_download_ids.py
```

**Option B: Interactive paste**

```bash
python find_download_ids.py
# Paste the failed items (either JSON or line format)
# Press Ctrl+D when done
```

**Option C: From command line argument**

```bash
python find_download_ids.py '[{"act_name":"SHORT TERM CROP LEASES ACT 1966","legal_id":"LOCI.STCLA"}]'
```

### Step 3: Use the correct IDs

The script will output mappings like:

```
Results:
  LOCI.STCLA -> LOCI.STCL66
  LOCI.WANDA -> LOCI.WA76
```

You can then:

1. **Manual download** - Update the Legal IDs and re-run
2. **Create ID mapping** - Add a mapping table to download_legislation.py:

```python
# Known ID mismatches
ID_MAPPINGS = {
    'LOCI.STCLA': 'LOCI.STCL66',
    'LOCI.WANDA': 'LOCI.WA76',
    # ... add more as discovered
}

# In download_pdf_with_retry():
legal_id = ID_MAPPINGS.get(legal_id, legal_id)
```

## Input Formats Supported

The `find_download_ids.py` script accepts:

1. **JSON array** (from download_legislation.py):
   ```json
   [{"act_name": "...", "legal_id": "LOCI.XXX"}]
   ```

2. **Line format** (human-readable):
   ```
   - SHORT TERM CROP LEASES ACT 1966 (LOCI.STCLA)
   - WANDERING ANIMALS ACT 1976 (LOCI.WANDA)
   ```

3. **Command line argument**:
   ```bash
   python find_download_ids.py '<json_string>'
   ```

## How It Works

1. **download_legislation.py** hits the API `/download_pdf_consolidated_law/{legal_id}`
2. Some IDs return 404 because the API metadata doesn't match the actual endpoint
3. **find_download_ids.py** uses Playwright to:
   - Navigate to the act's page on cookislandslaws.gov.ck
   - Click the "Download" button
   - Intercept the network request to capture the real download URL
   - Extract the correct Legal ID from that URL

## Troubleshooting

**"No download URL captured"** - The page structure may have changed. Check:
- Is the website accessible?
- Has the download button selector changed?
- Is JavaScript enabled in Playwright?

**Timeout errors** - Increase timeout in find_download_ids.py:
```python
await page.goto(url, wait_until="networkidle", timeout=60000)  # 60 seconds
```

## Next Improvement

Consider storing discovered ID mappings in a JSON file that both scripts can reference:

```json
{
  "LOCI.STCLA": "LOCI.STCL66",
  "LOCI.WANDA": "LOCI.WA76"
}
```

This way mappings persist across runs and don't need to be re-discovered.
