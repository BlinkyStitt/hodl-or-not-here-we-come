import arrow
import logging

from src.blocks import find_block_at
from src.tokens import get_token_contract
from src import strategy


def print_end_wei(strat_name, end_wei, end_token_decimal_shift):
    if end_wei:
        print("strategy:", strat_name, "=", end_wei / end_token_decimal_shift)

        # TODO: helper function for printing profits/losses with pretty colors


# TODO: what default dates? should probably pick a bull, a bear, and both?
def main(start_date="2022-01-01", end_date="now"):
    # TODO: default level from env var
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("web3").setLevel(logging.INFO)
    logging.getLogger("urllib3").setLevel(logging.INFO)

    # start with $10k USDC
    start_usdc = 10_000
    print("Starting with", start_usdc, "USDC")

    start_date = arrow.get(start_date)
    print("start_date: ", start_date.isoformat())

    if end_date == "now":
        end_date = arrow.now()
    else:
        end_date = arrow.get(end_date)
    print("end_date:   ", end_date.isoformat())

    start_block = find_block_at(start_date.timestamp()).number
    print("start_block:", start_block)

    end_block = find_block_at(end_date.timestamp()).number
    print("end_block:  ", end_block)

    usdc = get_token_contract("USDC")

    usdc_decimal_shift = 10 ** usdc.decimals()

    start_usdc_wei = start_usdc * usdc_decimal_shift

    end_wei = strategy.hodl_eth(start_block, usdc, start_usdc_wei, end_block)
    print_end_wei("hodl eth", end_wei, usdc_decimal_shift)

    end_wei = strategy.yearn_vault_usdc(start_block, usdc, start_usdc_wei, end_block)
    print_end_wei("yearn USDC Vault", end_wei, usdc_decimal_shift)

    # strategy: deposit into AAVE v1
    # strategy: deposit into AAVE v2
    # strategy: deposit into Compound
    # strategy: trade to ETH and deposit into AAVE v1
    # strategy: trade to ETH and deposit into AAVE v2
    # strategy: trade to ETH and deposit into Compound

    end_wei = strategy.curve_tricrypto2(start_block, start_usdc_wei, end_block)
    print_end_wei("curve tricrypto2", end_wei, usdc_decimal_shift)

    end_wei = strategy.yearn_vault_tricrypto2(
        start_block, usdc, start_usdc_wei, end_block
    )
    print_end_wei("yearn vault curve tricrypto2", end_wei, usdc_decimal_shift)

    # strategy: trade half to ETH and deposit into Uniswap V1 ETH/USDC
    # strategy: trade half to ETH and deposit into Uniswap V2 ETH/USDC
    # strategy: trade half to ETH and deposit into Uniswap V3 ETH/USDC. claim fees every 2 weeks.
