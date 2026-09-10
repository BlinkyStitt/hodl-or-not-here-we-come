"""Uniswap single sided liquidity amounts <https://blog.alphaventuredao.io/onesideduniswap/>"""
import logging

from brownie import Contract, ZERO_ADDRESS

from src.tokens import get_token_decimal_shift, get_token_symbol

UNISWAP_V2_ROUTER = Contract("0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D")

UNISWAP_V2_FACTORY = Contract(UNISWAP_V2_ROUTER.factory())


def calcSingleSidedDeposit(
    token0,
    token1,
    lpTotalSupply,
    reserve0,
    reserve1,
    depositToken,
    depositWei,
    otherToken,
):
    # simulate trading half the liquidity and see how that effects reserves
    (depositWei0, depositWei1, reserve0, reserve1) = _calcSwapHalfAmounts(
        reserve0,
        reserve1,
        otherToken,
        token0,
        token1,
        depositWei,
    )

    logging.debug("depositWei0: %s", depositWei0)
    logging.debug("depositWei1: %s", depositWei1)
    logging.debug("after swapping 1/2 reserve0: %s", reserve0)
    logging.debug("after swapping 1/2 reserve1: %s", reserve1)

    assert depositWei0 > 0
    assert depositWei1 > 0

    # calculate how many LP we get for minting with token0Wei+token1Wei and the updated reserves
    mintedLp = _calcMint(
        reserve0,
        reserve1,
        lpTotalSupply,
        depositWei0,
        depositWei1,
    )
    logging.debug("mintedLp: %s", mintedLp)

    return mintedLp


def calcSingleSidedWithdraw(
    lpTotalSupply, pairBalance0, pairBalance1, token0, token1, leaveToken, withdrawLpWei
):
    # withdraw both sides
    (withdraw0, withdraw1) = _calcBurn(
        pairBalance0,
        pairBalance1,
        lpTotalSupply,
        withdrawLpWei,
    )

    if leaveToken == token0:
        # trade withdraw0 for more token1
        withdraw1 += _calcAmountOut(withdraw0, pairBalance0, pairBalance1)
        return withdraw1
    else:
        assert leaveToken == token1

        # trade withdraw1 for more token0
        withdraw0 += _calcAmountOut(withdraw1, pairBalance1, pairBalance0)
        return withdraw0


def babylonianSqrt(y: int) -> int:
    if y > 3:
        z = y
        x = y // 2 + 1
        while x < z:
            z = x
            x = (y // x + x) // 2
    elif y != 0:
        z = 1
    else:
        z = 0
    return z


def _calcSwapHalfAmounts(
    res0,
    res1,
    toToken,
    token0,
    token1,
    from_token_total_wei,
):
    """
    Simulates swapping half of fromTokenTotalWei for toToken.
    Returns user balances and pool reserves after the trade.
    """
    assert toToken in (token0, token1)

    # TODO: DRY this up
    if toToken == token0:
        # swapping token1 -> token0
        logging.trace(
            "swapping %s to %s", get_token_symbol(token1), get_token_symbol(token0)
        )

        # figure out how much is 1/2. because of fees and the price curve, this is more complicated than just `fromTokenTotalWei / 2`
        amount_to_swap = _calcSwapHalfAmountIn(res1, from_token_total_wei)
        logging.trace(
            "calculated amount to swap: %s %s",
            amount_to_swap / get_token_decimal_shift(token1),
            get_token_symbol(token1),
        )

        # calculate what a swap will give and leave leftover
        # these two amounts are "equal" according to the pool
        token0Wei = _calcAmountOut(
            amount_to_swap,
            res1,
            res0,
        )
        token1_wei = from_token_total_wei - amount_to_swap

        # update the reserves
        res0 -= token0Wei
        res1 += amount_to_swap
    else:
        # swapping token0 -> token1
        logging.trace(
            "swapping %s to %s", get_token_symbol(token0), get_token_symbol(token1)
        )

        # figure out how much is 1/2. because of fees and the price curve, this is more complicated than just `fromTokenTotalWei / 2`
        amount_to_swap = _calcSwapHalfAmountIn(res0, from_token_total_wei)
        logging.trace(
            "calculated amount to swap: %s %s",
            amount_to_swap / get_token_decimal_shift(token0),
            get_token_symbol(token0),
        )

        # calculate what a swap will give and leave leftover
        # these two amounts are "equal" according to the pool
        token1_wei = _calcAmountOut(
            amount_to_swap,
            res0,
            res1,
        )
        token0Wei = from_token_total_wei - amount_to_swap

        # update the reserves
        res1 -= token1_wei
        res0 += amount_to_swap

    return (token0Wei, token1_wei, res0, res1)


def _calcSwapHalfAmountIn(reserveIn: int, userIn: int) -> int:
    """
    given an input amount of an asset and that asset's reserves,
    returns the amount that should be swapped to get an equal amount of the pair's other asset.
    """
    amountIn = babylonianSqrt(
        (reserveIn * (userIn * 3988000)) + (reserveIn * 3988009)
    ) - ((reserveIn * 1997) // 1994)

    assert amountIn > 0

    return amountIn


def _calcAmountOut(amountIn, reserveIn, reserveOut) -> int:
    """given an input amount of an asset and pair reserves, returns the maximum output amount of the other asset."""
    assert amountIn > 0
    assert reserveIn > 0
    assert reserveOut > 0

    amountInWithFee = amountIn * 997
    numerator = amountInWithFee * reserveOut
    denominator = reserveIn * 1000 + amountInWithFee

    return numerator // denominator


def _calcMint(
    reserve0,
    reserve1,
    lpTotalSupply,
    token0Wei,
    token1Wei,
):
    # liquidity = Math.min(amount0.mul(_totalSupply) / _reserve0, amount1.mul(_totalSupply) / _reserve1);
    return min(
        token0Wei * lpTotalSupply / reserve0, token1Wei * lpTotalSupply / reserve1
    )


def _calcBurn(
    pairBalance0,
    pairBalance1,
    lpTotalSupply,
    lpWei,
):
    # using balances instead of reserves ensures pro-rata distribution
    amount0 = lpTotalSupply * pairBalance0 // lpTotalSupply
    amount1 = lpTotalSupply * pairBalance1 // lpTotalSupply

    return (amount0, amount1)
