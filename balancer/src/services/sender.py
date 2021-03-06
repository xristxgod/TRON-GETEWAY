import asyncio
from decimal import Decimal
from typing import Optional, Tuple

from tronpy.tron import TAddress

from src.services.inc.node import node_tron
from src.services.helper.get_native import get_native
from src.services.service import getter, sender
from src.utils.utils import utils, helper
from src.utils.types import User, BodyOptimalFee, BodySendTransaction, BodySendToAlert
from src.utils.types import CoinHelper
from config import Config, logger


class UserValidator:
    """User validator"""
    def __init__(self, user: User):
        self.address = user.address
        self.private_key = user.privateKey

    async def validate_token_balance(self, token: str) -> Tuple[bool, Decimal]:
        """Check if the token is enough to send"""
        balance = await node_tron.balance(address=self.address, symbol=token)
        if token is not None and balance < CoinHelper.min_cost(symbol=token):
            return False, balance
        return True, balance

    async def validate_fee(self, token: str = None) -> Tuple[bool, Decimal, Decimal]:
        """Check whether the native is enough to pay the commission"""
        balance_native = await node_tron.balance(address=self.address)
        fee = await node_tron.optimal_fee(body=BodyOptimalFee(
            fromAddress=self.address, toAddress=Config.ADMIN_ADDRESS, symbol=token
        ))
        if balance_native - fee <= 0:
            return False, fee, balance_native
        return True, fee, balance_native


async def send_to_wallet_to_wallet(address: TAddress, token: str) -> Optional:
    """Resend tokens to the main wallet"""
    try:
        user = User(address=address, privateKey=await getter.get_private_key(address))
        user_validator = UserValidator(user=user)
        valid_balance, balance = await user_validator.validate_token_balance(token=token)
        if not valid_balance:
            logger.error((
                f"{utils.time_now()} | "
                f"ADDRESS: {user.address} | THE USER'S BALANCE IS TOO SMALL TO START SENDING! | "
                f"USER BALANCE: {balance} {token}"
            ))
            return
        valid_fee, fee, balance_native = await user_validator.validate_fee(token=token)
        if not valid_fee:
            logger.error((
                f"{utils.time_now()} | "
                f"ADDRESS: {user.address} | THE USER DOES NOT HAVE ENOUGH FUNDS TO PAY THE COMMISSION | "
                f"USER BALANCE: {balance_native} TRX | FEE PRICE {fee} TRX"
            ))
            if not await get_native(user.address, amount=fee):
                logger.error(f'{utils.time_now()} | THE NATIVE HAS BEEN SENT | TO: {user.address}')
                raise Exception
            await asyncio.sleep(10)
        logger.error((
            f"{utils.time_now()} | "
            f"ADDRESS: {address} | SENDING TO THE MAIN WALLET: {Config.ADMIN_ADDRESS} | "
            f"AMOUNT: {balance}"
        ))
        status, tx_id = await node_tron.send_transaction(body=BodySendTransaction(
            fromAddress=user.address,
            fromPrivateKey=user.privateKey,
            toAddress=Config.ADMIN_ADDRESS,
            amount=float(balance),
            symbol=token
        ))
        if not status:
            logger.error((
                f"{utils.time_now()} | "
                f"ADDRESS: {user.address} | THE TRANSFER TO THE MAIN WALLET DID NOT HAPPEN! | AMOUNT: {balance}"
            ))
            raise Exception
        logger.error((
            f"{utils.time_now()} | "
            f"ADDRESS: {user.address} | THE MONEY HAS BEEN SUCCESSFULLY SENT TO THE MAIN WALLET: {Config.ADMIN_ADDRESS}"
        ))
        # Notify that the wallet has been replenished
        await sender.send_to_alert(body=BodySendToAlert(
            timestamp=utils.time_now(True),
            transactionHash=tx_id,
            address=user.address,
            amount=float(balance)
        ))
    except Exception as error:
        logger.error(f"{utils.time_now()} | ERROR STEP 40: {error}")
        await helper.write_to_error(error=str(error), step=41)
        await sender.resend_to_balancer(message={"address": address, "token": token})
