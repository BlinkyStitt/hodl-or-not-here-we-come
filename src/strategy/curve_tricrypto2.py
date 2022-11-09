from brownie import Contract


def main(start_block, start_usdc_wei, end_block):
    """TODO: what about CRV farming? maybe better to just use yearn vaults"""
    if start_block < 12821148:
        # TODO: start with tricrypto and then convert to tricrypto2?
        return None

    # trade USDC to USDT on 3pool
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

    # deposit USDT into tricrypto2
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

    # withdraw tricrypto2 as USDT
    end_usdt_wei = tricrypto2_pool.calc_withdraw_one_coin(
        start_tricrypto2_wei,
        usdt_tricrypto_id,
        block_identifier=end_block,
    )

    # trade USDT to USDC
    end_usdc_wei = three_pool.get_dy(
        usdt_3pool_id, usdc_3pool_id, end_usdt_wei, block_identifier=end_block
    )

    return end_usdc_wei
