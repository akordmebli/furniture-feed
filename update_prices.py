name: Update variant prices

on:
  workflow_dispatch:

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: pip install requests
      - name: Run price updater
        env:
          SHOPIFY_DOMAIN: ${{ secrets.SHOPIFY_DOMAIN }}
          SHOPIFY_TOKEN: ${{ secrets.SHOPIFY_TOKEN }}
          AKORD_CSV: ${{ secrets.AKORD_CSV }}
        run: python update_prices.py
