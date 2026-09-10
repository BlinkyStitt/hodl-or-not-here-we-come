from brownie import Contract
from functools import cache
from tokenlists import TokenListManager

# global variables. bleh
TLM = TokenListManager()


@cache
def get_token_contract(symbol):
    """Case-sensitive lookup of tokens."""
    return Contract(TLM.get_token_info(symbol).address)


@cache
def get_token_decimal_shift(token):
    # TODO: sometimes they are all caps
    return 10 ** token.decimals()


@cache
def get_token_symbol(token):
    # TODO: sometimes they are all caps
    return token.symbol()
