import logging

from brownie import Contract

from src.yearn import vault_earnings


def main(start_block, start_token, start_wei, end_block):
    if start_block < 13513457:
        # TODO: i think there have been multiple vaults. not sure the best way to pick the best one for each block range
        return None

    start_symbol = start_token.symbol()
    assert start_symbol == "USDC"

    start_usdc_wei = start_wei

    # trade USDC to USDT on 3pool
    # TODO: move this to a helper function. probably using an on-chain router that finds the best price
    three_pool = Contract("0xbEbc44782C7dB0a1A60Cb6fe97d0b483032FF1C7")

    usdc_3pool_id = 1
    usdc = Contract(three_pool.coins(usdc_3pool_id))
    assert usdc.symbol() == "USDC"

    usdt_3pool_id = 2
    usdt = Contract(three_pool.coins(usdt_3pool_id))
    assert usdt.symbol() == "USDT"

    start_usdt_wei = three_pool.get_dy(
        usdc_3pool_id, usdt_3pool_id, start_usdc_wei, block_identifier=start_block
    )

    usdc_decimal_shift = 10 ** usdc.decimals()
    usdt_decimal_shift = 10 ** usdt.decimals()
    logging.debug(
        "traded %s USDC to %s USDT",
        start_usdc_wei / usdc_decimal_shift,
        start_usdt_wei / usdt_decimal_shift,
    )

    # deposit USDT into tricrypto2 pool
    tricrypto2_pool = Contract("0xD51a44d3FaE010294C616388b506AcdA1bfAAE46")

    usdt_tricrypto_id = 0
    assert tricrypto2_pool.coins(usdt_tricrypto_id) == usdt.address

    calc_token_amount_inputs = [0] * 3
    calc_token_amount_inputs[usdt_tricrypto_id] = start_usdt_wei

    start_tricrypto2_wei = tricrypto2_pool.calc_token_amount(
        calc_token_amount_inputs,
        True,
        block_identifier=start_block,
    )

    tricrypto2_token = Contract(tricrypto2_pool.token())
    tricrypto2_decimal_shift = 10 ** tricrypto2_token.decimals()

    logging.debug(
        "traded %s USDT to %s tricrypto2",
        start_usdt_wei / usdt_decimal_shift,
        start_tricrypto2_wei / tricrypto2_decimal_shift,
    )

    # deposit tricrypto2 pool shares into yearn and wait until end block
    end_tricrypto2_wei = vault_earnings(
        "0xE537B5cc158EB71037D4125BDD7538421981E6AA",
        start_block,
        tricrypto2_token,
        start_tricrypto2_wei,
        end_block,
    )

    # withdraw tricrypto2 as USDT
    # TODO: there might be better paths
    end_usdt_wei = tricrypto2_pool.calc_withdraw_one_coin(
        end_tricrypto2_wei,
        usdt_tricrypto_id,
        block_identifier=end_block,
    )
    logging.debug(
        "traded %s tricrypto2 to %s USDT",
        end_tricrypto2_wei / tricrypto2_decimal_shift,
        end_usdt_wei / usdt_decimal_shift,
    )

    # trade USDT to USDC
    # TODO: there might be better paths
    end_usdc_wei = three_pool.get_dy(
        usdt_3pool_id, usdc_3pool_id, end_usdt_wei, block_identifier=end_block
    )
    logging.debug(
        "traded %s USDT to %s USDC",
        end_usdt_wei / usdt_decimal_shift,
        end_usdc_wei / usdc_decimal_shift,
    )

    return end_usdc_wei
