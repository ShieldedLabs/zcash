#!/usr/bin/env python3
# Copyright (c) 2024 The Zcash developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or https://www.opensource.org/licenses/mit-license.php .

from test_framework.test_framework import BitcoinTestFramework
from test_framework.authproxy import JSONRPCException
from test_framework.util import (
    assert_equal,
    assert_false,
    assert_raises_message,
    connect_nodes_bi,
    start_nodes,
    sync_mempools,
    nuparams,
    NU5_BRANCH_ID,
    ZFUTURE_BRANCH_ID,
)
import time

from decimal import Decimal
from math import ceil

class Zip233ZsfTest(BitcoinTestFramework):

    def __init__(self):
        super().__init__()
        self.cache_behavior = 'clean'
        self.num_nodes = 2

    def setup_network(self, split = False):
        assert_false(split, False)
        self.is_network_split = False
        self.nodes = start_nodes(self.num_nodes, self.options.tmpdir, extra_args=[[
            nuparams(NU5_BRANCH_ID, 1),
            nuparams(ZFUTURE_BRANCH_ID, 103),
            '-nurejectoldversions=false',
            '-allowdeprecated=getnewaddress'
        ]] * self.num_nodes)
        connect_nodes_bi(self.nodes, 0, 1)
        self.sync_all()

    def run_test(self):
        OLD_BLOCK_REWARD = Decimal("6.25")
        COINBASE_MATURATION_BLOCK_COUNT = 100
        MAX_MONEY = 21_000_000
        TRANSACTION_FEE = Decimal("0.0001")

        def zsf_block_reward(chain_value):
            zatoshi = Decimal(100_000_000)
            issuance_reserve = (MAX_MONEY - chain_value) * zatoshi
            reward_zatoshi = ceil(issuance_reserve * 4_126 / 10_000_000_000)
            return reward_zatoshi / zatoshi

        alice, bob = self.nodes

        # Activate all upgrades up to and including NU5
        alice.generate(1)

        # Wait for our coinbase to mature and become spendable
        alice.generate(COINBASE_MATURATION_BLOCK_COUNT)

        block_height = 1 + COINBASE_MATURATION_BLOCK_COUNT
        self.sync_all()

        expected_chain_value = OLD_BLOCK_REWARD * block_height
        assert_equal(
            alice.getblockchaininfo()["chainSupply"]["chainValue"],
            expected_chain_value
        )
        assert_equal(
            bob.getblockchaininfo()["chainSupply"]["chainValue"],
            expected_chain_value
        )

        # Only the first block's coinbase has reached maturity
        assert_equal(alice.getbalance(), OLD_BLOCK_REWARD)
        assert_equal(bob.getbalance(), 0)

        bob_address = bob.getnewaddress()
        send_amount = Decimal("1.23")
        zsf_deposit_amount = Decimal("1.11")
        sendtoaddress_args = [
            bob_address,
            send_amount,
            "",
            "",
            False,
            zsf_deposit_amount
        ]

        assert_raises_message(
            JSONRPCException,
            "ZSF deposit is not supported at this block height.",
            alice.sendtoaddress,
            *sendtoaddress_args
        )

        # After this block, ZSF features will become available for inclusion in
        # the following block.
        alice.generate(1)
        block_height += 1
        expected_chain_value += OLD_BLOCK_REWARD

        # And now the same RPC call should succeed
        alice.sendtoaddress(*sendtoaddress_args)

        # Using the other node to mine ensures we test transaction serialization
        # in the mempool.
        sync_mempools([alice, bob])
        bob.generate(1)
        block_height += 1
        self.sync_all()

        # Alice's pre-upgrade coinbase continues to mature 100 blocks behind
        expected_alice_balance = (
            (OLD_BLOCK_REWARD * 3)
            - send_amount
            - zsf_deposit_amount
            - TRANSACTION_FEE
        )
        expected_bob_balance = send_amount
        expected_chain_value += zsf_block_reward(expected_chain_value) - zsf_deposit_amount

        assert_equal(alice.getbalance(), expected_alice_balance)
        assert_equal(bob.getbalance(), expected_bob_balance)

        assert_equal(
            alice.getblockchaininfo()["chainSupply"]["chainValue"],
            expected_chain_value
        )
        assert_equal(
            bob.getblockchaininfo()["chainSupply"]["chainValue"],
            expected_chain_value
        )

        #####
        # Try the same using createrawtransaction
        raw_transaction = (
            alice.createrawtransaction(
                [],
                {bob_address: send_amount},
                None,
                None,
                zsf_deposit_amount
            )
        )
        funded_transaction = alice.fundrawtransaction(raw_transaction)
        signed_transaction = alice.signrawtransaction(funded_transaction["hex"])
        transaction_hash = alice.sendrawtransaction(signed_transaction["hex"])

        assert_equal(alice.decoderawtransaction(raw_transaction)["zsfDeposit"], zsf_deposit_amount)
        assert_equal(alice.decoderawtransaction(funded_transaction["hex"])["zsfDeposit"], zsf_deposit_amount)
        assert_equal(alice.decoderawtransaction(signed_transaction["hex"])["zsfDeposit"], zsf_deposit_amount)

        alice.generate(1)
        self.sync_all()

        assert_equal(bob.getrawtransaction(transaction_hash, 1)["zsfDeposit"], zsf_deposit_amount)

        expected_alice_balance += (
            OLD_BLOCK_REWARD
            - send_amount
            - zsf_deposit_amount
            - TRANSACTION_FEE
        )
        expected_bob_balance += send_amount

        assert_equal(alice.getbalance(), expected_alice_balance)
        assert_equal(bob.getbalance(), expected_bob_balance)

        expected_chain_value += zsf_block_reward(expected_chain_value) - zsf_deposit_amount
        assert_equal(
            alice.getblockchaininfo()["chainSupply"]["chainValue"],
            expected_chain_value
        )
        assert_equal(
            bob.getblockchaininfo()["chainSupply"]["chainValue"],
            expected_chain_value
        )

        #####
        # Check that we can make a ZSF deposit without a vout
        raw_transaction = (
            alice.createrawtransaction(
                [],
                {},
                None,
                None,
                zsf_deposit_amount
            )
        )
        funded_transaction = alice.fundrawtransaction(raw_transaction)
        signed_transaction = alice.signrawtransaction(funded_transaction["hex"])
        alice.sendrawtransaction(signed_transaction["hex"])

        alice.generate(1)
        self.sync_all()

        expected_alice_balance += (
            OLD_BLOCK_REWARD
            - zsf_deposit_amount
            - TRANSACTION_FEE
        )

        assert_equal(alice.getbalance(), expected_alice_balance)
        assert_equal(bob.getbalance(), expected_bob_balance)

        expected_chain_value += zsf_block_reward(expected_chain_value) - zsf_deposit_amount
        assert_equal(
            alice.getblockchaininfo()["chainSupply"]["chainValue"],
            expected_chain_value
        )
        assert_equal(
            bob.getblockchaininfo()["chainSupply"]["chainValue"],
            expected_chain_value
        )

        #####
        # Inputs don't cover the cost of the ZSF deposit
        decoded_transaction = alice.decoderawtransaction(funded_transaction["hex"])
        raw_transaction = (
            alice.createrawtransaction(
                [
                    # The change from the previous transaction
                    {
                        "txid": decoded_transaction["txid"],
                        "vout": 0
                    }
                ],
                {},
                None,
                None,
                99999
            )
        )
        assert_raises_message(
            JSONRPCException,
            "min relay fee not met",
            alice.sendrawtransaction,
            raw_transaction
        )

        #####
        # Insufficient funds in wallet
        raw_transaction = alice.createrawtransaction([], {}, None, None, 99999)
        assert_raises_message(
            JSONRPCException,
            "Insufficient funds",
            alice.fundrawtransaction,
            raw_transaction
        )
        assert_raises_message(
            JSONRPCException,
            "Insufficient funds",
            alice.sendtoaddress,
            bob_address, 1, "", "", False, 99999
        )

        #####
        # Negative ZSF deposits
        assert_raises_message(
            JSONRPCException,
            "Amount out of range",
            alice.createrawtransaction,
            [], {}, None, None, -1
        )
        assert_raises_message(
            JSONRPCException,
            "Amount out of range",
            alice.sendtoaddress,
            bob_address, 1, "", "", False, -1
        )

        #####
        # Check that we can't make a truly empty transaction
        raw_transaction = alice.createrawtransaction([], {}, None, None, 0)
        assert_raises_message(
            JSONRPCException,
            "Transaction amounts must be positive",
            alice.fundrawtransaction,
            raw_transaction
        )

        #####
        # Deposit from coinbase transaction
        chain_value = alice.getblockchaininfo()["chainSupply"]["chainValue"]

        block_hash = alice.generate(1, zsf_deposit_amount)[0]
        self.sync_all()

        expected_coinbase_output = zsf_block_reward(chain_value) - zsf_deposit_amount
        transaction_hash = alice.getblock(block_hash)["tx"][0]
        assert_equal(
            alice.gettransaction(transaction_hash)["details"][0]["amount"],
            expected_coinbase_output
        )

        expected_chain_value = chain_value + zsf_block_reward(chain_value) - zsf_deposit_amount
        assert_equal(
            alice.getblockchaininfo()["chainSupply"]["chainValue"],
            expected_chain_value
        )
        assert_equal(
            bob.getblockchaininfo()["chainSupply"]["chainValue"],
            expected_chain_value
        )

        assert_raises_message(
            JSONRPCException,
            "Amount out of range",
            alice.generate,
            1, -1
        )

        assert_raises_message(
            JSONRPCException,
            "ZSF deposit in coinbase transaction must not exceed miner reward",
            alice.generate,
            1, 999
        )

if __name__ == '__main__':
    Zip233ZsfTest().main()
