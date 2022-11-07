import arrow
from brownie import chain, Contract

from src.blocks import find_block_at
from tokenlists import TokenListManager


# TODO: what default dates? should probably pick a bull, a bear, and both?
def main(start_date="2022-01-01", end_date="now"):
    start_usdc = 10_000

    start_date = arrow.get(start_date)

    if end_date == "now":
        end_date = arrow.now()
    else:
        end_date = arrow.get(end_date)

    start_block = find_block_at(start_date.timestamp())
    end_block = find_block_at(end_date.timestamp())

    print("start_block:", start_block.number)
    print("end_block:  ", end_block.number)

    tlm = TokenListManager()

    usdc = Contract(tlm.get_token_info("USDC").address)
    usdt = Contract(tlm.get_token_info("USDT").address)

    usdc_wei = start_usdc * 10 ** usdc.decimals()
