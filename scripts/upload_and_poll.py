#!/usr/bin/env python3
"""
Simple helper to upload a PDF to the local server and poll for analysis completion.
Usage:
    python scripts/upload_and_poll.py path/to/lease.pdf --host http://127.0.0.1:5000

This tool will POST the file to /process_lease_pdf, print the immediate response,
then poll /analysis_status/<job_id> until status is 'done' or 'error'.
"""
import argparse
import time
import requests


def main():
    p = argparse.ArgumentParser()
    p.add_argument('pdf', help='Path to PDF file to upload')
    p.add_argument('--host', default='http://127.0.0.1:5000', help='API base URL')
    p.add_argument('--timeout', type=int, default=120, help='Polling timeout seconds')
    args = p.parse_args()

    url = args.host.rstrip('/') + '/process_lease_pdf'
    print(f'Uploading {args.pdf} -> {url}')
    try:
        with open(args.pdf, 'rb') as f:
            files = {'file': (args.pdf, f, 'application/pdf')}
            r = requests.post(url, files=files, timeout=60)
    except Exception as e:
        print('Upload failed:', e)
        return

    try:
        resp = r.json()
    except Exception:
        print('Unexpected response:', r.status_code)
        print(r.text)
        return

    print('Immediate response:', resp)
    job_id = resp.get('job_id')
    if not job_id:
        print('No job_id returned; nothing to poll.')
        return

    status_url = args.host.rstrip('/') + f'/analysis_status/{job_id}'
    print('Polling', status_url)
    start = time.time()
    while True:
        try:
            pr = requests.get(status_url, timeout=20)
            jr = pr.json()
        except Exception as e:
            print('Polling error:', e)
            jr = None

        if jr:
            print('Status:', jr.get('status'))
            if jr.get('status') in ('done', 'error'):
                print('Final result:')
                print(jr.get('result'))
                return

        if time.time() - start > args.timeout:
            print('Timed out waiting for job to complete')
            return

        time.sleep(2)


if __name__ == '__main__':
    main()
