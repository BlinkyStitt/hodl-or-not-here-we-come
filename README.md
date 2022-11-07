# HODL or Not, Here We Come

```bash
python3 -m venv venv
source venv/bin/activate
pip install -U pip setuptools wheel
pip install -r requirements.txt
tokenlists install tokens.1inch.eth
```

## Run with the defaults

```bash
brownie run --network mainnet compare
```

## Advanced mode

You can change the start and end dates: `brownie run --network mainnet compare main $START_DATE $END_DATE`.

```bash
brownie run --network mainnet compare main "2021-01-01" "now"
```

## Interactive mode

Launch an interactive shell after the script runs:

```bash
brownie run --network mainnet compare main "2021-01-01" "now" -I
```
