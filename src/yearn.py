import logging

from brownie import Contract


def vault_earnings(vault, start_block, underlying, start_wei, end_block):
    vault = Contract(vault)

    assert vault.token() == underlying.address

    underlying_symbol = underlying.symbol()
    underlying_decimal_shift = 10 ** underlying.decimals()

    start_pps = vault.pricePerShare(block_identifier=start_block)
    logging.debug("start pps: %s", start_pps / underlying_decimal_shift)

    end_pps = vault.pricePerShare(block_identifier=end_block)
    logging.debug("end pps: %s", end_pps / underlying_decimal_shift)

    pps_delta = end_pps - start_pps
    logging.debug("pps delta: %s", pps_delta / underlying_decimal_shift)

    vault_wei_delta = start_wei * pps_delta // underlying_decimal_shift
    logging.debug("vault wei delta: %s", vault_wei_delta)

    end_wei = start_wei + vault_wei_delta

    logging.debug(
        "yearn vault grew %s %s into %s %s",
        start_wei / underlying_decimal_shift,
        underlying_symbol,
        end_wei / underlying_decimal_shift,
        underlying_symbol,
    )

    return end_wei
