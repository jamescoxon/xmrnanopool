from monero.wallet import Wallet
from monero.backends.jsonrpc import JSONRPCWallet
import time
import requests
from decimal import *

w = Wallet(JSONRPCWallet(port=28088))

import redis

r = redis.Redis(decode_responses=True)

monero_address = w.address()
monero_balance = w.balance()

print(monero_address)
print(monero_balance)

last_block = 0
if r.exists('last_block'):
    last_block = r.get('last_block')
else:
    r.set('last_block', 0)
    last_block = 0

while True:
    last_transaction = w.incoming(min_height=int(last_block))
    print(last_transaction)
    if len(last_transaction) > 0:
        print('Setting last_block')
        last_block = int(last_transaction[0].transaction.height) + 1
        r.set('last_block', last_block)
        r.set('last_amount', str(last_transaction[0].amount))

        print('Get latest pool data')
        x = requests.get('http://localhost:44733/1/workers')
        worker_json = x.json()

        total_shares = 0
        worker_shares = {}
        for worker in worker_json['workers']:
#            print('{} {}'.format(worker[0], worker[3]))

            current_shares = int(worker[3])
            # Calculate accepted shares for this round
            if r.exists(worker[0]):
                total_worker_shares = int(r.get(worker[0]))
            else:
                total_worker_shares = 0

            accepted_shares = current_shares - total_worker_shares

            # Add to our dict
            worker_shares[worker[0]] = accepted_shares

            # Store in Redis the total accepted shares 
            r.set(worker[0], current_shares)
            # Store in Redis the accepted shares for this round
            r.set('{}-{}'.format(str(last_block), worker[0]), accepted_shares)

            total_shares = total_shares + accepted_shares

        check_total = 0
        nano_total_amount_raw = 0
        for worker in worker_shares:
            # Nano amount (we will get this by parsing account)
            nano_total_amount_raw = 100

            # Calculate share
            nano_share_raw = Decimal(nano_total_amount_raw) * (Decimal(worker_shares[worker]) / Decimal(total_shares))
            print('{} {} {} {} {}'.format(worker, worker_shares[worker], total_shares, nano_share_raw, nano_total_amount_raw))

            check_total = check_total + nano_share_raw

        if check_total == nano_total_amount_raw:
            check_adds_up = True
        else:
            check_adds_up = False

        print('{} {} {}'.format(check_total, nano_total_amount_raw, check_adds_up ))

    time.sleep(5)




