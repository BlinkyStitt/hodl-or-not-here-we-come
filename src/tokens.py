from brownie import Contract
from tokenlists import TokenListManager

# global variables. bleh
TLM = TokenListManager()


def get_token_contract(symbol):
    """Case-sensitive lookup of tokens."""
    return Contract(TLM.get_token_info(symbol).address)
