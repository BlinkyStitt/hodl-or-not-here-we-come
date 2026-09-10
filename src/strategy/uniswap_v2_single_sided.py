import logging

from brownie import Contract

from src.tokens import get_token_contract, get_token_decimal_shift, get_token_symbol
from src.uniswap_v2 import (
    UNISWAP_V2_FACTORY,
    calcSingleSidedDeposit,
    calcSingleSidedWithdraw,
)


def main(start_block, start_token, other_token, start_wei, end_block):
    pair = Contract(UNISWAP_V2_FACTORY.getPair(start_token, other_token))
    logging.trace("pair: %s", pair.address)

    token0 = Contract(pair.token0())
    token1 = Contract(pair.token1())
    logging.trace("token0: %s", token0.symbol())
    logging.trace("token1: %s", token1.symbol())

    lp_start_supply = pair.totalSupply(block_identifier=start_block)
    (reserve0, reserve1, _) = pair.getReserves(block_identifier=start_block)

    logging.trace(
        "start lpTotalSupply: %s", lp_start_supply / get_token_decimal_shift(pair)
    )
    logging.trace("start reserve0: %s", reserve0 / get_token_decimal_shift(token0))
    logging.trace("start reserve1: %s", reserve1 / get_token_decimal_shift(token1))

    # single sided deposit of USDC into USDC/WETH UNI-V2
    lpWei = calcSingleSidedDeposit(
        token0,
        token1,
        lp_start_supply,
        reserve0,
        reserve1,
        start_token,
        start_wei,
        other_token,
    )

    # get values at end block
    # we add in our extra. this isn't perfect but i think its close enough
    lpEndSupply = pair.totalSupply(block_identifier=end_block) + lpWei

    balance0 = token0.balanceOf(pair, block_identifier=end_block)
    balance1 = token1.balanceOf(pair, block_identifier=end_block)

    if start_token == token0:
        balance0 += start_wei
    else:
        assert start_token == token1
        balance1 += start_wei

    # single sided withdraw from USDC/WETH UNI-V2 to USDC
    endWei = calcSingleSidedWithdraw(
        lpEndSupply, balance0, balance1, token0, token1, other_token, lpWei
    )
    logging.debug(
        "end %s: %s",
        get_token_symbol(start_token),
        endWei / get_token_decimal_shift(start_token),
    )

    return endWei
